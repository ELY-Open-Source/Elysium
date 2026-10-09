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
    quarantined: bool = False
    session_id: str = ""
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    recall_count: int = Field(default=0, ge=0)
    last_recalled_at: datetime | None = None
    archived_at: datetime | None = None

    @model_validator(mode="after")
    def _times_are_ordered(self) -> EvidenceAtom:
        if self.event_time and self.event_time_end and self.event_time_end < self.event_time:
            raise ValueError(f"{self.atom_id}: event_time_end precedes event_time")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError(f"{self.atom_id}: valid_to precedes valid_from")
        if self.atom_id in self.supersedes:
            raise ValueError(f"{self.atom_id}: an atom cannot supersede itself")
        return self

    @field_validator("ingested_at", "event_time", "event_time_end", "valid_from", "valid_to", "retention_until", "last_recalled_at", "archived_at")
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


class AtomPage(BaseModel):
    """A page of the store plus the total behind it, so a list can admit what it left out."""

    atoms: list[EvidenceAtom]
    total: int
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
    quarantined_excluded: list[str] = Field(default_factory=list)

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

class ForgetReport(BaseModel):
    """What a forget actually removed, including the derived copies that have to go with it."""

    source_id: str
    atom_ids: list[str]
    atoms_deleted: int
    edges_deleted: int
    cache_entries_cleared: int
    semantic_cache_cleared: int
    vectors_dropped: int
    visual_index_dropped: bool
    affected_cartridges: list[dict[str, Any]]
    reason: str


class ConsolidationRecord(BaseModel):
    """One lane of the long-term ledger: everything up to the watermark has been rolled up, and
    the next pass starts there so no memory is counted into two rollups.
    """

    holder_id: str
    scenario: str = ""
    watermark_at: datetime
    rollup_atom_id: str
    atom_count: int = Field(ge=0)
    token_equivalent: int = Field(ge=0)
    consolidated_at: datetime


class ConflictRecord(BaseModel):
    """Two memories of one holder that cannot both be current, with the value each side states."""

    conflict_id: int
    older_atom_id: str
    newer_atom_id: str
    holder_id: str
    scenario: str = ""
    terms: list[str] = Field(default_factory=list)
    older_value: str
    newer_value: str
    detected_at: datetime
    resolved_at: datetime | None = None


class ArchiveReport(BaseModel):
    """Which memories left the current tier, and the rule that moved them.

    `archived_at` is the moment the rule stamps; on a dry run it is the moment it would
    stamp, and `atom_ids` is the list the sentence would fall on.
    """

    atom_ids: list[str]
    archived_at: datetime
    rule: str
    dry_run: bool = False


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
    session_id: str = ""
    importance: float | None = Field(default=None, ge=0.0, le=1.0)


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
