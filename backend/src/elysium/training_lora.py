"""Train a LoRA adapter on a frozen dataset and write the manifest that proves it."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .db import Database
from .runtime_schemas import AdapterManifest
from .schemas import TrainingAdapterKind
from .training_common import (
        AUTOCAST_DTYPE,
        GRADIENT_CHECKPOINTING_MODE,
        TRAINING_FRAMEWORK,
        TRAINING_METHOD,
        TRAINING_PRECISION,
        TRAINING_PROOF_VERSION,
        adapter_id,
        relative_artifacts,
        sha256_file,
        sha256_tree,
        write_trace,
        write_training_summary,
)
from .training_datasets import model_for_kind, validate_dataset
from .training_encode import encode_training_sample
from .training_metrics import (
        activate_unsloth_training,
        bitsandbytes_gaudi_probe_guard,
        cuda_peak_memory_mb,
        enable_gradient_checkpointing,
        gradient_l2_norm,
        infer_lora_targets,
        make_optimizer,
        model_type_for_proof,
        optimizer_family,
        package_version,
        require_cuda_bf16,
        safetensor_weight_stats,
        trainable_l2_norm,
        trainable_named_parameters,
        trainable_state_cpu,
        trainable_state_sha256,
        trainable_update_l2,
        training_contract,
        training_environment,
)


def write_lora_config(
    settings: Settings,
    output_dir: Path,
    kind: TrainingAdapterKind = TrainingAdapterKind.hme_core_lora,
    rank: int = 16,
    alpha: int = 32,
    model_id: str | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "base_model": model_id or settings.model_id,
        "adapter_kind": kind.value,
        "method": "BF16 LoRA",
        "framework": TRAINING_FRAMEWORK,
        "rank": rank,
        "alpha": alpha,
        "gradient_checkpointing": True,
        "gradient_checkpointing_mode": GRADIENT_CHECKPOINTING_MODE,
        "precision": "bf16",
        "optimizer": "paged_adamw_8bit",
        "ensure_weight_tying": kind == TrainingAdapterKind.hme_visual_mtp,
    }
    path = output_dir / "lora_config.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

def train_lora(
    settings: Settings,
    database: Database,
    dataset_path: Path,
    output_dir: Path,
    max_steps: int,
    kind: TrainingAdapterKind = TrainingAdapterKind.hme_core_lora,
    model_id: str | None = None,
    rank: int = 16,
    alpha: int = 32,
    max_length: int | None = None,
    gradient_accumulation_steps: int | None = None,
    learning_rate: float | None = None,
    cartridge_id: str | None = None,
) -> AdapterManifest:
    samples = validate_dataset(dataset_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    model_id = model_id or model_for_kind(settings, kind)
    max_length = max_length or settings.train_max_length
    gradient_accumulation_steps = (
        gradient_accumulation_steps or settings.train_gradient_accumulation_steps
    )
    learning_rate = learning_rate or settings.train_learning_rate
    started_at = datetime.now(UTC)
    wall_start = time.perf_counter()
    trace_path = output_dir / "training_trace.jsonl"

    import torch

    activate_unsloth_training()
    from peft import LoraConfig, get_peft_model
    from transformers import AutoProcessor

    try:
        from transformers import AutoModelForImageTextToText

        model_cls = AutoModelForImageTextToText
    except ImportError:
        from transformers import AutoModelForCausalLM

        model_cls = AutoModelForCausalLM

    require_cuda_bf16(torch)
    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    dtype = torch.bfloat16
    device_map: dict[str, int] = {"": 0}
    model = model_cls.from_pretrained(
        model_id,
        dtype=dtype,
        device_map=device_map,
        trust_remote_code=True,
    )
    model.config.use_cache = False
    input_require_grads = False
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()
        input_require_grads = True

    target_modules = infer_lora_targets(model, kind)
    gradient_checkpointing = enable_gradient_checkpointing(model)
    peft_config_options: dict[str, Any] = {
        "r": rank,
        "lora_alpha": alpha,
        "target_modules": target_modules,
        "lora_dropout": 0.0,
        "bias": "none",
        "task_type": "CAUSAL_LM",
    }
    if kind == TrainingAdapterKind.hme_visual_mtp:
        peft_config_options["ensure_weight_tying"] = True
    with bitsandbytes_gaudi_probe_guard():
        model = get_peft_model(model, LoraConfig(**peft_config_options))
    unsloth_model_type = model_type_for_proof(model)
    trainable_params, total_params = model.get_nb_trainable_parameters()
    optimizer, optimizer_name = make_optimizer(model, learning_rate)
    model.train()

    losses: list[float] = []
    optimizer_updates: list[dict[str, Any]] = []
    trainable_tensors = trainable_named_parameters(model)
    initial_trainable_sha = trainable_state_sha256(trainable_tensors)
    initial_trainable_l2 = trainable_l2_norm(trainable_tensors)
    optimizer.zero_grad(set_to_none=True)
    environment = training_environment(torch)
    contract = training_contract(
        gradient_checkpointing=gradient_checkpointing,
        input_require_grads=input_require_grads,
        optimizer_name=optimizer_name,
        unsloth_model_type=unsloth_model_type,
    )
    with trace_path.open("w", encoding="utf-8", newline="\n") as trace:
        write_trace(
            trace,
            {
                "event": "run_start",
                **contract,
                "started_at": started_at.isoformat(),
                "adapter_kind": kind.value,
                "base_model": model_id,
                "dataset_path": str(dataset_path.resolve()),
                "dataset_sha256": sha256_file(dataset_path),
                "sample_count": len(samples),
                "max_steps": max_steps,
                "max_length": max_length,
                "rank": rank,
                "alpha": alpha,
                "gradient_accumulation_steps": gradient_accumulation_steps,
                "learning_rate": learning_rate,
                "target_modules": target_modules,
                "trainable_params": int(trainable_params),
                "total_params": int(total_params),
                "optimizer": optimizer_name,
                "environment": environment,
            },
        )
        for step in range(max_steps):
            sample = samples[step % len(samples)]
            batch = encode_training_sample(sample, processor, model.device, max_length)
            with torch.autocast(
                device_type="cuda",
                dtype=torch.bfloat16,
                enabled=torch.cuda.is_available(),
            ):
                outputs = model(**batch)
                loss = outputs.loss / gradient_accumulation_steps
            loss.backward()
            optimizer_step = (step + 1) % gradient_accumulation_steps == 0 or (step + 1) == max_steps
            grad_l2 = gradient_l2_norm(trainable_tensors)
            update_l2 = None
            if optimizer_step:
                before_update = trainable_state_cpu(trainable_tensors)
                optimizer.step()
                update_l2 = trainable_update_l2(before_update, trainable_tensors)
                optimizer_updates.append(
                    {
                        "step": step + 1,
                        "gradient_l2": grad_l2,
                        "update_l2": update_l2,
                    }
                )
                optimizer.zero_grad(set_to_none=True)
            actual_loss = float(loss.detach().cpu()) * gradient_accumulation_steps
            losses.append(actual_loss)
            write_trace(
                trace,
                {
                    "event": "step",
                    "step": step + 1,
                    "sample_id": sample.id,
                    "task": sample.task,
                    "loss": actual_loss,
                    "optimizer_step": optimizer_step,
                    "gradient_l2": grad_l2,
                    "update_l2": update_l2,
                },
            )

    final_trainable_sha = trainable_state_sha256(trainable_tensors)
    final_trainable_l2 = trainable_l2_norm(trainable_tensors)
    max_update_l2 = max((item["update_l2"] for item in optimizer_updates), default=None)
    loss_delta = losses[0] - losses[-1] if len(losses) >= 2 else None
    model.save_pretrained(output_dir)
    processor.save_pretrained(output_dir)
    write_lora_config(settings, output_dir, kind, rank, alpha, model_id)
    weight_stats = safetensor_weight_stats(output_dir / "adapter_model.safetensors")
    finished_at = datetime.now(UTC)
    wall_seconds = time.perf_counter() - wall_start
    summary_path = output_dir / "training_summary.json"
    proof_path = output_dir / "training_proof.json"
    training_proof = {
        **contract,
        "adapter_kind": kind.value,
        "base_model": model_id,
        "dataset_path": str(dataset_path.resolve()),
        "dataset_sha256": sha256_file(dataset_path),
        "sample_count": len(samples),
        "max_steps": max_steps,
        "max_length": max_length,
        "rank": rank,
        "alpha": alpha,
        "target_modules": target_modules,
        "trainable_params": int(trainable_params),
        "total_params": int(total_params),
        "optimizer": optimizer_name,
        "learning_rate": learning_rate,
        "gradient_accumulation_steps": gradient_accumulation_steps,
        "bf16": bool(torch.cuda.is_available()),
        "environment": environment,
        "initial_trainable_sha256": initial_trainable_sha,
        "final_trainable_sha256": final_trainable_sha,
        "initial_trainable_l2": initial_trainable_l2,
        "final_trainable_l2": final_trainable_l2,
        "optimizer_update_count": len(optimizer_updates),
        "max_optimizer_update_l2": max_update_l2,
        "loss_delta": loss_delta,
        "loss_history": losses,
        "optimizer_updates": optimizer_updates,
        "adapter_weight_sha256": weight_stats["sha256"],
        "adapter_weight_stats": weight_stats,
    }
    write_training_summary(proof_path, training_proof)
    write_training_summary(
        summary_path,
        {
            **contract,
            "adapter_kind": kind.value,
            "base_model": model_id,
            "dataset_path": str(dataset_path.resolve()),
            "dataset_sha256": sha256_file(dataset_path),
            "sample_count": len(samples),
            "max_steps": max_steps,
            "max_length": max_length,
            "rank": rank,
            "alpha": alpha,
            "target_modules": target_modules,
            "trainable_params": int(trainable_params),
            "total_params": int(total_params),
            "optimizer": optimizer_name,
            "learning_rate": learning_rate,
            "gradient_accumulation_steps": gradient_accumulation_steps,
            "bf16": bool(torch.cuda.is_available()),
            "loss_history": losses,
            "final_loss": losses[-1] if losses else None,
            "initial_trainable_sha256": initial_trainable_sha,
            "final_trainable_sha256": final_trainable_sha,
            "initial_trainable_l2": initial_trainable_l2,
            "final_trainable_l2": final_trainable_l2,
            "optimizer_update_count": len(optimizer_updates),
            "max_optimizer_update_l2": max_update_l2,
            "loss_delta": loss_delta,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "wall_seconds": wall_seconds,
            "environment": environment,
            "peak_cuda_memory_mb": cuda_peak_memory_mb(torch),
            "adapter_weight_sha256": weight_stats["sha256"],
            "adapter_weight_stats": weight_stats,
        },
    )
    with trace_path.open("a", encoding="utf-8", newline="\n") as trace:
        write_trace(
            trace,
            {
                "event": "run_finish",
                **contract,
                "finished_at": finished_at.isoformat(),
                "wall_seconds": wall_seconds,
                "final_loss": losses[-1] if losses else None,
                "initial_trainable_sha256": initial_trainable_sha,
                "final_trainable_sha256": final_trainable_sha,
                "optimizer_update_count": len(optimizer_updates),
                "max_optimizer_update_l2": max_update_l2,
                "loss_delta": loss_delta,
                "peak_cuda_memory_mb": cuda_peak_memory_mb(torch),
                "adapter_weight_sha256": weight_stats["sha256"],
            },
        )
    adapter_sha = sha256_tree(output_dir)
    manifest = AdapterManifest(
        adapter_id=adapter_id(kind, dataset_path, model_id),
        kind=kind,
        created_at=datetime.now(UTC),
        proof_version=TRAINING_PROOF_VERSION,
        training_method=TRAINING_METHOD,
        precision=TRAINING_PRECISION,
        framework=TRAINING_FRAMEWORK,
        base_model=model_id,
        dataset_path=str(dataset_path.resolve()),
        dataset_sha256=sha256_file(dataset_path),
        sample_count=len(samples),
        max_steps=max_steps,
        max_length=max_length,
        rank=rank,
        alpha=alpha,
        target_modules=target_modules,
        trainable_params=int(trainable_params),
        total_params=int(total_params),
        optimizer=optimizer_name,
        optimizer_family=optimizer_family(optimizer_name),
        learning_rate=learning_rate,
        gradient_accumulation_steps=gradient_accumulation_steps,
        gradient_checkpointing=gradient_checkpointing,
        gradient_checkpointing_mode=GRADIENT_CHECKPOINTING_MODE if gradient_checkpointing else None,
        autocast_dtype=AUTOCAST_DTYPE,
        bf16=torch.cuda.is_available(),
        unsloth_version=package_version("unsloth"),
        triton_version=package_version("triton-windows") or package_version("triton"),
        xformers_version=package_version("xformers"),
        unsloth_model_type=unsloth_model_type,
        final_loss=losses[-1] if losses else None,
        loss_history=losses,
        initial_trainable_sha256=initial_trainable_sha,
        final_trainable_sha256=final_trainable_sha,
        initial_trainable_l2=initial_trainable_l2,
        final_trainable_l2=final_trainable_l2,
        optimizer_update_count=len(optimizer_updates),
        max_optimizer_update_l2=max_update_l2,
        loss_delta=loss_delta,
        training_proof_path=str(proof_path.resolve()),
        training_proof_sha256=sha256_file(proof_path),
        training_trace_path=str(trace_path.resolve()),
        training_trace_sha256=sha256_file(trace_path),
        training_summary_path=str(summary_path.resolve()),
        training_summary_sha256=sha256_file(summary_path),
        training_started_at=started_at,
        training_finished_at=finished_at,
        training_wall_seconds=wall_seconds,
        training_device=str(environment.get("device_name") or environment.get("device") or ""),
        torch_version=str(environment.get("torch_version") or ""),
        cuda_version=(
            str(environment["torch_cuda_version"])
            if environment.get("torch_cuda_version") is not None
            else None
        ),
        adapter_weight_sha256=str(weight_stats["sha256"] or ""),
        adapter_tensor_count=int(weight_stats["tensor_count"]),
        adapter_lora_tensor_count=int(weight_stats["lora_tensor_count"]),
        adapter_total_elements=int(weight_stats["total_elements"]),
        adapter_nonzero_elements=int(weight_stats["nonzero_elements"]),
        adapter_max_abs=weight_stats["max_abs"],
        adapter_weights_finite=bool(weight_stats["all_finite"]),
        artifacts=relative_artifacts(output_dir),
        sha256=adapter_sha,
        cartridge_id=cartridge_id,
    )
    (output_dir / "adapter_manifest.json").write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return manifest
