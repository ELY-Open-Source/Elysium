"""Which adapter the runtime loads, and the reason every other kind does not."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
import torch
from fastapi.testclient import TestClient

from ely_eye import adapters, api
from ely_eye.cartridge_store import set_mounts
from ely_eye.config import Settings
from ely_eye.db import Database
from ely_eye.runtime import QwenRuntime
from ely_eye.schemas import CartridgeManifest, TrainingAdapterKind

CORE = TrainingAdapterKind.hme_core_lora
MODEL = "Qwen/Qwen3.5-9B"


def _manifest(kind: TrainingAdapterKind, base_model: str, adapter_id: str) -> dict[str, Any]:
    return {
        "adapter_id": adapter_id,
        "kind": kind.value,
        "created_at": "2026-05-01T00:00:00+00:00",
        "base_model": base_model,
        "dataset_path": "PRD.md",
        "dataset_sha256": "d" * 64,
        "sample_count": 8,
        "max_steps": 16,
        "max_length": 512,
        "rank": 8,
        "alpha": 16,
        "target_modules": ["q_proj"],
        "trainable_params": 1_000,
        "total_params": 10_000,
        "optimizer": "adamw_8bit",
        "learning_rate": 0.0002,
        "gradient_accumulation_steps": 1,
        "bf16": True,
        "final_loss": 0.01,
        "artifacts": {},
        "sha256": "a" * 64,
    }


def _write_adapter(
    root: Path,
    kind: TrainingAdapterKind = CORE,
    base_model: str = MODEL,
    adapter_id: str = "adapter-1",
    weights: bool = True,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    manifest = _manifest(kind, base_model, adapter_id)
    (root / "adapter_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if weights:
        (root / "adapter_model.safetensors").write_bytes(b"stub weights")
    return root


def _settings(tmp_path: Path) -> Settings:
    settings = Settings(home=tmp_path / "home", model_id=MODEL)
    settings.ensure_dirs()
    return settings


def _cartridge(settings: Settings, database: Database, cartridge_id: str) -> Path:
    root = settings.home / "cartridges" / cartridge_id
    root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    manifest = CartridgeManifest(
        cartridge_id=cartridge_id,
        name="home",
        created_at=now,
        model_base=settings.model_id,
        source_count=0,
        atom_count=0,
        token_equivalent=0,
        artifacts={},
        dna=None,
    )
    database.write_cartridge(cartridge_id, "home", root, manifest.model_dump_json(), None, 0, now)
    set_mounts(database, [cartridge_id], now)
    return root


class _FakeModel:
    def __init__(self) -> None:
        self.evalled = False
        self.device = "cpu"

    def eval(self) -> None:
        self.evalled = True

    def generate(self, **_kwargs: Any) -> torch.Tensor:
        return torch.zeros((1, 8), dtype=torch.long)


class _FakeProcessor:
    def apply_chat_template(self, _messages: Any, **_kwargs: Any) -> str:
        return "prompt"

    def __call__(self, **_kwargs: Any) -> dict[str, torch.Tensor]:
        return {"input_ids": torch.zeros((1, 5), dtype=torch.long)}

    def batch_decode(self, _generated: Any, **_kwargs: Any) -> list[str]:
        return ["three tokens"]


@pytest.fixture(autouse=True)
def _no_stale_loads():
    adapters.clear_loads()
    yield
    adapters.clear_loads()


def test_a_library_adapter_is_selected_for_its_kind(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    chosen = _write_adapter(settings.adapters_dir / "core")
    source, state, reason = adapters.resolve(adapters.library_sources(settings), settings, CORE)
    assert source is not None and source.path == chosen
    assert state == "available"
    assert reason == "selected from the adapter library"


def test_an_adapter_on_another_base_model_is_deferred_naming_both_models(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_adapter(settings.adapters_dir / "router", kind=TrainingAdapterKind.hme_router, base_model="Qwen/Qwen3.5-0.8B")
    source, state, reason = adapters.resolve(adapters.library_sources(settings), settings, TrainingAdapterKind.hme_router)
    assert source is None
    assert state == "deferred"
    assert "trained on Qwen/Qwen3.5-0.8B" in reason and f"runtime holds {MODEL}" in reason


def test_a_manifest_without_weights_is_deferred_naming_the_missing_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_adapter(settings.adapters_dir / "core", weights=False)
    source, state, reason = adapters.resolve(adapters.library_sources(settings), settings, CORE)
    assert source is None and state == "deferred"
    assert "adapter_model.safetensors" in reason


def test_the_mounted_cartridge_copy_wins_over_the_library(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = Database(settings)
    _write_adapter(settings.adapters_dir / "core", adapter_id="library-copy")
    cartridge_root = _cartridge(settings, database, "cart-home")
    cartridge_copy = _write_adapter(cartridge_root / "adapters" / "hme_core_lora", adapter_id="cartridge-copy")
    sources, mounted = adapters.discover(settings, database)
    assert mounted == ["cart-home"]
    source, state, reason = adapters.resolve(sources, settings, CORE)
    assert source is not None and source.path == cartridge_copy
    assert state == "available" and "mounted cartridge cart-home" in reason
    report = adapters.plan(settings, database)
    row = next(item for item in report.adapters if item.kind == CORE)
    assert row.adapter_id == "cartridge-copy" and row.cartridge_id == "cart-home"


def test_the_endpoint_lists_every_kind_with_a_reason(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    _write_adapter(settings.adapters_dir / "core")
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    client = TestClient(api.create_app())
    body = client.get("/api/runtime/adapters").json()
    assert body["model_id"] == MODEL and body["mounted"] == []
    by_kind = {row["kind"]: row for row in body["adapters"]}
    assert set(by_kind) == {kind.value for kind in TrainingAdapterKind}
    assert by_kind[CORE.value]["state"] == "available"
    for kind in TrainingAdapterKind:
        if kind == CORE:
            continue
        assert by_kind[kind.value]["state"] == "missing"
        assert by_kind[kind.value]["reason"], f"{kind.value} carries no reason"


def test_stub_weights_prove_the_load_branch_runs(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    chosen = _write_adapter(settings.adapters_dir / "core")
    attached: list[tuple[Any, Path]] = []

    def fake_attach(model: Any, path: Path) -> _FakeModel:
        attached.append((model, path))
        return _FakeModel()

    monkeypatch.setattr(adapters, "load_into_model", fake_attach)
    monkeypatch.setattr(QwenRuntime, "_load_base_model", lambda self: (_FakeModel(), object()))
    runtime = QwenRuntime(settings)
    model, _processor = runtime._load_transformers()
    assert attached == [(mock.ANY, chosen)], "peft was never asked to attach the stub adapter"
    assert model.evalled is True
    assert [record.adapter_id for record in adapters.load_records()] == ["adapter-1"]
    row = next(item for item in adapters.plan(settings, Database(settings)).adapters if item.kind == CORE)
    assert row.state == "loaded" and "attached to the live model" in row.reason


def test_unload_stops_claiming_a_model_that_is_gone(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    _write_adapter(settings.adapters_dir / "core")
    monkeypatch.setattr(adapters, "load_into_model", lambda model, path: _FakeModel())
    monkeypatch.setattr(QwenRuntime, "_load_base_model", lambda self: (_FakeModel(), object()))
    runtime = QwenRuntime(settings)
    runtime._load_transformers()
    database = Database(settings)
    row = next(item for item in adapters.plan(settings, database).adapters if item.kind == CORE)
    assert row.state == "loaded" and "live model" in row.reason
    other = QwenRuntime(settings)
    assert other._loaded_adapter() is None, "a second instance inherited another instance's claim"
    runtime.unload()
    row = next(item for item in adapters.plan(settings, database).adapters if item.kind == CORE)
    assert row.state == "available"
    assert "that model is gone" in row.reason, row.reason


def test_a_rejected_candidate_does_not_claim_another_adapter_won(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_adapter(settings.adapters_dir / "router", kind=TrainingAdapterKind.hme_router, base_model="Qwen/Qwen3.5-0.8B")
    report = adapters.plan(settings, Database(settings))
    router_rows = [row for row in report.adapters if row.kind == TrainingAdapterKind.hme_router]
    assert len(router_rows) == 1, "a rejected candidate was published as a shadow row"
    assert router_rows[0].state == "deferred" and "trained on Qwen/Qwen3.5-0.8B" in router_rows[0].reason
    assert not any(row.shadowed for row in report.adapters), "nothing won, so nothing may claim a winner"


def test_the_shadow_row_names_the_adapter_that_won(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_adapter(settings.adapters_dir / "first", adapter_id="written_first")
    _write_adapter(settings.adapters_dir / "second", adapter_id="written_second")
    report = adapters.plan(settings, Database(settings))
    losers = [row for row in report.adapters if row.shadowed]
    assert [row.adapter_id for row in losers] == ["written_first"]
    assert losers[0].reason == "shadowed by written_second for the current mount"
    winner = next(row for row in report.adapters if row.adapter_id == "written_second")
    assert winner.shadowed is False and winner.state == "available"


def test_a_cartridge_tagged_adapter_outranks_an_untagged_one(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    tagged = _write_adapter(settings.adapters_dir / "tagged", adapter_id="tagged")
    manifest = json.loads((tagged / "adapter_manifest.json").read_text(encoding="utf-8"))
    manifest["cartridge_id"] = "cart-not-mounted"
    (tagged / "adapter_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _write_adapter(settings.adapters_dir / "plain", adapter_id="plain")
    source, _state, _reason = adapters.resolve(adapters.library_sources(settings), settings, CORE)
    assert source is not None and source.manifest.adapter_id == "tagged"


def test_generation_reports_the_adapter_it_attached(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    chosen = _write_adapter(settings.adapters_dir / "core")
    monkeypatch.setitem(sys.modules, "qwen_vl_utils", SimpleNamespace(process_vision_info=lambda _messages: ([], None)))
    monkeypatch.setattr(adapters, "load_into_model", lambda model, path: _FakeModel())
    monkeypatch.setattr(QwenRuntime, "_load_base_model", lambda self: (_FakeModel(), _FakeProcessor()))
    generation = QwenRuntime(settings).generate_prompt("what does the cartridge hold?")
    assert generation.adapter_path == str(chosen)
    assert generation.adapter_kind == CORE.value and generation.adapter_id == "adapter-1"
    assert generation.adapter_sha256 == "a" * 64
    assert generation.output_tokens == 3 and generation.text == "three tokens"


def test_an_unreadable_manifest_names_the_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    broken = settings.adapters_dir / "broken"
    broken.mkdir(parents=True)
    (broken / "adapter_manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="the adapter manifest is not a valid AdapterManifest"):
        adapters.library_sources(settings)


def test_a_pinned_adapter_dir_without_a_manifest_says_the_path_is_missing(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path / "home", model_id=MODEL, adapter_dir=tmp_path / "empty")
    settings.ensure_dirs()
    assert adapters.library_sources(settings) == []
    available, detail = QwenRuntime(settings)._transformers_status()
    assert available is False
    assert detail == f"Configured adapter path is missing: {tmp_path / 'empty'}"
