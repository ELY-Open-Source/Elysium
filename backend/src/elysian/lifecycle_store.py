"""The memory tiers, kept out of the query layer the same way the search page is.

Working memory is what one session recorded. The ledger says what has already been rolled up.
Archived rows sit outside the current view on purpose. Recall counts are what the store observed,
not what a caller claimed, so they are written here and nowhere else.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from .db import Database
from .row_codec import from_iso, from_json, row_to_atom, to_json
from .schemas import ConflictRecord, ConsolidationRecord, EvidenceAtom


def _moment(value: str) -> datetime:
    """A ledger timestamp is never null, so a row whose date will not parse is corrupt, not empty."""
    moment = from_iso(value)
    if moment is None:
        raise ValueError(f"stored timestamp {value!r} is unreadable")
    return moment


def touch_recalls(database: Database, atom_ids: list[str], at: datetime) -> None:
    """Record that a search returned these memories, so use is a fact the store holds."""
    if not atom_ids:
        return
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE atoms
            SET recall_count = recall_count + 1, last_recalled_at = ?
            WHERE atom_id IN (SELECT value FROM json_each(?))
            """,
            (at.isoformat(), to_json(atom_ids)),
        )


def session_atoms(database: Database, holder_id: str, session_id: str) -> list[EvidenceAtom]:
    """What this session recorded and nothing else: the short-term tier, read without searching."""
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM v_atoms_current WHERE holder_id = ? AND session_id = ? ORDER BY ingested_at, atom_id",
            (holder_id, session_id),
        ).fetchall()
    return [row_to_atom(row) for row in rows]


def lane_atoms(
    database: Database, holder_id: str, scenario: str, *, after: datetime | None = None
) -> list[EvidenceAtom]:
    """Current memories of one holder and scenario, oldest first, from a watermark onward."""
    watermark = "" if after is None else after.isoformat()
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM v_atoms_current
            WHERE holder_id = ? AND scenario = ? AND (? = '' OR ingested_at > ?)
            ORDER BY ingested_at, atom_id
            """,
            (holder_id, scenario, watermark, watermark),
        ).fetchall()
    return [row_to_atom(row) for row in rows]


def read_ledger(database: Database, holder_id: str, scenario: str) -> ConsolidationRecord | None:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM consolidations WHERE holder_id = ? AND scenario = ?", (holder_id, scenario)
        ).fetchone()
    if row is None:
        return None
    return ConsolidationRecord(
        holder_id=row["holder_id"],
        scenario=row["scenario"],
        watermark_at=_moment(row["watermark_at"]),
        rollup_atom_id=row["rollup_atom_id"],
        atom_count=int(row["atom_count"]),
        token_equivalent=int(row["token_equivalent"]),
        consolidated_at=_moment(row["consolidated_at"]),
    )


def write_ledger(database: Database, record: ConsolidationRecord) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO consolidations (
                holder_id, scenario, watermark_at, rollup_atom_id, atom_count, token_equivalent, consolidated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(holder_id, scenario) DO UPDATE SET
                watermark_at=excluded.watermark_at,
                rollup_atom_id=excluded.rollup_atom_id,
                atom_count=excluded.atom_count,
                token_equivalent=excluded.token_equivalent,
                consolidated_at=excluded.consolidated_at
            """,
            (
                record.holder_id,
                record.scenario,
                record.watermark_at.isoformat(),
                record.rollup_atom_id,
                record.atom_count,
                record.token_equivalent,
                record.consolidated_at.isoformat(),
            ),
        )


def record_conflict(
    database: Database,
    *,
    older_atom_id: str,
    newer_atom_id: str,
    holder_id: str,
    scenario: str,
    terms: list[str],
    older_value: str,
    newer_value: str,
    detected_at: datetime,
) -> ConflictRecord | None:
    """Note that two memories cannot both be current. A repeat of the same pair is not a second conflict."""
    with database.connect() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO conflicts (
                older_atom_id, newer_atom_id, holder_id, scenario, terms_json,
                older_value, newer_value, detected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                older_atom_id,
                newer_atom_id,
                holder_id,
                scenario,
                to_json(terms),
                older_value,
                newer_value,
                detected_at.isoformat(),
            ),
        )
        row = connection.execute(
            "SELECT * FROM conflicts WHERE older_atom_id = ? AND newer_atom_id = ?",
            (older_atom_id, newer_atom_id),
        ).fetchone()
    return _row_to_conflict(row)


