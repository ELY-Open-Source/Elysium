from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .kv_fingerprint import KvFingerprint


def utc_now() -> datetime:
    return datetime.now(UTC)

class RuntimeProfile(StrEnum):
    live_demo = "live_demo"
    extreme_context = "extreme_context"
    library_100m = "library_100m"
    research_theater = "research_theater"

class TrainingAdapterKind(StrEnum):
    hme_core_lora = "hme_core_lora"
    hme_vision_lora = "hme_vision_lora"
    hme_ttt_vl = "hme_ttt_vl"
    hme_visual_mtp = "hme_visual_mtp"
    hme_router = "hme_router"
    hme_retrieval = "hme_retrieval"

class Modality(StrEnum):
    text = "text"
    code = "code"
    image = "image"
    pdf_page = "pdf_page"
    pdf_region = "pdf_region"
    video_frame = "video_frame"
    audio = "audio"
    ui_screenshot = "ui_screenshot"
    mixed = "mixed"

class MemoryOrigin(StrEnum):
    """Where a memory came from, which decides how much it may be trusted.

    A file the user handed over is not the same kind of claim as something the system
    watched happen, and neither is a statement the user made about themselves.
    """

    self_ = "self"
    observed = "observed"
    artifact = "artifact"
    third_party = "third_party"

class TimePrecision(StrEnum):
    """How finely the event time is actually known, so a day is never read as an instant."""

    instant = "instant"
    minute = "minute"
    hour = "hour"
    day = "day"
    month = "month"
    year = "year"
    unknown = "unknown"

class Visibility(BaseModel):
    """Who may use a memory. Retention lives on the atom itself because the current
    memory view has to filter on it."""

    scope: Literal["holder", "visible_to", "everyone"] = "holder"
    holders: list[str] = Field(default_factory=list)
    purpose: str | None = None

class LayoutBox(BaseModel):
    x: float
    y: float
    w: float
    h: float
    page: int | None = None
    frame_second: float | None = None

class TrustScores(BaseModel):
    parser: float = Field(ge=0.0, le=1.0)
    ocr: float = Field(default=0.0, ge=0.0, le=1.0)
    model: float = Field(default=0.0, ge=0.0, le=1.0)

class EvidenceAtom(BaseModel):
    atom_id: str
    modality: Modality
    source_id: str
    source: str
    ingested_at: datetime = Field(default_factory=utc_now)
    text: str = ""
    image_ref: str | None = None
    embedding_refs: list[str] = Field(default_factory=list)
    layout: LayoutBox | None = None
    relations: list[str] = Field(default_factory=list)
    trust: TrustScores
    token_equivalent: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    holder_id: str = ""
    origin: MemoryOrigin = MemoryOrigin.artifact
    scenario: str = ""
    event_time: datetime | None = None
    event_time_end: datetime | None = None
    event_time_precision: TimePrecision = TimePrecision.unknown
    event_time_source: str = ""
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    supersedes: list[str] = Field(default_factory=list)
    visibility: Visibility = Field(default_factory=Visibility)
    retention_until: datetime | None = None

    @model_validator(mode="after")
    def _times_are_ordered(self) -> EvidenceAtom:
        if self.event_time and self.event_time_end and self.event_time_end < self.event_time:
            raise ValueError(f"{self.atom_id}: event_time_end precedes event_time")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError(f"{self.atom_id}: valid_to precedes valid_from")
        if self.atom_id in self.supersedes:
            raise ValueError(f"{self.atom_id}: an atom cannot supersede itself")
        return self

    @field_validator("ingested_at", "event_time", "event_time_end", "valid_from", "valid_to", "retention_until")
    @classmethod
    def _times_are_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError(
                "memory timestamps need an explicit offset, e.g. 2026-05-01T12:00:00+08:00; "
                "a naive time cannot be compared with one that has an offset"
            )
        return value

class SourceRecord(BaseModel):
    source_id: str
    path: str
    kind: str
    mime: str
    sha256: str
    size_bytes: int
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

class SkippedFile(BaseModel):
    path: str
    reason: str

class IngestResponse(BaseModel):
    source_count: int
    atom_count: int
    cartridge_id: str | None
    token_equivalent: int
    sources: list[SourceRecord]
    skipped: list[SkippedFile] = []

class RetrievalHit(BaseModel):
    atom: EvidenceAtom
    sparse_score: float
    dense_score: float = 0.0
    visual_score: float = 0.0
    graph_score: float = 0.0
    final_score: float


