"""One place decides which adapter loads, and says out loud why the others do not."""

from __future__ import annotations

import logging
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from . import cartridge_store
from .config import Settings
from .db import Database
from .runtime_schemas import (
    AdapterChoice,
    AdapterLoadReport,
    AdapterManifest,
    AdapterOrigin,
    AdapterState,
)
from .schemas import TrainingAdapterKind

logger = logging.getLogger("ely_eye.adapters")

MANIFEST_FILE = "adapter_manifest.json"
WEIGHTS_FILE = "adapter_model.safetensors"


@dataclass(frozen=True)
class AdapterSource:
    """One adapter found on disk, plus where it was found."""

    path: Path
    manifest: AdapterManifest
    origin: AdapterOrigin
    cartridge_id: str | None


@dataclass(frozen=True)
class LoadRecord:
    """One adapter this process attached to one model."""

    source: AdapterSource

    @property
    def kind(self) -> TrainingAdapterKind:
        return self.source.manifest.kind

    @property
    def adapter_id(self) -> str:
        return self.source.manifest.adapter_id

    @property
    def path(self) -> str:
        return str(self.source.path)

    @property
    def sha256(self) -> str:
        return self.source.manifest.sha256


_ATTACHMENTS: list[tuple[LoadRecord, weakref.ReferenceType[object]]] = []


def read_manifest(path: Path) -> AdapterManifest:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"{path}: the adapter manifest cannot be read ({error})") from error
    try:
        return AdapterManifest.model_validate_json(text)
    except ValidationError as error:
        raise ValueError(
            f"{path}: the adapter manifest is not a valid AdapterManifest ({error})"
        ) from error


def cartridge_roots(database: Database) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for row in database.list_cartridges():
        roots[str(row["cartridge_id"])] = Path(str(row["root_path"]))
    return roots


def library_sources(settings: Settings) -> list[AdapterSource]:
    """Adapters in the library directory, for callers that have no database open."""
    if settings.adapter_dir is not None:
        pinned = settings.adapter_dir.expanduser()
        if not (pinned / MANIFEST_FILE).exists():
            logger.warning("adapter_dir %s holds no %s", pinned, MANIFEST_FILE)
            return []
        manifest = read_manifest(pinned / MANIFEST_FILE)
        return [
            AdapterSource(
                path=pinned,
                manifest=manifest,
                origin="library",
                cartridge_id=manifest.cartridge_id,
            )
        ]
    sources: list[AdapterSource] = []
    for manifest_path in sorted(settings.adapters_dir.glob(f"*/{MANIFEST_FILE}")):
        manifest = read_manifest(manifest_path)
        sources.append(
            AdapterSource(
                path=manifest_path.parent,
                manifest=manifest,
                origin="library",
                cartridge_id=manifest.cartridge_id,
            )
        )
    return sources


def discover(settings: Settings, database: Database) -> tuple[list[AdapterSource], list[str]]:
    """Every adapter the runtime could use: the library plus the copies inside mounted cartridges."""
    mounted = cartridge_store.mounted_ids(database)
    roots = cartridge_roots(database)
    sources = library_sources(settings)
    for cartridge_id in mounted:
        root = roots.get(cartridge_id)
        if root is None:
            logger.warning(
                "cartridge %s is mounted but its directory is not registered", cartridge_id
            )
            continue
        for manifest_path in sorted((root / "adapters").glob(f"*/{MANIFEST_FILE}")):
            sources.append(
                AdapterSource(
                    path=manifest_path.parent,
                    manifest=read_manifest(manifest_path),
                    origin="cartridge",
                    cartridge_id=cartridge_id,
                )
            )
    return sources, mounted


def resolve(
    sources: list[AdapterSource],
    settings: Settings,
    kind: TrainingAdapterKind,
) -> tuple[AdapterSource | None, AdapterState, str]:
    """Pick the adapter to load for one kind, or say which state it is stuck in and why."""
    candidates = [source for source in sources if source.manifest.kind == kind]
    if not candidates:
        return None, "missing", f"no adapter of kind {kind.value} is on disk"
    matching = [source for source in candidates if source.manifest.base_model == settings.model_id]
    if not matching:
        trained_on = ", ".join(sorted({source.manifest.base_model for source in candidates}))
        return (
            None,
            "deferred",
            f"every {kind.value} adapter is trained on {trained_on}; the runtime holds {settings.model_id}",
        )
    ready = [source for source in matching if (source.path / WEIGHTS_FILE).exists()]
    if not ready:
        return (
            None,
            "deferred",
            f"the {kind.value} manifests are present but none carries {WEIGHTS_FILE}",
        )
    ready.sort(key=_preference, reverse=True)
    chosen = ready[0]
    if chosen.origin == "cartridge":
        return chosen, "available", f"selected from mounted cartridge {chosen.cartridge_id}"
    return chosen, "available", "selected from the adapter library"


