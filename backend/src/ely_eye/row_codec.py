"""Row ↔ model conversion for the SQLite store, kept out of the query layer.

Every column of an atom is either a scalar, an ISO timestamp, or a JSON blob; one file holds
that mapping so the store can stay about queries and the codec can stay about shapes.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from .schemas import (
    EvidenceAtom,
    LayoutBox,
    MemoryOrigin,
    Modality,
    SourceRecord,
    TimePrecision,
    TrustScores,
    Visibility,
)


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def from_json(value: str | None, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(f"stored JSON is unreadable: {error}") from error


def from_iso(value: str | None) -> datetime | None:
    if value is None or value == "":
        return None
    return datetime.fromisoformat(value)


def atom_params(atom: EvidenceAtom) -> tuple[Any, ...]:
    return (
        atom.atom_id,
        atom.source_id,
        atom.modality.value,
        atom.source,
        atom.ingested_at.isoformat(),
        atom.text,
        atom.image_ref,
        to_json(atom.embedding_refs),
        to_json(atom.layout.model_dump() if atom.layout else None),
        to_json(atom.relations),
        to_json(atom.trust.model_dump()),
        atom.token_equivalent,
        to_json(atom.metadata),
        atom.holder_id,
        atom.origin.value,
        atom.scenario,
        atom.event_time.isoformat() if atom.event_time else None,
        atom.event_time_end.isoformat() if atom.event_time_end else None,
        atom.event_time_precision.value,
        atom.event_time_source,
        atom.valid_from.isoformat() if atom.valid_from else None,
        atom.valid_to.isoformat() if atom.valid_to else None,
        to_json(atom.supersedes),
        to_json(atom.visibility.model_dump()),
        atom.retention_until.isoformat() if atom.retention_until else None,
        1 if atom.quarantined else 0,
    )


def row_to_atom(row: sqlite3.Row) -> EvidenceAtom:
    layout_data = from_json(row["layout_json"], None)
    return EvidenceAtom(
        atom_id=row["atom_id"],
        modality=Modality(row["modality"]),
        source_id=row["source_id"],
        source=row["source"],
        ingested_at=datetime.fromisoformat(row["ingested_at"]),
        text=row["text"],
        image_ref=row["image_ref"],
        embedding_refs=from_json(row["embedding_refs_json"], []),
        layout=LayoutBox(**layout_data) if layout_data else None,
        relations=from_json(row["relations_json"], []),
        trust=TrustScores(**from_json(row["trust_json"], {"parser": 0.0})),
        token_equivalent=int(row["token_equivalent"]),
        metadata=from_json(row["metadata_json"], {}),
        holder_id=row["holder_id"],
        origin=MemoryOrigin(row["origin"]),
        scenario=row["scenario"],
        event_time=from_iso(row["event_time"]),
        event_time_end=from_iso(row["event_time_end"]),
        event_time_precision=TimePrecision(row["event_time_precision"]),
        event_time_source=row["event_time_source"],
        valid_from=from_iso(row["valid_from"]),
        valid_to=from_iso(row["valid_to"]),
        supersedes=from_json(row["supersedes_json"], []),
        visibility=Visibility(**from_json(row["visibility_json"], {})),
        retention_until=from_iso(row["retention_until"]),
        quarantined=bool(row["quarantined"]),
    )


def row_to_source(row: sqlite3.Row) -> SourceRecord:
    return SourceRecord(
        source_id=row["source_id"],
        path=row["path"],
        kind=row["kind"],
        mime=row["mime"],
        sha256=row["sha256"],
        size_bytes=int(row["size_bytes"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        metadata=from_json(row["metadata_json"], {}),
    )