class SearchFilters(BaseModel):
    """Who may answer, in what setting, and how fresh the memory has to be.

    A memory with no event time cannot satisfy since/until, so it drops out when a time bound is
    asked for rather than passing as unknown. `holder` restricts the answer to one holder's
    memories; `as_holder` is the identity asking, and applies the sharing rule instead.
    """

    holder: str | None = None
    as_holder: str | None = None
    scenario: str | None = None
    source_id: str | None = None
    modality: Modality | None = None
    cartridge_ids: list[str] | None = None
    since: datetime | None = None
    until: datetime | None = None
    min_trust: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _times_are_ordered(self) -> SearchFilters:
        if self.since and self.until and self.since > self.until:
            raise ValueError("search since must not be after until")
        return self


class SearchRequest(BaseModel):
    query: str
    top_k: int | None = Field(default=None, gt=0)
    filters: SearchFilters | None = None
    cursor: str | None = None
    image: Path | None = None


class SearchResult(BaseModel):
    """An empty answer says why: no_match is a claim about the corpus, [] is not."""

    query: str
    status: Literal["hits", "no_match"]
    hits: list[RetrievalHit]
    next_cursor: str | None = None

class ContextPlan(BaseModel):
    question: str
    profile: RuntimeProfile
    required_modalities: list[Modality]
    evidence_budget_atoms: int
    token_budget: int
    retrieval_query: str
    compression_strategy: str
    verifier_contract: list[str]

class CompiledContext(BaseModel):
    plan: ContextPlan
    hits: list[RetrievalHit]
    packed_text: str
    token_equivalent: int
    cache_trace_id: str

class CitationReport(BaseModel):
    cited_atom_ids: list[str]
    missing_atom_ids: list[str]
    citation_accuracy: float
    contradiction_notes: list[str]
    confidence: float

class AnswerResponse(BaseModel):
    answer: str
    citations: list[str]
    context: CompiledContext
    verifier: CitationReport
    runtime_backend: str

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

class SystemStatus(BaseModel):
    app: str = "Ely-Eye"
    version: str
    runtime: RuntimeStatus
    memory: MemoryStatus
    profiles: dict[str, dict[str, Any]]
    data_home: str

class MountState(BaseModel):
    """What is mounted now, and whether that narrows a search."""

    mounted: list[str]
    scoped: bool
    atoms_in_scope: int


class AppendRequest(BaseModel):
    atom_ids: list[str]


class CartridgeManifest(BaseModel):
    cartridge_id: str
    name: str
    created_at: datetime
    model_base: str
    source_count: int
    atom_count: int
    token_equivalent: int
    artifacts: dict[str, str]
    kv_fingerprint: KvFingerprint | None = None
    dna: str | None = None

class AdapterManifest(BaseModel):
    adapter_id: str
    kind: TrainingAdapterKind
    created_at: datetime
    proof_version: int = 1
    training_method: str = "BF16 LoRA"
    precision: str = "bf16"
    framework: str = "unsloth_patched_transformers_peft"
    base_model: str
    dataset_path: str
    dataset_sha256: str
    sample_count: int
    max_steps: int
    max_length: int
    rank: int
    alpha: int
    target_modules: list[str]
    trainable_params: int
    total_params: int
    optimizer: str
    optimizer_family: str | None = None
    learning_rate: float
    gradient_accumulation_steps: int
    gradient_checkpointing: bool = False
    gradient_checkpointing_mode: str | None = None
    autocast_dtype: str | None = None
    unsloth_version: str | None = None
    triton_version: str | None = None
    xformers_version: str | None = None
    unsloth_model_type: str | None = None
    bf16: bool
    final_loss: float | None
    loss_history: list[float] = Field(default_factory=list)
    initial_trainable_sha256: str | None = None
    final_trainable_sha256: str | None = None
    initial_trainable_l2: float | None = None
    final_trainable_l2: float | None = None
    optimizer_update_count: int = 0
    max_optimizer_update_l2: float | None = None
    loss_delta: float | None = None
    training_proof_path: str | None = None
    training_proof_sha256: str | None = None
    training_trace_path: str | None = None
    training_trace_sha256: str | None = None
    training_summary_path: str | None = None
    training_summary_sha256: str | None = None
    training_started_at: datetime | None = None
    training_finished_at: datetime | None = None
    training_wall_seconds: float | None = None
    training_device: str | None = None
    torch_version: str | None = None
    cuda_version: str | None = None
    adapter_weight_sha256: str | None = None
    adapter_tensor_count: int = 0
    adapter_lora_tensor_count: int = 0
    adapter_total_elements: int = 0
    adapter_nonzero_elements: int = 0
    adapter_max_abs: float | None = None
    adapter_weights_finite: bool = False
    artifacts: dict[str, str]
    sha256: str
    cartridge_id: str | None = None

