"""Behaviour tests for the training modules after the 1630-line file was split."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from elysian import training_datasets, training_lora, training_retrieval
from elysian.config import Settings
from elysian.db import Database
from elysian.schemas import (
    EvidenceAtom,
    Modality,
    SourceRecord,
    TrainingAdapterKind,
    TrustScores,
)
from elysian.training import TrainingService
from elysian.training_common import sha256_bytes
from elysian.training_datasets import (
    atom_id_for_path,
    atoms_for_path,
    latest_cartridge_id,
    model_for_kind,
    validate_dataset,
)
from elysian.training_lora import write_lora_config


def _settings(root: Path) -> Settings:
    return Settings(home=root, model_id="base/model", planner_model_id="planner/model")


def _database(root: Path) -> Database:
    database = Database(_settings(root))
    database.init()
    return database


def _sample(sample_id: str) -> dict[str, Any]:
    return {"id": sample_id, "task": "recall", "inputs": [{"text": "where are the keys"}], "output": {"text": "the drawer"}}


def test_validate_dataset_reads_jsonl_and_names_the_line_that_broke(tmp_path: Path) -> None:
    good = tmp_path / "data.jsonl"
    good.write_text(json.dumps(_sample("a")) + "\n" + json.dumps(_sample("b")) + "\n", encoding="utf-8")
    samples = validate_dataset(good)
    assert [sample.id for sample in samples] == ["a", "b"]

    broken = tmp_path / "broken.jsonl"
    broken.write_text(json.dumps(_sample("a")) + "\nnot json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid training sample at line 2"):
        validate_dataset(broken)

    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Training dataset is empty"):
        validate_dataset(empty)


def test_model_for_kind_uses_the_planner_only_for_the_router(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert model_for_kind(settings, TrainingAdapterKind.hme_router) == "planner/model"
    assert model_for_kind(settings, TrainingAdapterKind.hme_core_lora) == "base/model"


def test_latest_cartridge_id_is_none_until_a_cartridge_is_written(tmp_path: Path) -> None:
    database = _database(tmp_path)
    assert latest_cartridge_id(database) is None
    database.write_cartridge("old", "old", tmp_path / "old", "{}", None, 10, datetime(2026, 1, 1, tzinfo=UTC))
    database.write_cartridge("new", "new", tmp_path / "new", "{}", None, 20, datetime(2026, 3, 1, tzinfo=UTC))
    assert latest_cartridge_id(database) == "new"


def test_atoms_for_path_follows_the_source_and_falls_back_to_a_hash(tmp_path: Path) -> None:
    database = _database(tmp_path)
    paper = tmp_path / "paper.md"
    paper.write_text("the keys are in the drawer", encoding="utf-8")
    other = tmp_path / "other.md"
    database.upsert_sources(
        [
            SourceRecord(source_id=source_id, path=str(path), kind="text", mime="text/markdown", sha256="a", size_bytes=1)
            for source_id, path in (("paper", paper), ("other", other))
        ]
    )
    trust = TrustScores(parser=1.0)
    database.upsert_atoms(
        [
            EvidenceAtom(
                atom_id="paper:text",
                modality=Modality.text,
                source_id="paper",
                source=str(paper),
                text="drawer",
                trust=trust,
            ),
            EvidenceAtom(
                atom_id="other:text",
                modality=Modality.text,
                source_id="other",
                source=str(other),
                text="shelf",
                trust=trust,
            ),
        ]
    )
    assert [atom.atom_id for atom in atoms_for_path(database, paper)] == ["paper:text"]
    expected = f"notes:{sha256_bytes(b'cold')[:12]}"
    assert atom_id_for_path(database, tmp_path / "notes.md", "cold") == expected
    assert atom_id_for_path(database, paper, "cold") == "paper:text"


def test_write_lora_config_ties_weights_only_for_the_mtp_adapter(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    core = write_lora_config(settings, tmp_path / "core", TrainingAdapterKind.hme_core_lora, rank=8, alpha=16)
    payload = json.loads(core.read_text(encoding="utf-8"))
    assert payload["base_model"] == "base/model"
    assert payload["adapter_kind"] == "hme_core_lora"
    assert (payload["rank"], payload["alpha"]) == (8, 16)
    assert payload["ensure_weight_tying"] is False

    mtp = write_lora_config(settings, tmp_path / "mtp", TrainingAdapterKind.hme_visual_mtp, model_id="other/model")
    tied = json.loads(mtp.read_text(encoding="utf-8"))
    assert tied["base_model"] == "other/model"
    assert tied["ensure_weight_tying"] is True


FACADE = {
    "build_prd_dataset": training_datasets,
    "build_visual_dataset": training_datasets,
    "build_router_dataset": training_datasets,
    "build_retrieval_dataset": training_datasets,
    "train_lora": training_lora,
    "train_retrieval_lora": training_retrieval,
}


def test_the_service_facade_passes_every_argument_the_module_expects(tmp_path: Path) -> None:
    data = tmp_path / "data.jsonl"
    data.write_text(json.dumps(_sample("a")) + "\n", encoding="utf-8")
    service = TrainingService(_settings(tmp_path), _database(tmp_path))
    assert [sample.id for sample in service.validate_dataset(data)] == ["a"]
    for name, module in FACADE.items():
        # A bound method has no ``self`` parameter; the module function carries the two injected ones.
        method = list(inspect.signature(getattr(service, name)).parameters)
        function = list(inspect.signature(getattr(module, name)).parameters)[2:]
        assert method == function, name
