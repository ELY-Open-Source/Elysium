"""Shared verdict helpers for the proof checks.

Kept out of suite.py so the check modules can import them without importing the suite.
"""

from __future__ import annotations

from pathlib import Path

from ..cache_fabric import SEMANTIC_LAYER, CacheFabric
from ..config import Settings
from ..evaluation_schemas import (
    ProofCheck,
)
from .report import (
    write_json,
)

# A fixed puzzle count per hop depth. The old suite re-rolled until the running rate crossed its

HASHHOP_ATTEMPTS = 8

GOLD_ADAPTERS = (
    "HME-Core-LoRA",
    "HME-Vision-LoRA",
    "HME-TTT-VL",
    "HME-Visual-MTP",
    "HME-Router",
    "HME-Retrieval",
)


def _deferred_without_model(
    settings: Settings, artifact: Path, name: str, requirement: str, rerun: str
) -> ProofCheck | None:
    """A check that needs weights proves nothing on a machine that has no weights.

    Calling that a failure would blame the machine; calling it a pass would be a lie. The suite
    records what is missing and the command that runs the check once the weights arrive.
    """
    model_dir = settings.model_dir
    if model_dir is not None and model_dir.exists():
        return None
    write_json(
        artifact,
        {"status": "deferred", "reason": "no local model weights", "model_dir": str(model_dir)},
    )
    return ProofCheck(
        name=name,
        requirement=requirement,
        status="deferred",
        evidence=[str(artifact)],
        detail=f"model_dir={model_dir}",
        reason="the generator or encoder this check measures is not installed on this machine",
        rerun=rerun,
    )


def _semantic_counters(fabric: CacheFabric) -> dict[str, int]:
    """Hit and miss counts for the one cache layer that exists; zero when the layer has no rows."""
    for layer in fabric.statuses():
        if layer.layer == SEMANTIC_LAYER:
            return {"hit": layer.hit_count, "miss": layer.miss_count}
    return {"hit": 0, "miss": 0}