def open_conflicts(database: Database, holder_id: str | None = None) -> list[ConflictRecord]:
    """Every disagreement nobody has picked a side in, newest detection first."""
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM conflicts
            WHERE resolved_at IS NULL AND (? = '' OR holder_id = ?)
            ORDER BY detected_at DESC, conflict_id
            """,
            (holder_id or "", holder_id or ""),
        ).fetchall()
    return [_row_to_conflict(row) for row in rows]


def losing_sides(database: Database, atom_ids: list[str]) -> dict[str, str]:
    """Among these atoms, which lost to a newer one in a conflict nobody resolved.

    Both sides have to be in the list. A conflict is a claim about a pair, so an unresolved pair
    that arrives whole is settled by dropping the older side; if only the older side turned up, the
    store has not seen the replacement in this answer and says nothing about it.
    """
    if not atom_ids:
        return {}
    payload = to_json(atom_ids)
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT older_atom_id, newer_atom_id FROM conflicts
            WHERE resolved_at IS NULL
              AND older_atom_id IN (SELECT value FROM json_each(?))
              AND newer_atom_id IN (SELECT value FROM json_each(?))
            """,
            (payload, payload),
        ).fetchall()
    return {str(row["older_atom_id"]): str(row["newer_atom_id"]) for row in rows}


def resolve_conflicts(database: Database, conflict_ids: list[int], at: datetime) -> int:
    """Settle disagreements so retrieval stops suppressing a side on the store's own judgement."""
    if not conflict_ids:
        return 0
    with database.connect() as connection:
        cursor = connection.execute(
            """
            UPDATE conflicts SET resolved_at = ?
            WHERE resolved_at IS NULL AND conflict_id IN (SELECT value FROM json_each(?))
            """,
            (at.isoformat(), to_json([str(conflict_id) for conflict_id in conflict_ids])),
        )
    return int(cursor.rowcount)


def archive_atoms(database: Database, atom_ids: list[str], at: datetime) -> int:
    """Move memories out of the current tier. The rows stay; only the view stops showing them."""
    if not atom_ids:
        return 0
    with database.connect() as connection:
        cursor = connection.execute(
            """
            UPDATE atoms SET archived_at = ?
            WHERE archived_at IS NULL AND atom_id IN (SELECT value FROM json_each(?))
            """,
            (at.isoformat(), to_json(atom_ids)),
        )
    return int(cursor.rowcount)


def restore_atoms(database: Database, atom_ids: list[str]) -> int:
    """Bring archived memories back, counting only the rows that were actually archived.

    An id that was never archived changed nothing, so it is not counted: a report that says
    「restored 1」 has to mean one memory came back.
    """
    if not atom_ids:
        return 0
    with database.connect() as connection:
        cursor = connection.execute(
            "UPDATE atoms SET archived_at = NULL"
            " WHERE archived_at IS NOT NULL AND atom_id IN (SELECT value FROM json_each(?))",
            (to_json(atom_ids),),
        )
    return int(cursor.rowcount)


def archived_atoms(database: Database, holder_id: str | None = None) -> list[EvidenceAtom]:
    """The long-term tier: archived rows, which the current view hides by design."""
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM atoms
            WHERE archived_at IS NOT NULL AND (? = '' OR holder_id = ?)
            ORDER BY archived_at, atom_id
            """,
            (holder_id or "", holder_id or ""),
        ).fetchall()
    return [row_to_atom(row) for row in rows]


def stale_candidates(
    database: Database, *, before: datetime, max_importance: float | None
) -> list[str]:
    """Current memories that were ingested before the cutoff, were never returned by a search, and
    were never marked more important than the floor; an unset importance is not a reason to keep.
    """
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT atom_id FROM v_atoms_current
            WHERE ingested_at < ? AND recall_count = 0
              AND (? IS NULL OR importance IS NULL OR importance <= ?)
            ORDER BY ingested_at, atom_id
            """,
            (before.isoformat(), max_importance, max_importance),
        ).fetchall()
    return [str(row["atom_id"]) for row in rows]


def _row_to_conflict(row: sqlite3.Row) -> ConflictRecord:
    return ConflictRecord(
        conflict_id=int(row["conflict_id"]),
        older_atom_id=row["older_atom_id"],
        newer_atom_id=row["newer_atom_id"],
        holder_id=row["holder_id"],
        scenario=row["scenario"],
        terms=[str(item) for item in from_json(row["terms_json"], [])],
        older_value=row["older_value"],
        newer_value=row["newer_value"],
        detected_at=_moment(row["detected_at"]),
        resolved_at=from_iso(row["resolved_at"]),
    )
