"""The compatibility header a cartridge carries, and the check that gates a mount.

KV bytes are only valid under the RoPE, quantization and engine settings that produced
them (profiles.py launches YaRN factor 4.0 and llama.cpp --cache-type-k q4_0). A cartridge
mounted under different settings does not fail: it silently attends to wrong positions. So
the manifest carries a fingerprint and the mount compares it field by field.
"""

from __future__ import annotations

import hashlib
import json
from importlib import metadata
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .config import Settings

FORMAT_SEMVER = "1.0.0"
UNKNOWN = ""


class KvFingerprint(BaseModel):
    format_semver: str = FORMAT_SEMVER
    model_id: str = UNKNOWN
    model_hash: str = UNKNOWN
    tokenizer_hash: str = UNKNOWN
    chat_template_hash: str = UNKNOWN
    rope: dict[str, Any] = {}
    context_tokens: int = 0
    kv_dtype: str = UNKNOWN
    engine: str = UNKNOWN
    engine_version: str = UNKNOWN
    adapter_hashes: dict[str, str] = {}


def _read_bytes(path: Path) -> bytes | None:
    if not path.is_file():
        return None
    return path.read_bytes()


def _hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _config_json(model_dir: Path) -> dict[str, Any]:
    data = _read_bytes(model_dir / "config.json")
    if data is None:
        return {}
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as error:
        raise ValueError(f"{model_dir / 'config.json'}: the model config is unreadable ({error})") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"{model_dir / 'config.json'}: expected a JSON object")  # noqa: TRY004  # the file's bytes are wrong, not the caller's argument
    return parsed


def _model_hash(model_dir: Path) -> str:
    config = _read_bytes(model_dir / "config.json")
    if config is None:
        return UNKNOWN
    digest = hashlib.sha256(config)
    index = _read_bytes(model_dir / "model.safetensors.index.json")
    if index is not None:
        digest.update(index)
        return digest.hexdigest()
    for shard in sorted(model_dir.glob("*.safetensors")):
        digest.update(f"{shard.name}:{shard.stat().st_size}".encode())
    return digest.hexdigest()


def _rope(config: dict[str, Any]) -> dict[str, Any]:
    rope: dict[str, Any] = {}
    for key in ("rope_parameters", "rope_scaling"):
        block = config.get(key)
        if isinstance(block, dict):
            rope.update(block)
    for key in ("partial_rotary_factor", "max_position_embeddings", "sliding_window"):
        value = config.get(key)
        if value is not None:
            rope[key] = value
    return rope


def _chat_template_hash(model_dir: Path, config: dict[str, Any]) -> str:
    template = config.get("chat_template")
    if not isinstance(template, str):
        data = _read_bytes(model_dir / "chat_template.json")
        if data is None:
            return UNKNOWN
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as error:
            raise ValueError(f"{model_dir / 'chat_template.json'}: unreadable ({error})") from error
        template = parsed.get("chat_template") if isinstance(parsed, dict) else None
    return _hex(template.encode("utf-8")) if isinstance(template, str) else UNKNOWN


def adapter_hashes(adapter_root: Path) -> dict[str, str]:
    """Hash every adapter weight under a directory, keyed by adapter kind."""
    found: dict[str, str] = {}
    if not adapter_root.is_dir():
        return found
    for weight in sorted(adapter_root.rglob("adapter_model.safetensors")):
        kind = weight.parent.name
        found[kind] = _hex(weight.read_bytes())
    return found


def compute_fingerprint(settings: Settings, adapter_root: Path | None = None) -> KvFingerprint:
    """Read what this machine can prove; unverifiable fields come back empty."""
    engine_version = UNKNOWN
    try:
        engine_version = metadata.version(
            "transformers" if settings.runtime_backend == "transformers" else "sglang"
        )
    except metadata.PackageNotFoundError:
        pass  # an engine that is not installed here is a fact to report, not a crash
    model_dir = settings.model_dir
    config = _config_json(model_dir) if model_dir is not None else {}
    tokenizer = _read_bytes(model_dir / "tokenizer.json") if model_dir is not None else None
    if tokenizer is None and model_dir is not None:
        tokenizer = _read_bytes(model_dir / "tokenizer_config.json")
    return KvFingerprint(
        model_id=settings.model_id,
        model_hash=_model_hash(model_dir) if model_dir is not None else UNKNOWN,
        tokenizer_hash=_hex(tokenizer) if tokenizer is not None else UNKNOWN,
        chat_template_hash=_chat_template_hash(model_dir, config) if model_dir is not None else UNKNOWN,
        rope=_rope(config),
        context_tokens=settings.live_context_tokens,
        kv_dtype=settings.kv_cache_dtype,
        engine=settings.runtime_backend,
        engine_version=engine_version,
        adapter_hashes=adapter_hashes(adapter_root) if adapter_root is not None else {},
    )


def unverifiable_fields(fingerprint: KvFingerprint) -> list[str]:
    """Fields this machine cannot prove; a mount must not wave them through."""
    missing: list[str] = []
    for field in ("model_hash", "tokenizer_hash", "chat_template_hash", "engine_version"):
        if not getattr(fingerprint, field):
            missing.append(field)
    if not fingerprint.rope:
        missing.append("rope")
    return missing


def fingerprint_diff(stored: KvFingerprint, live: KvFingerprint) -> list[str]:
    """Named differences between a cartridge's header and this machine."""
    differences: list[str] = []
    if stored.format_semver != live.format_semver:
        differences.append(
            f"format_semver: cartridge {stored.format_semver} vs this build {live.format_semver}"
        )
    for field in (
        "model_id",
        "model_hash",
        "tokenizer_hash",
        "chat_template_hash",
        "context_tokens",
        "kv_dtype",
        "engine",
        "engine_version",
    ):
        left, right = getattr(stored, field), getattr(live, field)
        if left != right:
            differences.append(f"{field}: cartridge {left!r} vs local {right!r}")
    if stored.rope != live.rope:
        keys = sorted(set(stored.rope) | set(live.rope))
        changes = [
            f"{key}: cartridge {stored.rope.get(key)!r} vs local {live.rope.get(key)!r}"
            for key in keys
            if stored.rope.get(key) != live.rope.get(key)
        ]
        differences.append("rope: " + "; ".join(changes))
    if stored.adapter_hashes != live.adapter_hashes:
        kinds = sorted(set(stored.adapter_hashes) | set(live.adapter_hashes))
        changes = [
            f"{kind}: cartridge {_short(stored.adapter_hashes.get(kind))} vs local "
            f"{_short(live.adapter_hashes.get(kind))}"
            for kind in kinds
            if stored.adapter_hashes.get(kind) != live.adapter_hashes.get(kind)
        ]
        differences.append("adapters: " + "; ".join(changes))
    return differences


def _short(value: str | None) -> str:
    if not value:
        return "absent"
    return value[:12]
