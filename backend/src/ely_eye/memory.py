"""The single writer for memory: remember, supersede, forget.

Ingestion turns artefacts into atoms. This module turns statements into memories, and it
is the only place a memory is created or destroyed, so provenance is stamped here and no
caller can claim to be somebody else.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import lifecycle_store, trust
from .cache_fabric import CacheFabric
from .config import Settings, get_settings
from .db import Database
from .schemas import (
    ArchiveReport,
    ConflictRecord,
    ConsolidationRecord,
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
from .vector_index import VectorIndex
from .visual_index import VisualIndex

# A remembered sentence is stored verbatim, so trust scores carry no weight here; origin does.
MEMORY_TRUST = TrustScores(parser=1.0, ocr=0.0, model=0.0)

# The rollup atom's id suffix: one standing summary per holder and scenario, replaced in place.
ROLLUP_SUFFIX = ":rollup"


class MemoryService:
    def __init__(
        self,
        settings: Settings | None = None,
        database: Database | None = None,
        vectors: VectorIndex | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.db = database or Database(self.settings)
        self.vectors = vectors or VectorIndex(self.settings, self.db)
        self.pictures = VisualIndex(self.settings, self.db)
        self.cache = CacheFabric(self.settings, self.db)

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
        session_id: str = "",
        importance: float | None = None,
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
            session_id=session_id,
            importance=importance,
        )
        trust.stamp([atom], origin=origin)
        self.db.upsert_atoms([atom])
        self.vectors.sync_atoms([atom.atom_id])
        self._note_conflicts(atom)
        return atom

    def _note_conflicts(self, atom: EvidenceAtom) -> None:
        """A number that moves inside one holder's scenario is a disagreement, not a second fact.

        Only a memory that replaces nothing can start a conflict: a supersede has already
        picked a side, and recording it as unresolved would contradict that. And only a memory that
        leads with the same subject as its neighbour: two rooms' thermostats are two facts.
        """
        if atom.supersedes:
            return
        if not trust.numeric_values(atom.text).values:
            return
        for earlier in lifecycle_store.lane_atoms(self.db, atom.holder_id, atom.scenario):
            if earlier.atom_id == atom.atom_id:
                continue
            clash = trust.quantity_conflict(earlier.text, atom.text)
            if clash is None:
                continue
            lifecycle_store.record_conflict(
                self.db,
                older_atom_id=earlier.atom_id,
                newer_atom_id=atom.atom_id,
                holder_id=atom.holder_id,
                scenario=atom.scenario,
                terms=[clash.term],
                older_value=clash.older_value,
                newer_value=clash.newer_value,
                detected_at=utc_now(),
            )

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
        session_id: str = "",
        importance: float | None = None,
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
        # A correction takes effect when asserted: the old memory stops being current where the new one starts, so the pair is never true at the same instant.
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
            session_id=session_id,
            importance=importance,
        )
        self.db.close_atoms([atom_id], moment)
        self.vectors.sync_atoms([atom_id])
        return replacement

    def forget(
        self,
        *,
        atom_id: str | None = None,
        source_id: str | None = None,
        reason: str = "",
    ) -> ForgetReport:
        """Delete a memory and everything derived from it.

        The cascade is the whole point: a cached answer or a live vector will keep
        surfacing a memory the owner asked to erase, so both go with it.
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
        semantic_cleared = self.cache.drop_semantic_cache()
        if self.db.delete_source(target_source) != 1:
            raise ValueError(f"{target_source}: the source row vanished before the forget could erase it")
        vectors_dropped, visual_dropped = self._drop_derived_vectors(doomed_ids)
        return ForgetReport(
            source_id=target_source,
            atom_ids=doomed_ids,
            atoms_deleted=atoms_deleted,
            edges_deleted=edges_deleted,
            cache_entries_cleared=cache_cleared,
            semantic_cache_cleared=semantic_cleared,
            vectors_dropped=vectors_dropped,
            visual_index_dropped=visual_dropped,
            affected_cartridges=self._cartridges_holding(target_source),
            reason=reason,
        )

    def working_set(self, holder_id: str, session_id: str) -> list[EvidenceAtom]:
        """What this session recorded, in the order it recorded it: the short-term tier.

        No search is involved. A session asking for its own context gets exactly what it put
        down, which is the whole point of a working set rather than a wider top-k.
        """
        if not session_id.strip():
            raise ValueError("a working set needs a session; without one every memory is working memory")
        return lifecycle_store.session_atoms(self.db, holder_id, session_id)

    def consolidate(
        self, holder_id: str, scenario: str = "", *, at: datetime | None = None
    ) -> ConsolidationRecord | None:
        """Roll a lane's new memories into one standing summary and move the watermark.

        The summary replaces its own previous version under a fixed id, so a lane holds one
        rollup instead of a stack of them, and the ledger's watermark is what keeps a memory out
        of the next pass. Nothing is deleted: the individual memories stay current and findable,
        because a summary that erased the detail could not be questioned about where it came from.
        """
        moment = at or utc_now()
        ledger = lifecycle_store.read_ledger(self.db, holder_id, scenario)
        batch = [
            atom
            for atom in lifecycle_store.lane_atoms(
                self.db, holder_id, scenario, after=ledger.watermark_at if ledger else None
            )
            if not atom.atom_id.endswith(ROLLUP_SUFFIX)
        ]
        if not batch:
            return None

        lines: list[str] = []
        if ledger:
            previous = self.db.get_atoms([ledger.rollup_atom_id])
            if previous:
                lines.append(previous[0].text)
        lines.extend(atom.text for atom in batch)
        body = "\n".join(lines)

        digest = hashlib.sha256(f"{holder_id}\n{scenario}".encode()).hexdigest()
        source_id = f"rollup-{digest[:16]}"
        atom_id = f"{source_id}{ROLLUP_SUFFIX}"
        self.db.upsert_sources(
            [
                SourceRecord(
                    source_id=source_id,
                    path=f"memory://{holder_id}/{scenario or 'general'}#rollup",
                    kind="memory",
                    mime="text/plain",
                    sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    size_bytes=len(body.encode("utf-8")),
                    created_at=moment,
                    metadata={"holder_id": holder_id, "rollup": True},
                )
            ]
        )
        rollup = EvidenceAtom(
            atom_id=atom_id,
            modality=Modality.text,
            source_id=source_id,
            source=f"memory://{holder_id}/{scenario or 'general'}#rollup",
            ingested_at=moment,
            text=body,
            trust=MEMORY_TRUST,
            token_equivalent=token_equivalent(body),
            holder_id=holder_id,
            origin=MemoryOrigin.self_,
            scenario=scenario,
        )
        self.db.upsert_atoms([rollup])
        self.vectors.sync_atoms([atom_id])
        # The watermark is the newest memory actually rolled up, not the clock of the pass: a
        # consolidation run with a clock behind the memories would otherwise count them twice.
        record = ConsolidationRecord(
            holder_id=holder_id,
            scenario=scenario,
            watermark_at=max(atom.ingested_at for atom in batch),
            rollup_atom_id=atom_id,
            atom_count=(ledger.atom_count if ledger else 0) + len(batch),
            token_equivalent=token_equivalent(body),
            consolidated_at=moment,
        )
        lifecycle_store.write_ledger(self.db, record)
        return record

    def archive_stale(
        self,
        *,
        older_than_days: int,
        max_importance: float | None = None,
        at: datetime | None = None,
        dry_run: bool = False,
    ) -> ArchiveReport:
        """Move memories that were never used and never valued out of the current tier.

        The rule is stated instead of hidden in a decay formula: a memory goes when it was
        recorded before the cutoff, no search ever returned it, and nobody marked it important.
        Archived rows can be brought back; deleting them would make a wrong judgement
        unrecoverable, and the store's own estimate of what mattered is exactly the kind of thing
        that turns out to be wrong.
        """
        if older_than_days < 0:
            raise ValueError(f"older_than_days must not be negative, got {older_than_days}")
        moment = at or utc_now()
        cutoff = moment - timedelta(days=older_than_days)
        candidates = lifecycle_store.stale_candidates(self.db, before=cutoff, max_importance=max_importance)
        moved = 0 if dry_run else lifecycle_store.archive_atoms(self.db, candidates, moment)
        if not dry_run and moved != len(candidates):
            raise ValueError(f"{len(candidates)} memories were chosen for the archive but {moved} were moved")
        floor = "any importance" if max_importance is None else f"importance unset or at or under {max_importance}"
        return ArchiveReport(
            atom_ids=candidates,
            archived_at=moment,
            rule=f"recorded before {cutoff.isoformat()}, never returned by a search, {floor}",
            dry_run=dry_run,
        )

    def archived(self, holder_id: str | None = None) -> list[EvidenceAtom]:
        """The long-term tier: what the current view hides, listed rather than guessed at."""
        return lifecycle_store.archived_atoms(self.db, holder_id)

    def restore(self, atom_ids: list[str]) -> int:
        """Bring archived memories back: the archive is a tier, not a verdict."""
        if not atom_ids:
            raise ValueError("restore needs atom ids; nothing was named")
        return lifecycle_store.restore_atoms(self.db, atom_ids)

    def conflicts(self, holder_id: str | None = None) -> list[ConflictRecord]:
        """Every disagreement the store noticed and nobody has settled."""
        return lifecycle_store.open_conflicts(self.db, holder_id)

    def resolve_conflicts(self, conflict_ids: list[int], *, at: datetime | None = None) -> int:
        """Settle disagreements so retrieval stops dropping a side on the store's own reading."""
        if not conflict_ids:
            raise ValueError("resolving needs conflict ids; nothing was named")
        return lifecycle_store.resolve_conflicts(self.db, conflict_ids, at or utc_now())

    def _drop_derived_vectors(self, atom_ids: list[str]) -> tuple[int, bool]:
        """A forgotten memory must stop answering from the derived indexes too.

        The dense vectors live in the database beside the atoms, so they go one memory at a
        time. The picture index is one file for the whole store, so it is dropped and rebuilt.
        """
        dropped = self.vectors.drop_atoms(atom_ids)
        return dropped, self.pictures.drop()

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