class AdapterStatus(BaseModel):
    name: str
    kind: TrainingAdapterKind
    proof_version: int = 1
    training_method: str = "BF16 LoRA"
    precision: str = "bf16"
    framework: str = "unsloth_patched_transformers_peft"
    base_model: str
    path: str
    adapter_id: str
    sample_count: int
    max_steps: int
    trainable_params: int
    final_loss: float | None
    sha256: str
    weight_bytes: int
    safetensor_keys: int
    cartridge_id: str | None = None
    cartridge_bound: bool
    training_trace_path: str | None = None
    training_trace_sha256: str | None = None
    training_trace_steps: int = 0
    training_proof_path: str | None = None
    training_proof_sha256: str | None = None
    optimizer: str | None = None
    optimizer_family: str | None = None
    gradient_checkpointing: bool = False
    gradient_checkpointing_mode: str | None = None
    autocast_dtype: str | None = None
    unsloth_version: str | None = None
    triton_version: str | None = None
    xformers_version: str | None = None
    unsloth_model_type: str | None = None
    optimizer_update_count: int = 0
    max_optimizer_update_l2: float | None = None
    loss_delta: float | None = None
    training_summary_path: str | None = None
    training_wall_seconds: float | None = None
    training_device: str | None = None
    bf16: bool = False
    torch_version: str | None = None
    cuda_version: str | None = None
    adapter_weight_sha256: str | None = None
    adapter_tensor_count: int = 0
    adapter_lora_tensor_count: int = 0
    adapter_total_elements: int = 0
    adapter_nonzero_elements: int = 0
    adapter_max_abs: float | None = None
    adapter_weights_finite: bool = False

class CartridgeAssetStatus(BaseModel):
    name: str
    path: str
    sha256: str
    size_bytes: int
    item_count: int
    dtype: str
    status: Literal["ready", "missing"]

class CartridgeAssetReport(BaseModel):
    cartridge_id: str
    status: Literal["ready", "incomplete"]
    created_at: datetime = Field(default_factory=utc_now)
    assets: list[CartridgeAssetStatus]

class RuntimeLaunchProfile(BaseModel):
    name: str
    runtime: str
    role: str
    context_tokens: int
    script: str
    command: list[str]
    environment: dict[str, str] = Field(default_factory=dict)
    required_features: list[str] = Field(default_factory=list)

class RuntimeProfileValidation(BaseModel):
    name: str
    runtime: str
    status: Literal["ready", "missing"]
    script_exists: bool
    package: str | None = None
    package_version: str | None = None
    executable: str | None = None
    gpu_available: bool = False
    probe_command: list[str] = Field(default_factory=list)
    probe_status: Literal["passed", "failed", "skipped"] = "skipped"
    probe_exit_code: int | None = None
    probe_output: str | None = None
    detail: str

class RuntimeProfileReport(BaseModel):
    status: Literal["ready", "incomplete"]
    created_at: datetime = Field(default_factory=utc_now)
    profiles: list[RuntimeLaunchProfile]
    validations: list[RuntimeProfileValidation] = Field(default_factory=list)

class ForgetReport(BaseModel):
    """What a forget actually removed, including the derived copies that have to go with it."""

    source_id: str
    atom_ids: list[str]
    atoms_deleted: int
    edges_deleted: int
    cache_entries_cleared: int
    vector_index_dropped: bool
    affected_cartridges: list[dict[str, Any]]
    reason: str


class RememberRequest(BaseModel):
    """A memory as a caller states it. Holder, origin and ingestion time are stamped by the
    server, so they are absent here on purpose: a client cannot claim to be somebody else.
    """

    text: str
    scenario: str = ""
    event_time: datetime | None = None
    event_time_precision: TimePrecision = TimePrecision.unknown
    event_time_source: str = ""
    retention_until: datetime | None = None


class SupersedeRequest(RememberRequest):
    atom_id: str


class ForgetRequest(BaseModel):
    atom_id: str | None = None
    source_id: str | None = None
    reason: str = ""


class UploadIngestRequest(BaseModel):
    cartridge_name: str | None = None
    dense_embeddings: bool | None = None

class PathIngestRequest(BaseModel):
    path: Path
    cartridge_name: str | None = None
    dense_embeddings: bool | None = None
