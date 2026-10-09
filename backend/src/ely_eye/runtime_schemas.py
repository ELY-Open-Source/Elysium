"""Runtime and adapter shapes: what the model holds in memory, what trained it, and how a machine
launches it. A proof report moves when the evidence rules move; the memory model should not.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .schemas import TrainingAdapterKind, utc_now

AdapterState = Literal["loaded", "available", "deferred", "missing"]
AdapterOrigin = Literal["library", "cartridge"]


class AdapterChoice(BaseModel):
    """One adapter kind, and the honest reason it is or is not attached to the model."""

    kind: TrainingAdapterKind
    state: AdapterState
    reason: str
    path: str | None = None
    adapter_id: str | None = None
    base_model: str | None = None
    origin: AdapterOrigin | None = None
    cartridge_id: str | None = None
    shadowed: bool = False


class AdapterLoadReport(BaseModel):
    model_id: str
    mounted: list[str]
    adapters: list[AdapterChoice]

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
