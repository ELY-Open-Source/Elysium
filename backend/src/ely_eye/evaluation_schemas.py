"""Report shapes for the evaluation and proof layer.

These describe what a run claims, not what the memory holds, so they live apart from the
memory and runtime schemas: a proof report changes when the evidence rules change, and the
memory model should not move with it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .schemas import utc_now


class BenchmarkSpec(BaseModel):
    name: str
    target: str
    dataset: str
    task_type: str
    runner: str
    metric: str

class BenchmarkRegistryReport(BaseModel):
    status: Literal["ready", "incomplete"]
    created_at: datetime = Field(default_factory=utc_now)
    benchmarks: list[BenchmarkSpec]

class BenchmarkSourceStatus(BaseModel):
    name: str
    dataset: str
    status: Literal["ready", "unavailable"]
    sha: str | None = None
    gated: bool | str | None = None
    private: bool | None = None
    sibling_count: int = 0
    error: str | None = None

class BenchmarkSourceReport(BaseModel):
    status: Literal["ready", "incomplete"]
    created_at: datetime = Field(default_factory=utc_now)
    sources: list[BenchmarkSourceStatus]

class BenchmarkSampleStatus(BaseModel):
    name: str
    dataset: str
    source_dataset: str | None = None
    source_sha: str | None = None
    source_note: str | None = None
    status: Literal["loaded", "gated", "failed"]
    config: str | None = None
    split: str | None = None
    sample_id: str | None = None
    fields: list[str] = Field(default_factory=list)
    question_preview: str | None = None
    answer_preview: str | None = None
    sample_sha256: str | None = None
    media_artifacts: list[str] = Field(default_factory=list)
    error: str | None = None

class BenchmarkSampleReport(BaseModel):
    status: Literal["ready", "partial", "failed"]
    created_at: datetime = Field(default_factory=utc_now)
    samples: list[BenchmarkSampleStatus]

class BenchmarkPredictionStatus(BaseModel):
    name: str
    dataset: str
    status: Literal["predicted", "gated", "failed"]
    config: str | None = None
    split: str | None = None
    sample_id: str | None = None
    task_type: str
    metric: str
    prompt_sha256: str | None = None
    sample_sha256: str | None = None
    prediction: str | None = None
    answer: str | None = None
    score: float | None = None
    runtime_backend: str | None = None
    adapter_id: str | None = None
    adapter_sha256: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    media_artifacts: list[str] = Field(default_factory=list)
    error: str | None = None

class BenchmarkPredictionReport(BaseModel):
    status: Literal["ready", "partial", "failed"]
    created_at: datetime = Field(default_factory=utc_now)
    predictions: list[BenchmarkPredictionStatus]

class HashHopProof(BaseModel):
    proof_id: str
    kind: Literal["text_hashhop", "visual_hashhop"]
    hops: int
    token_equivalent: int
    query_id: str
    expected_target_id: str
    model_target_id: str | None = None
    passed: bool | None = None
    artifacts: list[str]
    created_at: datetime = Field(default_factory=utc_now)

class ProofCheck(BaseModel):
    name: str
    requirement: str
    status: Literal["passed", "failed"]
    evidence: list[str]
    detail: str

class ProofSuiteReport(BaseModel):
    proof_id: str
    cartridge_id: str
    status: Literal["passed", "failed"]
    created_at: datetime = Field(default_factory=utc_now)
    checks: list[ProofCheck]
    artifacts: dict[str, str]
    dna_before: str | None = None
    dna_after: str | None = None
