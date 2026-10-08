"""What the machine reports about itself: runtime, memory, cache layers, senses."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from .schemas import TrainingAdapterKind


class CacheLayerStatus(BaseModel):
    layer: str
    entries: int
    bytes_estimate: int
    hit_count: int
    miss_count: int
    last_event_at: datetime | None


class MemoryStatus(BaseModel):
    active_atoms: int
    active_token_equivalent: int
    cartridges: int
    library_token_equivalent: int
    layers: list[CacheLayerStatus]


class RuntimeStatus(BaseModel):
    backend: str
    model_id: str
    available: bool
    detail: str
    adapter_path: str | None = None
    adapter_kind: TrainingAdapterKind | None = None
    adapter_id: str | None = None
    adapter_sha256: str | None = None
    gpu_name: str | None = None
    cuda: str | None = None
    vram_total_mb: int | None = None
    vram_used_mb: int | None = None


SenseState = Literal["absent", "missing", "ready"]
VisualState = Literal["absent", "stale", "ready"]
DenseState = Literal["off", "missing", "behind", "current"]


class SenseStatus(BaseModel):
    """What the machine can perceive now; absent means no model was given, missing means the one it was given is gone."""

    dense: DenseState
    dense_covered: int
    dense_expected: int
    picture_atoms: int
    picture_bytes_missing: int
    visual: VisualState
    audio_atoms: int
    speech: SenseState
    captioning: SenseState
    clip_path: str | None = None
    asr_path: str | None = None
    vlm_path: str | None = None


class SystemStatus(BaseModel):
    app: str = "Ely-Eye"
    version: str
    runtime: RuntimeStatus
    memory: MemoryStatus
    senses: SenseStatus
    profiles: dict[str, dict[str, Any]]
    data_home: str
