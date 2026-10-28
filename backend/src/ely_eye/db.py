from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings, get_settings
from .migrations import apply as apply_migrations
from .row_codec import atom_params, from_json, row_to_atom, row_to_source, to_json
from .schemas import EvidenceAtom, SourceRecord, utc_now
from .text_index import index_text


class Database:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        self.path = self.settings.db_path
        self.init()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        from .vector_index import load_extension

        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        load_extension(connection)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init(self) -> None:
        # connect(), not a bare sqlite3.connect: the migrations read rows by name.
        with self.connect() as connection:
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
                    valid_from, valid_to, supersedes_json, visibility_json, retention_until,
                    quarantined, session_id, importance, recall_count, last_recalled_at, archived_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    retention_until=excluded.retention_until,
                    quarantined=excluded.quarantined,
                    session_id=excluded.session_id,
                    importance=excluded.importance
                    -- recall_count, last_recalled_at and archived_at stay as the store has them: a
                    -- re-ingested copy of the same atom cannot erase how often it was used.
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
            self._bump_revision(connection)

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

    def stored_provenance(self, source_ids: list[str]) -> dict[str, EvidenceAtom]:
        """One stored atom per source, so a re-ingest keeps who that source belongs to and when it was true.

        A source whose atoms disagree on those facts is refused: copying either side onto the new
        atoms would hand one holder's memory to the other's readers.
        """
        if not source_ids:
            return {}
        with self.connect() as connection:
            split = connection.execute(
                "SELECT source_id FROM atoms WHERE source_id IN (SELECT value FROM json_each(?)) "
                "GROUP BY source_id HAVING count(DISTINCT holder_id || char(31) || scenario || char(31) || "
                "visibility_json || char(31) || coalesce(retention_until, '') || char(31) || "
                "coalesce(event_time, '') || char(31) || coalesce(event_time_end, '') || char(31) || "
                "event_time_precision || char(31) || event_time_source) > 1",
                (to_json(source_ids),),
            ).fetchall()
            if split:
                raise ValueError(
                    f"source {split[0]['source_id']}: its stored atoms disagree about who holds them or "
                    "when they were true, so a re-ingest cannot tell which to keep"
                )
            rows = connection.execute(
                "SELECT * FROM atoms WHERE source_id IN (SELECT value FROM json_each(?)) GROUP BY source_id",
                (to_json(source_ids),),
            ).fetchall()
        return {str(row["source_id"]): row_to_atom(row) for row in rows}

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
            self._bump_revision(connection)
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
            self._bump_revision(connection)
        return int(cursor.rowcount)

    def delete_source(self, source_id: str) -> int:
        """Erase where a memory came from, so a forget leaves no provenance row behind."""
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM sources WHERE source_id = ?", (source_id,))
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

    def revision(self) -> int:
        """What a compiled context was compiled against; see store_meta."""
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM store_meta WHERE key = 'revision'").fetchone()
        return int(row["value"]) if row is not None else 0

    def _bump_revision(self, connection: sqlite3.Connection) -> None:
        """A write changes what a compiled context may contain, so the semantic cache must notice."""
        connection.execute("INSERT OR IGNORE INTO store_meta(key, value) VALUES ('revision', '0')")
        connection.execute("UPDATE store_meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'revision'")

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
