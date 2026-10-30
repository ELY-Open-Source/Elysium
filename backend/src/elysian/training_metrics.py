"""Measure what a training run actually changed: trainable weights, gradients, optimizers, environment."""

from __future__ import annotations

import hashlib
import math
import platform
import subprocess
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .schemas import TrainingAdapterKind
from .training_common import (
    AUTOCAST_DTYPE,
    GRADIENT_CHECKPOINTING_MODE,
    TRAINING_FRAMEWORK,
    TRAINING_METHOD,
    TRAINING_PRECISION,
    TRAINING_PROOF_VERSION,
    sha256_file,
)


def infer_lora_targets(model: Any, kind: TrainingAdapterKind) -> list[str]:
    import torch

    core_leafs = {"q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"}
    mlp_leafs = {"gate_proj", "up_proj", "down_proj"}
    found_leafs: set[str] = set()
    exact: set[str] = set()
    for name, module in model.named_modules():
        if not isinstance(module, torch.nn.Linear):
            continue
        leaf = name.rsplit(".", 1)[-1]
        lower = name.lower()
        if kind == TrainingAdapterKind.hme_core_lora and leaf in core_leafs:
            found_leafs.add(leaf)
        elif kind == TrainingAdapterKind.hme_vision_lora and ("visual" in lower or "vision" in lower):
            exact.add(name)
        elif kind == TrainingAdapterKind.hme_ttt_vl and (leaf in mlp_leafs or "visual" in lower):
            exact.add(name if "visual" in lower else leaf)
        elif kind == TrainingAdapterKind.hme_visual_mtp and (
            "mtp" in lower or "draft" in lower or name == "lm_head"
        ):
            exact.add(name)
        elif kind in {TrainingAdapterKind.hme_router, TrainingAdapterKind.hme_retrieval} and leaf in core_leafs:
            found_leafs.add(leaf)
    targets = sorted(exact or found_leafs)
    if not targets:
        for name, module in model.named_modules():
            if isinstance(module, torch.nn.Linear) and not name.endswith("lm_head"):
                targets.append(name.rsplit(".", 1)[-1])
        targets = sorted(set(targets))
    if not targets:
        raise ValueError(f"No LoRA target modules found for {kind.value}")
    return targets

def trainable_named_parameters(model: Any) -> list[tuple[str, Any]]:
    return [(name, param) for name, param in model.named_parameters() if param.requires_grad]

def trainable_state_cpu(named_parameters: list[tuple[str, Any]]) -> dict[str, Any]:
    return {name: param.detach().float().cpu().clone() for name, param in named_parameters}

def trainable_state_sha256(named_parameters: list[tuple[str, Any]]) -> str:
    digest = hashlib.sha256()
    for name, param in named_parameters:
        tensor = param.detach().float().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(tuple(tensor.shape)).encode("utf-8"))
        digest.update(tensor.numpy().tobytes())
    return digest.hexdigest()

def trainable_l2_norm(named_parameters: list[tuple[str, Any]]) -> float:
    total = 0.0
    for _, param in named_parameters:
        tensor = param.detach().float()
        total += float(tensor.square().sum().detach().cpu())
    return math.sqrt(total)

def gradient_l2_norm(named_parameters: list[tuple[str, Any]]) -> float:
    total = 0.0
    for _, param in named_parameters:
        if param.grad is None:
            continue
        grad = param.grad.detach().float()
        total += float(grad.square().sum().detach().cpu())
    return math.sqrt(total)

def trainable_update_l2(before_update: dict[str, Any], named_parameters: list[tuple[str, Any]]) -> float:
    total = 0.0
    for name, param in named_parameters:
        delta = param.detach().float().cpu() - before_update[name]
        total += float(delta.square().sum())
    return math.sqrt(total)

def require_cuda_bf16(torch_module: Any) -> None:
    if not torch_module.cuda.is_available():
        raise RuntimeError("training needs a CUDA device; none is available.")
    bf16_supported = getattr(torch_module.cuda, "is_bf16_supported", lambda: False)
    if not bool(bf16_supported()):
        raise RuntimeError("PRD 12.2 training requires BF16-capable CUDA hardware.")

def activate_unsloth_training() -> None:
    required = {
        "unsloth": package_version("unsloth"),
        "unsloth_zoo": package_version("unsloth_zoo"),
        "triton": package_version("triton-windows") or package_version("triton"),
        "xformers": package_version("xformers"),
    }
    missing = [name for name, installed in required.items() if not installed]
    if missing:
        raise RuntimeError(
            "PRD 12.2 training requires installed Unsloth dependencies: " + ", ".join(missing)
        )
    with bitsandbytes_gaudi_probe_guard():
        __import__("unsloth")

def enable_gradient_checkpointing(model: Any) -> bool:
    if not hasattr(model, "gradient_checkpointing_enable"):
        return False
    try:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    except TypeError:
        model.gradient_checkpointing_enable()
    return True

def model_type_for_proof(model: Any) -> str | None:
    current = model
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        config = getattr(current, "config", None)
        model_type = getattr(config, "model_type", None)
        if isinstance(model_type, str) and model_type:
            return model_type
        current = getattr(current, "model", None)
    return None

def make_optimizer(model: Any, learning_rate: float) -> tuple[Any, str]:
    params = [param for param in model.parameters() if param.requires_grad]
    try:
        with bitsandbytes_gaudi_probe_guard():
            from bitsandbytes.optim.adamw import PagedAdamW8bit
    except Exception as exc:
        raise RuntimeError("PRD 12.2 training requires bitsandbytes PagedAdamW8bit.") from exc
    try:
        return PagedAdamW8bit(params, lr=learning_rate), "paged_adamw_8bit"
    except Exception as exc:
        raise RuntimeError("bitsandbytes PagedAdamW8bit failed to initialize.") from exc

