"""The single writer for memory: remember, supersede, forget.

Ingestion turns artefacts into atoms. This module turns statements into memories, and it
is the only place a memory is created or destroyed, so provenance is stamped here and no
caller can claim to be somebody else.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings, get_settings
from .db import Database
from .schemas import (
    EvidenceAtom,
    ForgetReport,
    MemoryOrigin,
    Modality,
    SourceRecord,
    TimePrecision,
    TrustScores,
    Visibility,
    utc_now,
)
from .storage import token_equivalent
from .visual_index import VisualIndex

# Trust scores describe extraction fidelity, not truthfulness: a remembered sentence is
# stored verbatim, so the parser is fully trusted and origin carries the epistemic weight.
MEMORY_TRUST = TrustScores(parser=1.0, ocr=0.0, model=0.0)


class MemoryService:
    def __init__(self, settings: Settings | None = None, database: Database | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = database or Database(self.settings)

    def remember(
        self,
        text: str,
        *,
        holder_id: str,
        origin: MemoryOrigin,
        scenario: str = "",
        event_time: datetime | None = None,
        event_time_precision: TimePrecision = TimePrecision.unknown,
        event_time_source: str = "",
        visibility: Visibility | None = None,
        supersedes: list[str] | None = None,
        valid_from: datetime | None = None,
        retention_until: datetime | None = None,
    ) -> EvidenceAtom:
        """Store one statement as a memory owned by a holder.

        Repeating the same sentence as the same holder updates the memory instead of
        duplicating it; two holders holding the same sentence keep two memories.
        """
        statement = text.strip()
        if not statement:
            raise ValueError("remember needs text; an empty memory will be found by nobody")
        if not holder_id.strip():
            raise ValueError("remember needs a holder; a memory nobody owns cannot be referred to")
        if event_time is not None and event_time_precision is TimePrecision.unknown:
            raise ValueError(
                f"event_time {event_time.isoformat()} needs its precision; "
                "a day stored as an instant will be read as a moment"
            )

        moment = utc_now()
        digest = hashlib.sha256(f"{holder_id}\n{statement}".encode()).hexdigest()
        source_id = f"mem-{digest[:16]}"
        self.db.upsert_sources(
            [
                SourceRecord(
                    source_id=source_id,
                    path=f"memory://{holder_id}/{scenario or 'general'}",
                    kind="memory",
                    mime="text/plain",
                    sha256=hashlib.sha256(statement.encode("utf-8")).hexdigest(),
                    size_bytes=len(statement.encode("utf-8")),
                    created_at=moment,
                    metadata={"holder_id": holder_id, "origin": origin.value},
                )
            ]
        )
        atom = EvidenceAtom(
            atom_id=f"{source_id}:text",
            modality=Modality.text,
            source_id=source_id,
            source=f"memory://{holder_id}/{scenario or 'general'}",
            ingested_at=moment,
            text=statement,
            trust=MEMORY_TRUST,
            token_equivalent=token_equivalent(statement),
            holder_id=holder_id,
            origin=origin,
            scenario=scenario,
            event_time=event_time,
            event_time_precision=event_time_precision,
            event_time_source=event_time_source,
            supersedes=list(supersedes or []),
            valid_from=valid_from,
            visibility=visibility or Visibility(),
            retention_until=retention_until,
        )
        self.db.upsert_atoms([atom])
        return atom

    def supersede(
        self,
        atom_id: str,
        *,
        text: str,
        holder_id: str,
        origin: MemoryOrigin = MemoryOrigin.self_,
        scenario: str = "",
        event_time: datetime | None = None,
        event_time_precision: TimePrecision = TimePrecision.unknown,
        event_time_source: str = "",
    ) -> EvidenceAtom:
        """Close an old memory and record the new one as its replacement.

        Both rows stay: the new atom answers what is true now, the closed one answers what
        was true when asked, and a system that forgets the second cannot explain itself.
        """
        previous = self.db.get_atoms([atom_id])
        if not previous:
            raise ValueError(f"cannot supersede {atom_id}: no such atom")
        if previous[0].valid_to is not None:
            raise ValueError(
                f"{atom_id} was already closed at {previous[0].valid_to.isoformat()}; "
                "superseding a closed memory hides which replacement is current"
            )
        # A correction takes effect when it is asserted: the old memory stops being current
        # and the new one starts there, so the pair never claims to be true at the same time.
        moment = event_time or utc_now()
        replacement = self.remember(
            text,
            holder_id=holder_id,
            origin=origin,
            scenario=scenario or previous[0].scenario,
            event_time=event_time,
            event_time_precision=event_time_precision,
            event_time_source=event_time_source,
            supersedes=[atom_id],
            valid_from=moment,
        )
        self.db.close_atoms([atom_id], moment)
        return replacement

    def forget(
        self,
        *,
        atom_id: str | None = None,
        source_id: str | None = None,
        reason: str = "",
    ) -> ForgetReport:
        """Delete a memory and everything derived from it.

        The cascade is the whole point: an answer cached from a forgotten memory is still
        on screen, and a vector index that still carries it will keep surfacing it.
        """
        if (atom_id is None) == (source_id is None):
            raise ValueError("forget takes exactly one of atom_id or source_id")
        target_source = source_id or self.db.source_id_of_atom(str(atom_id))
        if target_source is None:
            raise ValueError(f"nothing to forget: no atom {atom_id}")
        doomed = self.db.atoms_of_source(target_source)
        if not doomed:
            raise ValueError(f"nothing to forget: source {target_source} holds no atom")

        doomed_ids = [atom.atom_id for atom in doomed]
        edges_deleted = self.db.delete_edges_touching(doomed_ids)
        atoms_deleted = self.db.delete_atoms(doomed_ids)
        cache_cleared = self.db.clear_cache_events(f"forget:{target_source}")
        vectors_dropped = self._drop_vector_index()
        return ForgetReport(
            source_id=target_source,
            atom_ids=doomed_ids,
            atoms_deleted=atoms_deleted,
            edges_deleted=edges_deleted,
            cache_entries_cleared=cache_cleared,
            vector_index_dropped=vectors_dropped,
            affected_cartridges=self._cartridges_holding(target_source),
            reason=reason,
        )

    def _drop_vector_index(self) -> bool:
        """The text and picture indexes are derived data; a stale one keeps answering with deleted memories."""
        dropped = False
        for path in (self.settings.cache_dir / "dense_index.npy", self.settings.cache_dir / "dense_index_atoms.json"):
            if path.exists():
                path.unlink()
                dropped = True
        return VisualIndex(self.settings, self.db).drop() or dropped

    def _cartridges_holding(self, source_id: str) -> list[dict[str, Any]]:
        """Name the cartridges that exported this source, so they can be rebuilt.

        An exported cartridge is an immutable artefact on disk; rewriting it here would
        silently change a DNA hash somebody already quoted.
        """
        affected: list[dict[str, Any]] = []
        for cartridge in self.db.list_cartridges():
            sources_path = Path(str(cartridge["root_path"])) / "sources.json"
            try:
                payload = json.loads(sources_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                affected.append({"cartridge_id": cartridge["cartridge_id"], "contains_source": "unknown"})
                continue
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError(f"{sources_path}: the cartridge source list is unreadable ({error})") from error
            held = any(str(row.get("source_id")) == source_id for row in payload)
            if held:
                affected.append({"cartridge_id": cartridge["cartridge_id"], "contains_source": True})
        return affected
