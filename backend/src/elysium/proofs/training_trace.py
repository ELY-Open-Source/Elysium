"""Check that an adapter's training artifacts tell a consistent story.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ..runtime_schemas import AdapterManifest
from ..schemas import TrainingAdapterKind
from ..training_common import (
    AUTOCAST_DTYPE,
    GRADIENT_CHECKPOINTING_MODE,
    TRAINING_FRAMEWORK,
    TRAINING_METHOD,
    TRAINING_PRECISION,
    TRAINING_PROOF_VERSION,
    sha256_file,
)
from ..training_metrics import safetensor_weight_stats


def cuda_bf16_training(environment: dict[str, Any]) -> bool:
    """The requirement is CUDA plus BF16 support, not one card name written down in 2025."""
    return bool(environment.get("cuda_available")) and bool(environment.get("bf16_supported"))


def count_safetensor_keys(path: Path) -> int:
    return int(safetensor_weight_stats(path)["tensor_count"])


def peft_config_loads(path: Path) -> bool:
    try:
        from peft import PeftConfig

        PeftConfig.from_pretrained(str(path))
        return True
    except Exception:  # noqa: BLE001  # a probe records its failure instead of crashing the proof run
        return False


def validate_training_contract(manifest: AdapterManifest) -> dict[str, Any]:
    target_modules_ok = training_target_modules_ok(manifest.kind, manifest.target_modules)
    report = {
        "proof_version_ok": manifest.proof_version >= TRAINING_PROOF_VERSION,
        "method_ok": manifest.training_method == TRAINING_METHOD,
        "precision_ok": manifest.precision == TRAINING_PRECISION and manifest.bf16,
        "framework_ok": manifest.framework == TRAINING_FRAMEWORK,
        "optimizer_ok": manifest.optimizer == "paged_adamw_8bit",
        "optimizer_family_ok": manifest.optimizer_family == "8-bit AdamW / paged optimizer",
        "gradient_checkpointing_ok": (
            manifest.gradient_checkpointing
            and manifest.gradient_checkpointing_mode == GRADIENT_CHECKPOINTING_MODE
        ),
        "autocast_dtype_ok": manifest.autocast_dtype == AUTOCAST_DTYPE,
        "unsloth_version_ok": bool(manifest.unsloth_version),
        "triton_version_ok": bool(manifest.triton_version),
        "xformers_version_ok": bool(manifest.xformers_version),
        "unsloth_model_type_ok": bool(manifest.unsloth_model_type),
        "max_length_ok": manifest.max_length >= 8192,
        "target_modules_ok": target_modules_ok,
    }
    report["valid"] = all(report.values())
    return report


def training_target_modules_ok(kind: TrainingAdapterKind, target_modules: list[str]) -> bool:
    targets = set(target_modules)
    core = {"q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"}
    if kind == TrainingAdapterKind.hme_core_lora:
        return core.issubset(targets)
    if kind == TrainingAdapterKind.hme_vision_lora:
        return bool(targets) and any("visual" in target or "vision" in target for target in targets)
    if kind == TrainingAdapterKind.hme_ttt_vl:
        has_visual = any("visual" in target or "vision" in target for target in targets)
        has_mlp = bool({"gate_proj", "up_proj", "down_proj"} & targets)
        return has_visual and has_mlp
    if kind == TrainingAdapterKind.hme_visual_mtp:
        return any("mtp" in target or "draft" in target or target == "lm_head" for target in targets)
    if kind in {TrainingAdapterKind.hme_router, TrainingAdapterKind.hme_retrieval}:
        return core.issubset(targets)
    return False


def training_payload_contract_ok(payload: dict[str, Any], manifest: AdapterManifest) -> bool:
    return (
        int(payload.get("proof_version") or 0) >= TRAINING_PROOF_VERSION
        and payload.get("training_method") == TRAINING_METHOD
        and payload.get("precision") == TRAINING_PRECISION
        and payload.get("framework") == TRAINING_FRAMEWORK
        and payload.get("optimizer_family") == manifest.optimizer_family
        and bool(payload.get("gradient_checkpointing"))
        and payload.get("gradient_checkpointing_mode") == GRADIENT_CHECKPOINTING_MODE
        and payload.get("autocast_dtype") == AUTOCAST_DTYPE
        and payload.get("unsloth_version") == manifest.unsloth_version
        and payload.get("triton_version") == manifest.triton_version
        and payload.get("xformers_version") == manifest.xformers_version
        and payload.get("unsloth_model_type") == manifest.unsloth_model_type
    )


def validate_training_trace(manifest: AdapterManifest, adapter_root: Path) -> dict[str, Any]:
    trace_path = adapter_root / "training_trace.jsonl"
    summary_path = adapter_root / "training_summary.json"
    report: dict[str, Any] = {
        "trace_path": str(trace_path),
        "summary_path": str(summary_path),
        "trace_exists": trace_path.exists(),
        "summary_exists": summary_path.exists(),
        "trace_sha256_ok": False,
        "summary_sha256_ok": False,
        "step_records": 0,
        "loss_history_records": len(manifest.loss_history),
        "loss_history_ok": False,
        "summary_matches_manifest": False,
        "summary_contract_ok": False,
        "run_start_contract_ok": False,
        "run_finish_contract_ok": False,
        "cuda_training": False,
        "bf16_supported": False,
        "bf16": manifest.bf16,
        "valid": False,
    }
    if not trace_path.exists() or not summary_path.exists():
        return report
    try:
        trace_rows = [
            json.loads(line)
            for line in trace_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return report

    step_rows = [row for row in trace_rows if row.get("event") == "step"]
    start_row: dict[str, Any] = next((row for row in trace_rows if row.get("event") == "run_start"), {})
    finish_row: dict[str, Any] = next(
        (row for row in reversed(trace_rows) if row.get("event") == "run_finish"), {}
    )
    losses = [row.get("loss") for row in step_rows]
    finite_losses = all(isinstance(loss, (int, float)) and math.isfinite(float(loss)) for loss in losses)
    final_loss_ok = (
        manifest.final_loss is not None
        and bool(losses)
        and abs(float(losses[-1]) - float(manifest.final_loss)) < 1e-6
    )
    report.update(
        {
            "trace_sha256_ok": (
                manifest.training_trace_sha256 is not None
                and sha256_file(trace_path) == manifest.training_trace_sha256
            ),
            "summary_sha256_ok": (
                manifest.training_summary_sha256 is not None
                and sha256_file(summary_path) == manifest.training_summary_sha256
            ),
            "step_records": len(step_rows),
            "loss_history_ok": (
                len(manifest.loss_history) == manifest.max_steps
                and finite_losses
                and final_loss_ok
            ),
            "summary_matches_manifest": (
                summary.get("adapter_kind") == manifest.kind.value
                and summary.get("base_model") == manifest.base_model
                and summary.get("dataset_sha256") == manifest.dataset_sha256
                and int(summary.get("max_steps") or -1) == manifest.max_steps
                and int(summary.get("trainable_params") or -1) == manifest.trainable_params
            ),
            "summary_contract_ok": training_payload_contract_ok(summary, manifest),
            "run_start_contract_ok": training_payload_contract_ok(start_row, manifest),
            "run_finish_contract_ok": training_payload_contract_ok(finish_row, manifest),
        }
    )
    environment = summary.get("environment") if isinstance(summary.get("environment"), dict) else {}
    report["cuda_training"] = cuda_bf16_training(environment)
    report["bf16_supported"] = bool(environment.get("bf16_supported"))
    report["valid"] = (
        report["trace_sha256_ok"]
        and report["summary_sha256_ok"]
        and report["step_records"] == manifest.max_steps
        and report["loss_history_ok"]
        and report["summary_matches_manifest"]
        and report["summary_contract_ok"]
        and report["run_start_contract_ok"]
        and report["run_finish_contract_ok"]
        and report["cuda_training"]
        and report["bf16_supported"]
        and manifest.bf16
    )
    return report


def validate_training_proof(manifest: AdapterManifest, adapter_root: Path) -> dict[str, Any]:
    proof_path = adapter_root / "training_proof.json"
    report: dict[str, Any] = {
        "proof_path": str(proof_path),
        "proof_exists": proof_path.exists(),
        "proof_sha256_ok": False,
        "hash_changed": False,
        "optimizer_update_count": manifest.optimizer_update_count,
        "optimizer_update_count_ok": False,
        "max_optimizer_update_l2": manifest.max_optimizer_update_l2,
        "max_optimizer_update_l2_ok": False,
        "loss_delta": manifest.loss_delta,
        "loss_delta_finite": False,
        "updates_have_gradients": False,
        "updates_have_weight_delta": False,
        "proof_weight_sha256_ok": False,
        "proof_weight_stats_ok": False,
        "proof_cuda_bf16": False,
        "proof_bf16_supported": False,
        "proof_contract_ok": False,
        "proof_optimizer_ok": False,
        "proof_max_length_ok": False,
        "proof_target_modules_ok": False,
        "proof_unsloth_runtime_ok": False,
        "proof_matches_manifest": False,
        "valid": False,
    }
    if not proof_path.exists():
        return report
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return report

    updates = proof.get("optimizer_updates") if isinstance(proof.get("optimizer_updates"), list) else []
    update_l2_values = [
        float(value)
        for item in updates
        if isinstance(item, dict) and isinstance(value := item.get("update_l2"), (int, float))
    ]
    gradient_l2_values = [
        float(value)
        for item in updates
        if isinstance(item, dict) and isinstance(value := item.get("gradient_l2"), (int, float))
    ]
    weight_report = safetensor_weight_stats(adapter_root / "adapter_model.safetensors")
    proof_weight_stats = proof.get("adapter_weight_stats") if isinstance(proof.get("adapter_weight_stats"), dict) else {}
    proof_environment = proof.get("environment") if isinstance(proof.get("environment"), dict) else {}
    report.update(
        {
            "proof_sha256_ok": (
                manifest.training_proof_sha256 is not None
                and sha256_file(proof_path) == manifest.training_proof_sha256
            ),
            "hash_changed": (
                bool(manifest.initial_trainable_sha256)
                and bool(manifest.final_trainable_sha256)
                and manifest.initial_trainable_sha256 != manifest.final_trainable_sha256
            ),
            "optimizer_update_count_ok": (
                manifest.optimizer_update_count > 0
                and len(updates) == manifest.optimizer_update_count
            ),
            "max_optimizer_update_l2_ok": (
                manifest.max_optimizer_update_l2 is not None
                and math.isfinite(float(manifest.max_optimizer_update_l2))
                and float(manifest.max_optimizer_update_l2) > 0.0
            ),
            "loss_delta_finite": (
                manifest.loss_delta is not None
                and math.isfinite(float(manifest.loss_delta))
            ),
            "updates_have_gradients": bool(gradient_l2_values)
            and all(math.isfinite(value) and value > 0.0 for value in gradient_l2_values),
            "updates_have_weight_delta": bool(update_l2_values)
            and all(math.isfinite(value) and value > 0.0 for value in update_l2_values),
            "proof_weight_sha256_ok": (
                isinstance(proof.get("adapter_weight_sha256"), str)
                and proof.get("adapter_weight_sha256") == weight_report["sha256"]
            ),
            "proof_weight_stats_ok": (
                proof_weight_stats.get("sha256") == weight_report["sha256"]
                and proof_weight_stats.get("tensor_count") == weight_report["tensor_count"]
                and proof_weight_stats.get("lora_tensor_count") == weight_report["lora_tensor_count"]
                and proof_weight_stats.get("total_elements") == weight_report["total_elements"]
                and proof_weight_stats.get("nonzero_elements") == weight_report["nonzero_elements"]
                and int(proof_weight_stats.get("lora_tensor_count") or 0) > 0
                and int(proof_weight_stats.get("nonzero_elements") or 0) > 0
                and bool(proof_weight_stats.get("all_finite"))
            ),
            "proof_cuda_bf16": bool(proof.get("bf16")) and cuda_bf16_training(proof_environment),
            "proof_bf16_supported": bool(proof_environment.get("bf16_supported")),
            "proof_contract_ok": training_payload_contract_ok(proof, manifest),
            "proof_optimizer_ok": proof.get("optimizer") == "paged_adamw_8bit",
            "proof_max_length_ok": int(proof.get("max_length") or 0) >= 8192,
            "proof_target_modules_ok": training_target_modules_ok(
                manifest.kind,
                proof.get("target_modules") if isinstance(proof.get("target_modules"), list) else [],
            ),
            "proof_unsloth_runtime_ok": (
                bool(proof.get("unsloth_version"))
                and bool(proof.get("triton_version"))
                and bool(proof.get("xformers_version"))
                and bool(proof.get("unsloth_model_type"))
            ),
            "proof_matches_manifest": (
                proof.get("adapter_kind") == manifest.kind.value
                and proof.get("proof_version") == manifest.proof_version
                and proof.get("training_method") == manifest.training_method
                and proof.get("precision") == manifest.precision
                and proof.get("framework") == manifest.framework
                and proof.get("base_model") == manifest.base_model
                and proof.get("dataset_sha256") == manifest.dataset_sha256
                and proof.get("sample_count") == manifest.sample_count
                and proof.get("max_steps") == manifest.max_steps
                and proof.get("max_length") == manifest.max_length
                and proof.get("rank") == manifest.rank
                and proof.get("alpha") == manifest.alpha
                and proof.get("target_modules") == manifest.target_modules
                and proof.get("optimizer") == manifest.optimizer
                and proof.get("optimizer_family") == manifest.optimizer_family
                and proof.get("learning_rate") == manifest.learning_rate
                and proof.get("gradient_accumulation_steps") == manifest.gradient_accumulation_steps
                and proof.get("gradient_checkpointing") == manifest.gradient_checkpointing
                and proof.get("gradient_checkpointing_mode") == manifest.gradient_checkpointing_mode
                and proof.get("autocast_dtype") == manifest.autocast_dtype
                and proof.get("unsloth_version") == manifest.unsloth_version
                and proof.get("triton_version") == manifest.triton_version
                and proof.get("xformers_version") == manifest.xformers_version
                and proof.get("unsloth_model_type") == manifest.unsloth_model_type
                and proof.get("bf16") == manifest.bf16
                and proof.get("trainable_params") == manifest.trainable_params
                and proof.get("total_params") == manifest.total_params
                and proof.get("initial_trainable_sha256") == manifest.initial_trainable_sha256
                and proof.get("final_trainable_sha256") == manifest.final_trainable_sha256
                and proof.get("optimizer_update_count") == manifest.optimizer_update_count
                and proof.get("max_optimizer_update_l2") == manifest.max_optimizer_update_l2
            ),
        }
    )
    report["valid"] = (
        report["proof_sha256_ok"]
        and report["hash_changed"]
        and report["optimizer_update_count_ok"]
        and report["max_optimizer_update_l2_ok"]
        and report["loss_delta_finite"]
        and report["updates_have_gradients"]
        and report["updates_have_weight_delta"]
        and report["proof_weight_sha256_ok"]
        and report["proof_weight_stats_ok"]
        and report["proof_cuda_bf16"]
        and report["proof_bf16_supported"]
        and report["proof_contract_ok"]
        and report["proof_optimizer_ok"]
        and report["proof_max_length_ok"]
        and report["proof_target_modules_ok"]
        and report["proof_unsloth_runtime_ok"]
        and report["proof_matches_manifest"]
    )
    return report
