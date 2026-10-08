"""Shared fixtures: a model snapshot the fingerprint can read without a 9B download."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest

ROPE: dict[str, Any] = {
    "rope_type": "yarn",
    "factor": 4.0,
    "original_max_position_embeddings": 262_144,
    "mrope_interleaved": True,
    "mrope_section": [11, 11, 10],
}
TEMPLATE = "{% for message in messages %}{{ message['content'] }}{% endfor %}"


def write_model(model_dir: Path, **config_overrides: Any) -> Path:
    config: dict[str, Any] = {
        "model_type": "qwen3_5",
        "max_position_embeddings": 262_144,
        "partial_rotary_factor": 0.25,
        "rope_parameters": dict(ROPE),
        "chat_template": TEMPLATE,
    }
    config.update(config_overrides)
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (model_dir / "tokenizer.json").write_text('{"version": "1.0"}', encoding="utf-8")
    (model_dir / "model.safetensors.index.json").write_text(
        json.dumps({"metadata": {}, "weight_map": {"model-00001.safetensors": "0"}}),
        encoding="utf-8",
    )
    return model_dir


@pytest.fixture
def chat_template() -> str:
    return TEMPLATE


@pytest.fixture
def write_model_fixture() -> Callable[..., Path]:
    return write_model


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    return write_model(tmp_path / "model")


class HashEmbeddings:
    """A stand-in for the embedding model: the same words give the same vector, no download.

    Different words land in different directions, which is all a retrieval test needs; the
    numbers mean nothing to a human, so no test should assert on a score's value.
    """

    def __init__(self, dim: int = 16) -> None:
        self.dim = dim

    def enabled(self) -> bool:
        return True

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        if not texts:
            raise ValueError("encode_texts was asked to encode nothing")
        rows = [
            np.frombuffer(hashlib.sha256(text.encode("utf-8")).digest()[: self.dim], dtype=np.int8).astype(np.float32)
            for text in texts
        ]
        matrix = np.stack(rows)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.where(norms == 0, 1.0, norms)

    def encode_atoms(self, atoms: list[Any]) -> np.ndarray:
        return self.encode_texts([atom.text or "" for atom in atoms])

    def embed_query(self, query: str) -> np.ndarray:
        return self.encode_texts([query])[0]

    def probe_dim(self) -> int:
        return self.dim


@pytest.fixture
def fake_embeddings() -> Callable[[], HashEmbeddings]:
    return HashEmbeddings
