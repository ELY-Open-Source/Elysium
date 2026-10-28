"""The holder registry and the directory query: who holds a memory, and who knows a topic.

A transactive memory system stores the directory, not the content: "I do not know where the
keys are, I know my wife knows, and I can find my wife." That requires a holder entity the
store can answer questions about, and it requires the answer to be a pointer with a reason,
never a guess.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from .db import Database
from .row_codec import from_json, to_json
from .schemas import utc_now
from .text_index import fts_query
from .transactive_schemas import Holder, HolderKind


@dataclass(frozen=True)
class WhoKnowsCount:
    """One holder's evidence for one query, straight from the index."""

    holder_id: str
    matched: int
    top_score: float
    latest_time: str | None


_TOKEN_BYTES = 32


class HolderStore:
    """CRUD for registered holders plus the raw counts who_knows is built from."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert(self, holder: Holder) -> Holder:
        """Insert or replace a registry entry, keeping the original creation time."""
        now = utc_now().isoformat()
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT created_at FROM holders WHERE holder_id = ?", (holder.holder_id,)
            ).fetchone()
            created_at = str(existing["created_at"]) if existing is not None else now
            stored = holder.model_copy(update={"created_at": _moment(created_at), "updated_at": _moment(now)})
            connection.execute(
                """
                INSERT INTO holders (holder_id, name, kind, knows_about_json, contact_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(holder_id) DO UPDATE SET
                    name = excluded.name,
                    kind = excluded.kind,
                    knows_about_json = excluded.knows_about_json,
                    contact_json = excluded.contact_json,
                    updated_at = excluded.updated_at
                """,
                (
                    stored.holder_id,
                    stored.name,
                    stored.kind,
                    to_json(stored.knows_about),
                    to_json(stored.contact),
                    stored.created_at.isoformat(),
                    stored.updated_at.isoformat(),
                ),
            )
        return stored

    def register_minimal(self, holder_id: str) -> None:
        """Make a holder exist without overwriting what somebody already declared about them.

        A memory nobody registered still needs a directory entry, or a referral to its holder has
        no target to point at.
        """
        now = utc_now().isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO holders (holder_id, name, kind, knows_about_json, contact_json, created_at, updated_at)
                VALUES (?, '', 'person', '[]', '{}', ?, ?)
                ON CONFLICT(holder_id) DO NOTHING
                """,
                (holder_id, now, now),
            )

    def issue_token(self, holder_id: str) -> tuple[Holder, str]:
        """Give a holder a fresh bearer token. The plain value is returned once; the row keeps its hash."""
        self.register_minimal(holder_id)
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        now = utc_now().isoformat()
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE holders SET token_hash = ?, token_issued_at = ?, updated_at = ? WHERE holder_id = ?",
                (_token_hash(token), now, now, holder_id),
            )
        entry = self.get(holder_id)
        if entry is None:
            raise ValueError(f"holder {holder_id!r} vanished while its token was being issued")
        return entry, token

    def revoke_token(self, holder_id: str) -> Holder:
        """Drop a holder's token: nobody can read as them until a new one is issued."""
        now = utc_now().isoformat()
        with self.database.connect() as connection:
            changed = connection.execute(
                "UPDATE holders SET token_hash = NULL, token_issued_at = NULL, updated_at = ? WHERE holder_id = ?",
                (now, holder_id),
            )
        if changed.rowcount == 0:
            raise ValueError(f"no holder {holder_id!r} is registered")
        entry = self.get(holder_id)
        if entry is None:
            raise ValueError(f"holder {holder_id!r} vanished while its token was being revoked")
        return entry

    def verify_token(self, token: str) -> str | None:
        """Which holder a bearer token speaks for, or None when it speaks for nobody.

        The store keeps only the sha256 digest, so this is SQL equality on the digest: no plaintext
        exists here to compare in constant time, and a copied database cannot replay a token.
        """
        if not token:
            return None
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT holder_id FROM holders WHERE token_hash = ?", (_token_hash(token),)
            ).fetchone()
        return None if row is None else str(row["holder_id"])

    def get(self, holder_id: str) -> Holder | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM holders WHERE holder_id = ?", (holder_id,)).fetchone()
        return None if row is None else _row_to_holder(row)

    def list_holders(self) -> list[Holder]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM holders ORDER BY holder_id").fetchall()
        return [_row_to_holder(row) for row in rows]

    def delete(self, holder_id: str) -> None:
        """Remove a registry entry. Refuses while that holder still owns memories: forgetting a
        phone number must not silently orphan the memories it points to."""
        holding = self.atom_count(holder_id)
        if holding:
            raise ValueError(
                f"holder {holder_id!r} still holds {holding} memories; forget them before deleting the holder"
            )
        with self.database.connect() as connection:
            connection.execute("DELETE FROM holders WHERE holder_id = ?", (holder_id,))

    def atom_count(self, holder_id: str) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM v_atoms_current WHERE holder_id = ?", (holder_id,)
            ).fetchone()
        return int(row["n"])

    def known_holders(self) -> list[str]:
        """Every holder with at least one open memory, registered or not.

        A person who has memories is a holder whether or not anybody registered them; the
        registry adds declared topics and contact details, it does not grant existence.
        """
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT holder_id FROM v_atoms_current WHERE holder_id <> '' ORDER BY holder_id"
            ).fetchall()
        return [str(row["holder_id"]) for row in rows]

    def who_knows_counts(self, query: str, limit: int) -> list[WhoKnowsCount]:
        """Rank holders by how well their own memories answer the query.

        The directory is deliberately unfiltered by visibility: the whole point of transactive
        memory is knowing that someone knows, even when their memory is private to them.

        `rank` is FTS5's own bm25 column, and it is the only way to aggregate the score: SQLite
        refuses bm25() inside MAX(), and refuses it in a subquery or window over a match.
        """
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT a.holder_id,
                       COUNT(*) AS matched,
                       -MAX(rank) AS top_score,
                       MAX(COALESCE(a.event_time, a.ingested_at)) AS latest_time
                FROM atom_fts AS f
                JOIN v_atoms_current AS a ON a.atom_id = f.atom_id
                WHERE atom_fts MATCH ?
                  AND a.holder_id <> ''
                GROUP BY a.holder_id
                ORDER BY top_score DESC, matched DESC
                LIMIT ?
                """,
                (fts_query(query), limit),
            ).fetchall()
        return [
            WhoKnowsCount(
                holder_id=str(row["holder_id"]),
                matched=int(row["matched"]),
                top_score=float(row["top_score"]),
                latest_time=None if row["latest_time"] is None else str(row["latest_time"]),
            )
            for row in rows
        ]


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _moment(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"holder timestamps need an explicit offset, stored {value!r}")
    return parsed


_HOLDER_KINDS: tuple[HolderKind, ...] = ("person", "agent", "service")


def _kind(value: str) -> HolderKind:
    if value not in _HOLDER_KINDS:
        raise ValueError(f"stored holder kind {value!r} is not one of person, agent, service")
    return cast(HolderKind, value)


def _row_to_holder(row: sqlite3.Row) -> Holder:
    return Holder(
        holder_id=str(row["holder_id"]),
        name=str(row["name"]),
        kind=_kind(str(row["kind"])),
        knows_about=from_json(row["knows_about_json"], []),
        contact=from_json(row["contact_json"], {}),
        token_issued_at=None if row["token_issued_at"] is None else _moment(str(row["token_issued_at"])),
        created_at=_moment(str(row["created_at"])),
        updated_at=_moment(str(row["updated_at"])),
    )
