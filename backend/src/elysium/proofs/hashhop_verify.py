"""Judge a HashHop proof: chain, answer, artifacts, pass rate.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..evaluation_schemas import (
    HashHopProof,
)
from .hashhop import HashHopEvaluator


def hashhop_chain_valid(proof: HashHopProof) -> bool:
    chain_artifacts = [Path(path) for path in proof.artifacts if path.endswith(".jsonl")]
    if len(chain_artifacts) != 1 or not chain_artifacts[0].exists():
        return False
    try:
        rows = [
            json.loads(line)
            for line in chain_artifacts[0].read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError):
        return False  # an unreadable chain is not a valid chain, and this is a predicate
    if len(rows) != proof.hops:
        return False
    if rows[0]["from"] != proof.query_id or rows[-1]["to"] != proof.expected_target_id:
        return False
    for index in range(1, len(rows)):
        if rows[index - 1]["to"] != rows[index]["from"]:
            return False
    return all(Path(path).exists() for path in proof.artifacts)


def copy_proof_artifacts(proof: HashHopProof, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    source_roots = {Path(path).parent for path in proof.artifacts}
    for source_root in source_roots:
        if source_root.name == "visual_blocks":
            shutil.copytree(source_root, target / "visual_blocks", dirs_exist_ok=True)
    for artifact in proof.artifacts:
        path = Path(artifact)
        if path.is_file() and path.parent.name != "visual_blocks":
            shutil.copy2(path, target / path.name)
    (target / "proof.json").write_text(proof.model_dump_json(indent=2), encoding="utf-8")


def pass_rate(proofs: list[HashHopProof]) -> float:
    if not proofs:
        return 0.0
    return sum(1 for proof in proofs if proof.passed) / len(proofs)


def collect_model_visual_proofs(
    evaluator: HashHopEvaluator,
    hops: int,
    token_equivalent: int,
    attempts: int,
) -> list[HashHopProof]:
    """Run exactly `attempts` puzzles and keep every verdict.

    The old loop stopped the moment the running pass rate crossed its target, so a model could be
    re-rolled until it passed. A fixed attempt count is what makes the rate mean anything.
    """
    if attempts <= 0:
        raise ValueError(f"collect needs a positive attempt count, got {attempts}")
    return [
        evaluator.generate_model_visual_proof(hops, token_equivalent, max_proofs=5)
        for _ in range(attempts)
    ]