def _preference(source: AdapterSource) -> tuple[bool, bool, float]:
    weights = source.path / WEIGHTS_FILE
    return (
        source.origin == "cartridge",
        source.manifest.cartridge_id is not None,
        weights.stat().st_mtime if weights.exists() else 0.0,
    )


def load_records() -> list[LoadRecord]:
    """Every adapter still attached, or attached since the last load, in attachment order."""
    return [record for record, _reference in _ATTACHMENTS]


def live_attachments() -> list[LoadRecord]:
    """Attachments whose model still exists; a dead model cannot be claimed as loaded."""
    return [record for record, reference in _ATTACHMENTS if reference() is not None]


def record_load(source: AdapterSource, model: Any) -> LoadRecord:
    record = LoadRecord(source=source)
    _ATTACHMENTS[:] = [
        (item, reference) for item, reference in _ATTACHMENTS if reference() is not None
    ]
    _ATTACHMENTS.append((record, weakref.ref(model)))
    logger.info("loaded adapter %s (%s) from %s", record.adapter_id, record.kind.value, record.path)
    return record


def load_into_model(model: Any, path: Path) -> Any:
    """Attach one LoRA to a live model; the only place generation imports peft."""
    from .training_metrics import bitsandbytes_gaudi_probe_guard

    with bitsandbytes_gaudi_probe_guard():
        from peft import PeftModel

        return PeftModel.from_pretrained(model, str(path))


def plan(settings: Settings, database: Database) -> AdapterLoadReport:
    """One row per adapter kind, plus a row for every adapter that lost the choice."""
    sources, mounted = discover(settings, database)
    rows: list[AdapterChoice] = []
    winners: dict[str, AdapterSource | None] = {}
    attached = live_attachments()
    for kind in TrainingAdapterKind:
        source, state, reason = resolve(sources, settings, kind)
        winners[kind.value] = source
        live = [record for record in attached if record.kind == kind]
        earlier = next((record for record in reversed(load_records()) if record.kind == kind), None)
        if live:
            newest = live[-1]
            state = "loaded"
            reason = f"attached to the live model from {newest.path}"
            held = sorted({record.adapter_id for record in live[:-1] if record.adapter_id != newest.adapter_id})
            if held:
                subject = "another live model still holds" if len(held) == 1 else "other live models still hold"
                reason = f"{reason}; {subject} {' and '.join(held)}"
            rows.append(_choice(kind, state, reason, newest.source))
            continue
        if earlier is not None and source is not None:
            state = "available"
            reason = f"{reason}; {earlier.adapter_id} was attached earlier in this process and that model is gone"
        rows.append(_choice(kind, state, reason, source))
    for source in sources:
        winner = winners.get(source.manifest.kind.value)
        if winner is None or source.path == winner.path:
            continue
        rows.append(
            _choice(
                source.manifest.kind,
                "deferred",
                f"shadowed by {winner.manifest.adapter_id} for the current mount",
                source,
                shadowed=True,
            )
        )
    return AdapterLoadReport(model_id=settings.model_id, mounted=mounted, adapters=rows)


def _choice(
    kind: TrainingAdapterKind,
    state: AdapterState,
    reason: str,
    source: AdapterSource | None,
    shadowed: bool = False,
) -> AdapterChoice:
    """Build one report row from the adapter the row is actually talking about."""
    return AdapterChoice(
        kind=kind,
        state=state,
        reason=reason,
        path=str(source.path) if source else None,
        adapter_id=source.manifest.adapter_id if source else None,
        base_model=source.manifest.base_model if source else None,
        origin=source.origin if source else None,
        cartridge_id=source.cartridge_id if source else None,
        shadowed=shadowed,
    )
