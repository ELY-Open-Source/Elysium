"""BM25 search over the store, kept out of the query layer by the line budget."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .db import Database
from .row_codec import to_json
from .text_index import fts_expression, fts_terms, rare_terms


@dataclass(frozen=True)
class FtsPage:
    """One page of BM25 hits plus whether the corpus holds more: the cursor is an offset, and a
    ranking this small re-reads rather than keeps a server-side position."""

    rows: list[tuple[str, float]]
    has_more: bool


def search_fts(database: Database, query: str, limit: int) -> list[tuple[str, float]]:
    """Best BM25 matches over the whole corpus, no filters: the ranking the product needs most days."""
    return search_atoms(database, query, limit=limit).rows


def search_atoms(
    database: Database,
    query: str,
    *,
    limit: int,
    offset: int = 0,
    holder: str | None = None,
    scenario: str | None = None,
    source_id: str | None = None,
    modality: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    min_trust: float | None = None,
    cartridge_ids: list[str] | None = None,
    as_holder: str | None = None,
) -> FtsPage:
    """BM25 over the FTS index joined to memories that are open right now and readable by the asker.

    Every filter is a `? IS NULL OR` predicate in one literal statement: the ranking never
    depends on string-built SQL, and the planner sees one shape. A memory with no event time
    cannot answer a time filter, so it drops out when one is asked for.

    `as_holder` applies the sharing rule: a memory is readable by its owner, by anyone named
    in its visible_to list, by everyone when it is public, and by anyone when nobody owns it.
    A memory with no holder cannot be private to a holder that does not exist. Without an
    asker the query runs over the whole library, which is what an operator debugging wants."""
    with database.connect() as connection:
        expression = fts_expression(rare_terms(connection, fts_terms(query)))
        rows = connection.execute(
            """
            SELECT f.atom_id, bm25(atom_fts) AS score
            FROM atom_fts AS f
            JOIN v_atoms_current AS a ON a.atom_id = f.atom_id
            WHERE atom_fts MATCH ?
              AND (? IS NULL OR a.holder_id = ?)
              AND (? IS NULL OR a.scenario = ?)
              AND (? IS NULL OR a.source_id = ?)
              AND (? IS NULL OR a.modality = ?)
              AND (? IS NULL OR (a.event_time IS NOT NULL AND a.event_time >= ?))
              AND (? IS NULL OR (a.event_time IS NOT NULL AND a.event_time <= ?))
              AND (? IS NULL OR (
                    a.trust_json IS NOT NULL
                    AND min(
                        json_extract(a.trust_json, '$.parser'),
                        json_extract(a.trust_json, '$.ocr'),
                        json_extract(a.trust_json, '$.model')
                    ) >= ?
              ))
              AND (? IS NULL OR EXISTS (
                    SELECT 1 FROM cartridge_atoms AS ca
                    WHERE ca.atom_id = f.atom_id
                      AND ca.cartridge_id IN (SELECT value FROM json_each(?))
              ))
              AND (? IS NULL OR a.holder_id = ''
                    OR json_extract(a.visibility_json, '$.scope') = 'everyone'
                    OR a.holder_id = ?
                    OR EXISTS (
                          SELECT 1 FROM json_each(json_extract(a.visibility_json, '$.holders'))
                          WHERE value = ?
                    ))
            ORDER BY score
            LIMIT ? OFFSET ?
            """,
            (
                expression,
                holder,
                holder,
                scenario,
                scenario,
                source_id,
                source_id,
                modality,
                modality,
                None if since is None else since.isoformat(),
                None if since is None else since.isoformat(),
                None if until is None else until.isoformat(),
                None if until is None else until.isoformat(),
                min_trust,
                min_trust,
                None if cartridge_ids is None else to_json(cartridge_ids),
                None if cartridge_ids is None else to_json(cartridge_ids),
                as_holder,
                as_holder,
                as_holder,
                limit + 1,
                offset,
            ),
        ).fetchall()
    matched = [(str(row["atom_id"]), -float(row["score"])) for row in rows[:limit]]
    return FtsPage(rows=matched, has_more=len(rows) > limit)
