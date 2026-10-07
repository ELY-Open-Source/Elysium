"""KV bytes are only valid under the settings that produced them, so the header must say so."""

from __future__ import annotations

import json
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest

from ely_eye.config import Settings
from ely_eye.kv_fingerprint import (
    FORMAT_SEMVER,
    KvFingerprint,
    adapter_hashes,
    compute_fingerprint,
    fingerprint_diff,
    unverifiable_fields,
)


def settings_for(model_dir: Path | None, home: Path, **overrides: Any) -> Settings:
    fields: dict[str, Any] = {"runtime_backend": "transformers", **overrides}
    return Settings(home=home, model_dir=model_dir, **fields)


def test_a_readable_snapshot_leaves_nothing_unverifiable(
    tmp_path: Path, write_model_fixture: Callable[..., Path]
) -> None:
    fingerprint = compute_fingerprint(
        settings_for(write_model_fixture(tmp_path / "model"), tmp_path)
    )
    assert unverifiable_fields(fingerprint) == []
    assert fingerprint.format_semver == FORMAT_SEMVER
    assert fingerprint.rope["factor"] == 4.0
    assert fingerprint.engine_version == metadata.version("transformers")


def test_a_machine_without_the_model_says_what_it_cannot_prove(tmp_path: Path) -> None:
    gaps = unverifiable_fields(compute_fingerprint(settings_for(None, tmp_path)))
    assert gaps == ["model_hash", "tokenizer_hash", "chat_template_hash", "rope"]


def test_an_engine_that_is_not_installed_is_reported_not_guessed(
    tmp_path: Path, write_model_fixture: Callable[..., Path]
) -> None:
    settings = settings_for(
        write_model_fixture(tmp_path / "model"), tmp_path, runtime_backend="sglang"
    )
    assert "engine_version" in unverifiable_fields(compute_fingerprint(settings))


def test_different_weights_change_the_model_hash_and_are_named(
    tmp_path: Path, write_model_fixture: Callable[..., Path]
) -> None:
    model = write_model_fixture(tmp_path / "model")
    before = compute_fingerprint(settings_for(model, tmp_path))
    (model / "model.safetensors.index.json").write_text(
        json.dumps({"metadata": {}, "weight_map": {"model-00002.safetensors": "0"}}),
        encoding="utf-8",
    )
    differences = fingerprint_diff(before, compute_fingerprint(settings_for(model, tmp_path)))
    assert len(differences) == 1
    assert differences[0].startswith("model_hash: cartridge ")


def test_a_rope_change_names_the_field_it_moves(
    tmp_path: Path, write_model_fixture: Callable[..., Path]
) -> None:
    model = write_model_fixture(tmp_path / "model")
    before = compute_fingerprint(settings_for(model, tmp_path))
    write_model_fixture(model, rope_parameters={"rope_type": "yarn", "factor": 2.0})
    differences = fingerprint_diff(before, compute_fingerprint(settings_for(model, tmp_path)))
    rope = [line for line in differences if line.startswith("rope: ")]
    assert len(rope) == 1
    assert "factor: cartridge 4.0 vs local 2.0" in rope[0]
    assert any(line.startswith("model_hash: ") for line in differences)


def test_a_template_in_a_sidecar_file_hashes_the_same(
    tmp_path: Path, write_model_fixture: Callable[..., Path], chat_template: str
) -> None:
    in_config = write_model_fixture(tmp_path / "a")
    sidecar = write_model_fixture(tmp_path / "b", chat_template=None)
    (sidecar / "chat_template.json").write_text(
        json.dumps({"chat_template": chat_template}), encoding="utf-8"
    )
    assert compute_fingerprint(settings_for(in_config, tmp_path)).chat_template_hash == (
        compute_fingerprint(settings_for(sidecar, tmp_path)).chat_template_hash
    )


def test_adapter_weights_are_hashed_by_kind(tmp_path: Path) -> None:
    adapters = tmp_path / "adapters" / "hme-router"
    adapters.mkdir(parents=True)
    (adapters / "adapter_model.safetensors").write_bytes(b"weights-one")
    found = adapter_hashes(tmp_path / "adapters")
    assert list(found) == ["hme-router"]
    (adapters / "adapter_model.safetensors").write_bytes(b"weights-two")
    assert found != adapter_hashes(tmp_path / "adapters")


def test_a_missing_adapter_shows_up_as_absent(
    tmp_path: Path, write_model_fixture: Callable[..., Path]
) -> None:
    adapters = tmp_path / "adapters" / "hme-router"
    adapters.mkdir(parents=True)
    (adapters / "adapter_model.safetensors").write_bytes(b"weights")
    model = write_model_fixture(tmp_path / "model")
    stored = compute_fingerprint(settings_for(model, tmp_path), tmp_path / "adapters")
    live = compute_fingerprint(settings_for(model, tmp_path), tmp_path / "gone")
    differences = fingerprint_diff(stored, live)
    assert len(differences) == 1
    assert differences[0].startswith("adapters: hme-router: cartridge ")
    assert differences[0].endswith("vs local absent")


def test_a_fingerprint_format_change_refuses_the_mount(
    tmp_path: Path, write_model_fixture: Callable[..., Path]
) -> None:
    live = compute_fingerprint(
        settings_for(write_model_fixture(tmp_path / "model"), tmp_path)
    )
    stored = KvFingerprint.model_validate({**live.model_dump(), "format_semver": "0.9.0"})
    assert fingerprint_diff(stored, live) == [
        f"format_semver: cartridge 0.9.0 vs this build {FORMAT_SEMVER}"
    ]


def test_an_unreadable_model_config_fails_loudly(
    tmp_path: Path, write_model_fixture: Callable[..., Path]
) -> None:
    model = write_model_fixture(tmp_path / "model")
    (model / "config.json").write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="the model config is unreadable"):
        compute_fingerprint(settings_for(model, tmp_path))
