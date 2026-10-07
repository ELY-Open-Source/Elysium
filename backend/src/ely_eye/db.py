from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings, get_settings
from .migrations import apply as apply_migrations
from .row_codec import atom_params, from_json, row_to_atom, row_to_source, to_json
from .schemas import EvidenceAtom, SourceRecord, utc_now
from .text_index import fts_expression, fts_terms, index_text, rare_terms


@dataclass(frozen=True)
class FtsPage:
    """One page of BM25 hits plus whether the corpus holds more: the cursor is an offset, and a
    ranking this small re-reads rather than keeps a server-side position."""

    rows: list[tuple[str, float]]
    has_more: bool


class Database:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        self.path = self.settings.db_path
        self.init()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init(self) -> None:
        with sqlite3.connect(self.path) as connection:
            apply_migrations(connection)

    def upsert_sources(self, sources: list[SourceRecord]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO sources (
                    source_id, path, kind, mime, sha256, size_bytes, created_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    path=excluded.path,
                    kind=excluded.kind,
                    mime=excluded.mime,
                    sha256=excluded.sha256,
                    size_bytes=excluded.size_bytes,
                    metadata_json=excluded.metadata_json
                """,
                [
                    (
                        source.source_id,
                        source.path,
                        source.kind,
                        source.mime,
                        source.sha256,
                        source.size_bytes,
                        source.created_at.isoformat(),
                        to_json(source.metadata),
                    )
                    for source in sources
                ],
            )

    def upsert_atoms(self, atoms: list[EvidenceAtom]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO atoms (
                    atom_id, source_id, modality, source, ingested_at, text, image_ref,
                    embedding_refs_json, layout_json, relations_json, trust_json,
                    token_equivalent, metadata_json, holder_id, origin, scenario,
                    event_time, event_time_end, event_time_precision, event_time_source,
                    valid_from, valid_to, supersedes_json, visibility_json, retention_until
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(atom_id) DO UPDATE SET
                    modality=excluded.modality,
                    source=excluded.source,
                    ingested_at=excluded.ingested_at,
                    text=excluded.text,
                    image_ref=excluded.image_ref,
                    embedding_refs_json=excluded.embedding_refs_json,
                    layout_json=excluded.layout_json,
                    relations_json=excluded.relations_json,
                    trust_json=excluded.trust_json,
                    token_equivalent=excluded.token_equivalent,
                    metadata_json=excluded.metadata_json,
                    holder_id=excluded.holder_id,
                    origin=excluded.origin,
                    scenario=excluded.scenario,
                    event_time=excluded.event_time,
                    event_time_end=excluded.event_time_end,
                    event_time_precision=excluded.event_time_precision,
                    event_time_source=excluded.event_time_source,
                    valid_from=excluded.valid_from,
                    valid_to=excluded.valid_to,
                    supersedes_json=excluded.supersedes_json,
                    visibility_json=excluded.visibility_json,
                    retention_until=excluded.retention_until
                """,
                [atom_params(atom) for atom in atoms],
            )
            connection.executemany("DELETE FROM atom_fts WHERE atom_id = ?", [(atom.atom_id,) for atom in atoms])
            connection.executemany(
                "INSERT INTO atom_fts(atom_id, source, text) VALUES (?, ?, ?)",
                [(atom.atom_id, index_text(atom.source), index_text(atom.text)) for atom in atoms],
            )
            # New text changes which words are common, so every remembered count is void.
            connection.execute("DELETE FROM term_df")

    def list_atoms(self, limit: int | None = None) -> list[EvidenceAtom]:
        with self.connect() as connection:
            if limit is None:
                rows = connection.execute("SELECT * FROM atoms ORDER BY ingested_at DESC").fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM atoms ORDER BY ingested_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [row_to_atom(row) for row in rows]

    def atoms_as_of(self, moment: datetime, holder: str | None = None) -> list[EvidenceAtom]:
        """Memories that were open at `moment`, the question a parameterless view cannot ask.

        Same predicate as v_atoms_current minus the retention filter: retention says how long
        the system keeps a memory, not whether it was true then. Unknown bounds read as open.
        """
        stamp = moment.isoformat()
        with self.connect() as connection:
            if holder is None:
                rows = connection.execute(
                    "SELECT * FROM atoms "
                    "WHERE (valid_from IS NULL OR valid_from <= ?) "
                    "AND (valid_to IS NULL OR valid_to > ?) "
                    "ORDER BY ingested_at DESC",
                    (stamp, stamp),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM atoms "
                    "WHERE holder_id = ? "
                    "AND (valid_from IS NULL OR valid_from <= ?) "
                    "AND (valid_to IS NULL OR valid_to > ?) "
                    "ORDER BY ingested_at DESC",
                    (holder, stamp, stamp),
                ).fetchall()
        return [row_to_atom(row) for row in rows]

    def get_atoms(self, atom_ids: list[str]) -> list[EvidenceAtom]:
        if not atom_ids:
            return []
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM atoms WHERE atom_id IN (SELECT value FROM json_each(?))", (to_json(atom_ids),)
            ).fetchall()
        by_id = {row["atom_id"]: row_to_atom(row) for row in rows}
        return [by_id[atom_id] for atom_id in atom_ids if atom_id in by_id]

    def search_fts(self, query: str, limit: int) -> list[tuple[str, float]]:
        """Best BM25 matches over the whole corpus, no filters: the ranking the product needs most days."""
        return self.search_atoms(query, limit=limit).rows

    def search_atoms(
        self,
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
        """BM25 over the FTS index joined to memories that are open right now.

        Every filter is a `? IS NULL OR` predicate in one literal statement: the ranking never
        depends on string-built SQL, and the planner sees one shape. A memory with no event time
        cannot answer a time filter, so it drops out when one is asked for.

        `as_holder` applies the sharing rule: a memory is readable by its owner, by anyone named
        in its visible_to list, by everyone when it is public, and by anyone when nobody owns it.
        A memory with no holder cannot be private to a holder that does not exist. Without an
        asker the query runs over the whole library, which is what an operator debugging wants.
        """
        with self.connect() as connection:
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


    def source_id_of_atom(self, atom_id: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute("SELECT source_id FROM atoms WHERE atom_id = ?", (atom_id,)).fetchone()
        return None if row is None else str(row["source_id"])

    def atoms_of_source(self, source_id: str) -> list[EvidenceAtom]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM atoms WHERE source_id = ? ORDER BY atom_id", (source_id,)
            ).fetchall()
        return [row_to_atom(row) for row in rows]

    def close_atoms(self, atom_ids: list[str], closed_at: datetime) -> int:
        """Stop treating these memories as current; the rows stay for time travel."""
        if not atom_ids:
            return 0
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE atoms SET valid_to = ? "
                "WHERE valid_to IS NULL AND atom_id IN (SELECT value FROM json_each(?))",
                (closed_at.isoformat(), to_json(atom_ids)),
            )
        return int(cursor.rowcount)

    def delete_atoms(self, atom_ids: list[str]) -> int:
        if not atom_ids:
            return 0
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM atom_fts WHERE atom_id IN (SELECT value FROM json_each(?))", (to_json(atom_ids),)
            )
            cursor = connection.execute(
                "DELETE FROM atoms WHERE atom_id IN (SELECT value FROM json_each(?))", (to_json(atom_ids),)
            )
            connection.execute("DELETE FROM term_df")
        return int(cursor.rowcount)

    def delete_edges_touching(self, atom_ids: list[str]) -> int:
        if not atom_ids:
            return 0
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM evidence_edges "
                "WHERE from_atom_id IN (SELECT value FROM json_each(?)) "
                "OR to_atom_id IN (SELECT value FROM json_each(?))",
                (to_json(atom_ids), to_json(atom_ids)),
            )
        return int(cursor.rowcount)

    def clear_cache_events(self, reason: str) -> int:
        """Empty the cache and leave one trace row proving why it is empty."""
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM cache_events")
            cleared = int(cursor.rowcount)
            connection.execute(
                "INSERT INTO cache_events(ts, layer, cache_key, event, bytes_estimate, metadata_json) "
                "VALUES (?, 'memory', ?, 'invalidated', 0, ?)",
                (utc_now().isoformat(), reason, to_json({"entries_cleared": cleared})),
            )
        return cleared

    def atom_count(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM atoms").fetchone()[0])

    def token_equivalent_sum(self) -> int:
        with self.connect() as connection:
            value = connection.execute("SELECT COALESCE(SUM(token_equivalent), 0) FROM atoms").fetchone()[0]
        return int(value)

    def cartridge_token_equivalent_sum(self) -> int:
        with self.connect() as connection:
            value = connection.execute(
                "SELECT COALESCE(SUM(token_equivalent), 0) FROM cartridges"
            ).fetchone()[0]
        return int(value)

    def source_count(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0])

    def list_sources(self) -> list[SourceRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT source_id, path, kind, mime, sha256, size_bytes, created_at, metadata_json "
                "FROM sources ORDER BY created_at DESC"
            ).fetchall()
        return [row_to_source(row) for row in rows]

    def get_sources(self, source_ids: list[str]) -> list[SourceRecord]:
        if not source_ids:
            return []
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT source_id, path, kind, mime, sha256, size_bytes, created_at, metadata_json "
                "FROM sources WHERE source_id IN (SELECT value FROM json_each(?))",
                (to_json(source_ids),),
            ).fetchall()
        return [row_to_source(row) for row in rows]

    def cartridge_count(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM cartridges").fetchone()[0])

    def write_cartridge(
        self,
        cartridge_id: str,
        name: str,
        root_path: Path,
        manifest_json: str,
        dna: str | None,
        token_equivalent: int,
        created_at: datetime,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO cartridges (
                    cartridge_id, name, root_path, manifest_json, dna, token_equivalent, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cartridge_id) DO UPDATE SET
                    name=excluded.name,
                    root_path=excluded.root_path,
                    manifest_json=excluded.manifest_json,
                    dna=excluded.dna,
                    token_equivalent=excluded.token_equivalent
                """,
                (
                    cartridge_id,
                    name,
                    str(root_path),
                    manifest_json,
                    dna,
                    token_equivalent,
                    created_at.isoformat(),
                ),
            )

    def list_cartridges(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT cartridge_id, name, root_path, manifest_json, dna, token_equivalent, created_at "
                "FROM cartridges ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def log_cache_event(
        self,
        layer: str,
        cache_key: str,
        event: str,
        bytes_estimate: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO cache_events(ts, layer, cache_key, event, bytes_estimate, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now().isoformat(),
                    layer,
                    cache_key,
                    event,
                    bytes_estimate,
                    to_json(metadata or {}),
                ),
            )

    def write_evidence_edges(self, edges: list[dict[str, Any]]) -> None:
        if not edges:
            return
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO evidence_edges(from_atom_id, to_atom_id, relation, confidence, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(edge["from_atom_id"]),
                        str(edge["to_atom_id"]),
                        str(edge["relation"]),
                        float(edge["confidence"]),
                        to_json(edge.get("metadata") or {}),
                    )
                    for edge in edges
                ],
            )

    def list_evidence_edges(self, limit: int | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            if limit is None:
                rows = connection.execute(
                    "SELECT from_atom_id, to_atom_id, relation, confidence, metadata_json "
                    "FROM evidence_edges ORDER BY id DESC"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT from_atom_id, to_atom_id, relation, confidence, metadata_json "
                    "FROM evidence_edges ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            {
                "from_atom_id": row["from_atom_id"],
                "to_atom_id": row["to_atom_id"],
                "relation": row["relation"],
                "confidence": float(row["confidence"]),
                "metadata": from_json(row["metadata_json"], {}),
            }
            for row in rows
        ]

    def cache_layer_rows(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT
                  layer,
                  COUNT(DISTINCT cache_key) AS entries,
                  COALESCE(SUM(bytes_estimate), 0) AS bytes_estimate,
                  SUM(CASE WHEN event = 'hit' THEN 1 ELSE 0 END) AS hit_count,
                  SUM(CASE WHEN event = 'miss' THEN 1 ELSE 0 END) AS miss_count,
                  MAX(ts) AS last_event_at
                FROM cache_events
                GROUP BY layer
                """
            ).fetchall()