def optimizer_family(optimizer_name: str) -> str:
    if optimizer_name == "paged_adamw_8bit":
        return "8-bit AdamW / paged optimizer"
    return optimizer_name

@contextmanager
def bitsandbytes_gaudi_probe_guard() -> Any:
    original_run = subprocess.run

    def guarded_run(*args: Any, **kwargs: Any) -> Any:
        command = args[0] if args else kwargs.get("args")
        if isinstance(command, str) and "habana-torch-plugin" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        return original_run(*args, **kwargs)

    subprocess.run = guarded_run
    try:
        yield
    finally:
        subprocess.run = original_run

def training_contract(
    *,
    gradient_checkpointing: bool,
    input_require_grads: bool,
    optimizer_name: str,
    unsloth_model_type: str | None,
) -> dict[str, Any]:
    return {
        "proof_version": TRAINING_PROOF_VERSION,
        "training_method": TRAINING_METHOD,
        "precision": TRAINING_PRECISION,
        "framework": TRAINING_FRAMEWORK,
        "optimizer_family": optimizer_family(optimizer_name),
        "gradient_checkpointing": gradient_checkpointing,
        "gradient_checkpointing_mode": GRADIENT_CHECKPOINTING_MODE if gradient_checkpointing else None,
        "input_require_grads": input_require_grads,
        "autocast_dtype": AUTOCAST_DTYPE,
        "unsloth_version": package_version("unsloth"),
        "triton_version": package_version("triton-windows") or package_version("triton"),
        "xformers_version": package_version("xformers"),
        "unsloth_model_type": unsloth_model_type,
    }

def training_environment(torch_module: Any) -> dict[str, Any]:
    cuda_available = bool(torch_module.cuda.is_available())
    device_name = torch_module.cuda.get_device_name(0) if cuda_available else platform.processor()
    capability = torch_module.cuda.get_device_capability(0) if cuda_available else None
    bf16_supported = (
        bool(getattr(torch_module.cuda, "is_bf16_supported", lambda: False)())
        if cuda_available
        else False
    )
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "device": "cuda:0" if cuda_available else "cpu",
        "device_name": device_name,
        "cuda_available": cuda_available,
        "bf16_supported": bf16_supported,
        "cuda_capability": list(capability) if capability else None,
        "torch_version": getattr(torch_module, "__version__", None),
        "torch_cuda_version": getattr(torch_module.version, "cuda", None),
        "transformers_version": package_version("transformers"),
        "peft_version": package_version("peft"),
        "bitsandbytes_version": package_version("bitsandbytes"),
        "unsloth_version": package_version("unsloth"),
        "unsloth_zoo_version": package_version("unsloth_zoo"),
        "triton_version": package_version("triton-windows") or package_version("triton"),
        "xformers_version": package_version("xformers"),
    }

def package_version(package_name: str) -> str | None:
    try:
        return version(package_name)
    except PackageNotFoundError:
        return None

def cuda_peak_memory_mb(torch_module: Any) -> float | None:
    if not torch_module.cuda.is_available():
        return None
    return float(torch_module.cuda.max_memory_allocated() / 1024 / 1024)

def safetensor_weight_stats(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256_file(path) if path.exists() else None,
        "tensor_count": 0,
        "lora_tensor_count": 0,
        "total_elements": 0,
        "nonzero_elements": 0,
        "nonzero_tensor_count": 0,
        "finite_tensor_count": 0,
        "all_finite": False,
        "max_abs": None,
        "mean_abs": None,
        "dtype_counts": {},
        "key_sample": [],
        "valid": False,
    }
    if not path.exists():
        return report

    import torch
    from safetensors import safe_open

    total_abs = 0.0
    max_abs = 0.0
    dtype_counts: dict[str, int] = {}
    with safe_open(path, framework="pt", device="cpu") as handle:
        keys = list(handle.keys())
        report["tensor_count"] = len(keys)
        report["key_sample"] = keys[:12]
        for key in keys:
            tensor = handle.get_tensor(key)
            numel = int(tensor.numel())
            dtype = str(tensor.dtype).replace("torch.", "")
            dtype_counts[dtype] = dtype_counts.get(dtype, 0) + 1
            report["total_elements"] += numel
            if "lora_" in key:
                report["lora_tensor_count"] += 1
            if numel == 0:
                continue
            tensor_float = tensor.detach().float()
            finite = bool(torch.isfinite(tensor_float).all().item())
            if finite:
                report["finite_tensor_count"] += 1
            nonzero = int(torch.count_nonzero(tensor).item())
            report["nonzero_elements"] += nonzero
            if nonzero > 0:
                report["nonzero_tensor_count"] += 1
            abs_tensor = tensor_float.abs()
            tensor_max_abs = float(abs_tensor.max().item())
            max_abs = max(max_abs, tensor_max_abs)
            total_abs += float(abs_tensor.sum().item())

    report["dtype_counts"] = dtype_counts
    report["all_finite"] = (
        report["tensor_count"] > 0 and report["finite_tensor_count"] == report["tensor_count"]
    )
    if int(report["total_elements"]) > 0:
        report["max_abs"] = max_abs
        report["mean_abs"] = total_abs / int(report["total_elements"])
    report["valid"] = (
        report["exists"]
        and int(report["tensor_count"]) > 0
        and int(report["lora_tensor_count"]) > 0
        and int(report["total_elements"]) > 0
        and int(report["nonzero_elements"]) > 0
        and bool(report["all_finite"])
        and report["max_abs"] is not None
        and float(report["max_abs"]) > 0.0
    )
    return report
