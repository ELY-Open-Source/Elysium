"""JointRunner must rank exactly like ArmRunner, and the rankings cache must resume.

The ablation switched to a single pass that computes each signal once. If that pass
drifted from the per-arm path, the baseline would silently measure a different system.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench import systems
from bench.run import Query, fingerprint, latency, load_rankings
from bench.systems import ARMS, ArmRunner, Atom, JointRunner
from bench.tests.test_systems import ATOMS

MODEL_ARMS = ["bm25_only", "graph_only", "dense_only", "no_rerank", "fusion_rerank"]


def _queries() -> list[str]:
    return ["alpha report", "beta invoice", "gamma", ""]


@pytest.mark.parametrize("arm", MODEL_ARMS)
def test_joint_ranking_matches_the_per_arm_runner(arm: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(systems, "INDEX_DIR", tmp_path)
    queries = _queries()
    joint = JointRunner([arm], ATOMS, systems.MODELS)
    per_arm = ArmRunner(arm, ATOMS, systems.MODELS)
    for query in queries:
        expected = per_arm.rank(query)
        ranked, seconds = joint.rank_all(query)[arm]
        assert ranked == expected, f"{arm} drifted from the per-arm path on {query!r}"
        assert seconds >= 0.0


def test_joint_runner_computes_the_sparse_signal_once_per_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(systems, "INDEX_DIR", tmp_path)
    joint = JointRunner(["bm25_only", "no_rerank", "fusion_rerank"], ATOMS, systems.MODELS)
    calls = 0
    assert joint._sparse is not None
    original = joint._sparse.scores

    def counting_scores(query: str):
        nonlocal calls
        calls += 1
        return original(query)

    monkeypatch.setattr(joint._sparse, "scores", counting_scores)
    joint.rank_all("alpha report")
    assert calls == 1, "three arms that all need BM25 must still score the corpus once"


def test_joint_runner_rejects_unknown_or_empty_arm_lists() -> None:
    with pytest.raises(SystemExit, match="unknown arm"):
        JointRunner(["vibes"], ATOMS, systems.MODELS)
    with pytest.raises(SystemExit, match="at least one arm"):
        JointRunner([], ATOMS, systems.MODELS)


def test_rankings_cache_resumes_and_refuses_a_mismatched_run(tmp_path: Path) -> None:
    atoms = [Atom(atom_id=f"a{index}", source_id=f"s{index}", text=f"text {index}") for index in range(3)]
    queries = [
        Query(
            query_id=f"q{index}",
            text="t",
            modality="pdf",
            gold=frozenset({"s0"}),
            holder="h",
            answerable=True,
            as_of=None,
        )
        for index in range(2)
    ]
    mark = fingerprint(["bm25_only"], queries, atoms)
    path = tmp_path / "rankings.jsonl"
    assert load_rankings(path, mark) == {}
    rows = [json.dumps({"fingerprint": mark}), json.dumps({"query_id": "q0", "arms": {"bm25_only": {"ranked": ["s0"]}}})]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert load_rankings(path, mark) == {"q0": {"bm25_only": {"ranked": ["s0"]}}}
    with pytest.raises(SystemExit, match="different run"):
        load_rankings(path, "other")
    path.write_text("\n".join([rows[0], "{not json"]) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="not JSON"):
        load_rankings(path, mark)


def test_latency_needs_samples() -> None:
    assert latency([0.5, 1.0])["p50"] == pytest.approx(0.75)
    with pytest.raises(SystemExit, match="no latency samples"):
        latency([])


def test_every_arm_declares_the_signals_it_consumes() -> None:
    assert set(systems.ARM_COMPONENTS) == set(ARMS)
