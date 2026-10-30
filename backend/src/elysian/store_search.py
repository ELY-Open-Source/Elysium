"""BM25 search over the store, kept out of the query layer by the line budget."""

from __future__ import annotations

import sqlite3
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
    as_of: datetime | None = None,
    min_trust: float | None = None,
    cartridge_ids: list[str] | None = None,
    as_holder: str | None = None,
    fill: int = 0,
) -> FtsPage:
    """BM25 over the FTS index joined to memories that answer for the moment being asked about.

    Every filter is a `? IS NULL OR` predicate in one literal statement: the ranking never
    depends on string-built SQL, and the planner sees one shape. A memory with no event time
    cannot answer a time filter, so it drops out when one is asked for.

    With no `as_of` the join repeats `v_atoms_current` in place of the view — same rule, asked
    through the atom_id index instead of a scan. With one, the question is what was true then,
    so a memory retired since still answers and `archived_at` (a storage tier, not a claim about
    the world) is ignored.

    `as_holder` applies the sharing rule in three states: a holder id sees its own memories, the
    ones naming it in visible_to, the ones marked for everyone, and the ones nobody owns; the
    empty string is a caller who is nobody, so only the last two; None runs over the whole
    library, which is what an operator or a process that owns the store reads with. A memory with
    no holder cannot be private to a holder that does not exist.

    The common words are dropped by a count over the whole library, but the search runs inside one
    holder's scope. A scope of four functions that shares only `axis` and `series` with a question
    keeps nothing when those words are common elsewhere, so when the rare words match fewer than
    `fill` atoms in scope, the search runs again with every word. Every page is read from the first
    row, so each page counts the same rows and a cursor never switches expressions halfway."""
    as_of_iso = None if as_of is None else as_of.isoformat()
    with database.connect() as connection:
        terms = fts_terms(query)
        rare = rare_terms(connection, terms)

        def match(chosen: list[str]) -> list[sqlite3.Row]:
            return connection.execute(
                """
                SELECT f.atom_id, bm25(atom_fts) AS score
                FROM atom_fts AS f
                JOIN atoms AS a ON a.atom_id = f.atom_id
                WHERE atom_fts MATCH ?
                  AND (
                        (? IS NULL
                            AND (a.valid_to IS NULL
                                 OR a.valid_to > strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'))
                            AND a.archived_at IS NULL
                            AND (a.valid_from IS NULL
                                 OR a.valid_from <= strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'))
                            AND (a.retention_until IS NULL
                                 OR a.retention_until >= strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')))
                        OR (? IS NOT NULL
                            AND (a.valid_from IS NULL OR a.valid_from <= ?)
                            AND (a.valid_to IS NULL OR a.valid_to > ?)
                            AND (a.event_time IS NULL OR a.event_time <= ?)
                            AND (a.retention_until IS NULL OR a.retention_until > ?))
                  )
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
                  AND (? IS NULL
                        OR a.holder_id = ''
                        OR json_extract(a.visibility_json, '$.scope') = 'everyone'
                        OR (? <> '' AND (a.holder_id = ?
                              OR EXISTS (
                                    SELECT 1 FROM json_each(json_extract(a.visibility_json, '$.holders'))
                                    WHERE value = ?
                              ))))
                ORDER BY score
                LIMIT ?
                """,
                (
                    fts_expression(chosen),
                    as_of_iso,
                    as_of_iso,
                    as_of_iso,
                    as_of_iso,
                    as_of_iso,
                    as_of_iso,
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
                    as_holder,
                    offset + limit + 1,
                ),
            ).fetchall()

        rows = match(rare)
        if len(rows) < fill and rare != terms:
            rows = match(terms)
    page = rows[offset:]
    matched = [(str(row["atom_id"]), -float(row["score"])) for row in page[:limit]]
    return FtsPage(rows=matched, has_more=len(page) > limit)
