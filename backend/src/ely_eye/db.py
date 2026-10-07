from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings, get_settings
from .migrations import apply as apply_migrations
from .schemas import EvidenceAtom, MemoryOrigin, SourceRecord, TimePrecision, utc_now


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _loads(value: str | None, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(f"stored JSON is unreadable: {error}") from error


def _datetime(value: str | None) -> datetime | None:
    if value is None or value == "":
        return None
    return datetime.fromisoformat(value)


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
                        _json(source.metadata),
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
                [self._atom_params(atom) for atom in atoms],
            )
            connection.executemany("DELETE FROM atom_fts WHERE atom_id = ?", [(atom.atom_id,) for atom in atoms])
            connection.executemany(
                "INSERT INTO atom_fts(atom_id, source, text) VALUES (?, ?, ?)",
                [(atom.atom_id, atom.source, atom.text) for atom in atoms],
            )

    def _atom_params(self, atom: EvidenceAtom) -> tuple[Any, ...]:
        return (
            atom.atom_id,
            atom.source_id,
            atom.modality.value,
            atom.source,
            atom.ingested_at.isoformat(),
            atom.text,
            atom.image_ref,
            _json(atom.embedding_refs),
            _json(atom.layout.model_dump() if atom.layout else None),
            _json(atom.relations),
            _json(atom.trust.model_dump()),
            atom.token_equivalent,
            _json(atom.metadata),
            atom.holder_id,
            atom.origin.value,
            atom.scenario,
            atom.event_time.isoformat() if atom.event_time else None,
            atom.event_time_end.isoformat() if atom.event_time_end else None,
            atom.event_time_precision.value,
            atom.event_time_source,
            atom.valid_from.isoformat() if atom.valid_from else None,
            atom.valid_to.isoformat() if atom.valid_to else None,
            _json(atom.supersedes),
            _json(atom.visibility.model_dump()),
            atom.retention_until.isoformat() if atom.retention_until else None,
        )

    def list_atoms(self, limit: int | None = None) -> list[EvidenceAtom]:
        with self.connect() as connection:
            if limit is None:
                rows = connection.execute("SELECT * FROM atoms ORDER BY ingested_at DESC").fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM atoms ORDER BY ingested_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._row_to_atom(row) for row in rows]

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
        return [self._row_to_atom(row) for row in rows]

    def get_atoms(self, atom_ids: list[str]) -> list[EvidenceAtom]:
        if not atom_ids:
            return []
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM atoms WHERE atom_id IN (SELECT value FROM json_each(?))", (_json(atom_ids),)
            ).fetchall()
        by_id = {row["atom_id"]: self._row_to_atom(row) for row in rows}
        return [by_id[atom_id] for atom_id in atom_ids if atom_id in by_id]

    def search_fts(self, query: str, limit: int) -> list[tuple[str, float]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT atom_id, bm25(atom_fts) AS score
                FROM atom_fts
                WHERE atom_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        return [(row["atom_id"], float(-row["score"])) for row in rows]

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
        return [self._row_to_source(row) for row in rows]

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
                    _json(metadata or {}),
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
                        _json(edge.get("metadata") or {}),
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
                "metadata": _loads(row["metadata_json"], {}),
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

    def _row_to_atom(self, row: sqlite3.Row) -> EvidenceAtom:
        from .schemas import LayoutBox, Modality, TrustScores, Visibility

        layout_data = _loads(row["layout_json"], None)
        return EvidenceAtom(
            atom_id=row["atom_id"],
            modality=Modality(row["modality"]),
            source_id=row["source_id"],
            source=row["source"],
            ingested_at=datetime.fromisoformat(row["ingested_at"]),
            text=row["text"],
            image_ref=row["image_ref"],
            embedding_refs=_loads(row["embedding_refs_json"], []),
            layout=LayoutBox(**layout_data) if layout_data else None,
            relations=_loads(row["relations_json"], []),
            trust=TrustScores(**_loads(row["trust_json"], {"parser": 0.0})),
            token_equivalent=int(row["token_equivalent"]),
            metadata=_loads(row["metadata_json"], {}),
            holder_id=row["holder_id"],
            origin=MemoryOrigin(row["origin"]),
            scenario=row["scenario"],
            event_time=_datetime(row["event_time"]),
            event_time_end=_datetime(row["event_time_end"]),
            event_time_precision=TimePrecision(row["event_time_precision"]),
            event_time_source=row["event_time_source"],
            valid_from=_datetime(row["valid_from"]),
            valid_to=_datetime(row["valid_to"]),
            supersedes=_loads(row["supersedes_json"], []),
            visibility=Visibility(**_loads(row["visibility_json"], {})),
            retention_until=_datetime(row["retention_until"]),
        )

    def _row_to_source(self, row: sqlite3.Row) -> SourceRecord:
        return SourceRecord(
            source_id=row["source_id"],
            path=row["path"],
            kind=row["kind"],
            mime=row["mime"],
            sha256=row["sha256"],
            size_bytes=int(row["size_bytes"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            metadata=_loads(row["metadata_json"], {}),
        )
