"""JointRunner must rank exactly like ArmRunner, and the rankings cache must resume.

The ablation switched to a single pass that computes each signal once. If that pass
drifted from the per-arm path, the baseline would silently measure a different system.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bench import systems
from bench.run import (
    Query,
    fingerprint,
    latency,
    load_rankings,
    remeasure_latency,
    scale_arm_names,
    scale_probes,
    write_markdown,
)
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


def _probe_set(count: int) -> list[Query]:
    return [
        Query(
            query_id=f"q{index}",
            text="t",
            modality="pdf",
            gold=frozenset({f"s{index}"}),
            holder="h",
            answerable=index % 2 == 0,
            as_of=None,
        )
        for index in range(count)
    ]


def test_scale_probes_ignore_gold_so_every_corpus_size_is_measured() -> None:
    queries = _probe_set(100)
    probes = scale_probes(queries, 10)
    assert len(probes) == 10
    assert all(query.answerable for query in probes)
    assert probes == scale_probes(queries, 10), "the curve must be reproducible across runs"
    assert {query.query_id for query in probes} <= {q.query_id for q in queries if q.answerable}
    with pytest.raises(SystemExit, match="at least one probe"):
        scale_probes(queries, 0)
    with pytest.raises(SystemExit, match="needs answerable"):
        scale_probes([], 10)


def _overall() -> dict[str, float]:
    return {
        "recall_at_1": 0.3,
        "recall_at_5": 0.4,
        "recall_at_10": 0.5,
        "ndcg_at_10": 0.42,
        "mrr": 0.4,
        "hit_at_10": 0.52,
        "hit_at_10_wilson_lower": 0.45,
        "abstention_rate_answerable": 0.0,
        "abstention_rate_unanswerable": 0.0,
        "top_hit_from_holder_unanswerable": 0.2,
    }


def _report() -> dict:
    return {
        "meta": {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "git_commit": "a" * 40,
            "corpus_sources": 10,
            "queries": 16,
            "answerable": 8,
            "machine": {"system": "Linux", "release": "x", "cpus": 32, "load_average_1_5_15": [1.0, 2.0, 3.0]},
            "models": {"dense": "d", "rerank": "r"},
        },
        "chance": {"recall_at_1": 0.0, "recall_at_5": 0.0, "recall_at_10": 0.0},
        "arms": [
            {
                "arm": "bm25_only",
                "overall": _overall(),
                "by_modality": {"pdf": _overall()},
                "latency_seconds": {"p50": 0.1, "p95": 0.2},
            }
        ],
        "live_product": {
            "queries": 2,
            "top_k": 10,
            "p50": 1.0,
            "mean": 1.0,
            "max": 1.0,
            "top10_overlap_with_bm25_only": 0.0,
            "identical_top10": 0.0,
            "distinct_sources_in_top10": {"mean": 7.5, "min": 1, "max": 10},
        },
        "scale": [
            {"sources": 500, "atoms": 900, "queries": 4, "note": "latency only", "bm25_only": {"p50": 0.001, "p95": 0.002}}
        ],
    }


def test_the_report_writer_survives_a_scale_note(tmp_path: Path) -> None:
    path = tmp_path / "BASELINE.md"
    write_markdown(_report(), path)
    text = path.read_text(encoding="utf-8")
    assert "| 500 | 900 | 0.001/0.002 |" in text
    assert "_latency only_" in text
    assert "load average 1.0 on 32 cores" in text
    assert "## unanswerable queries (50.0% of the suite)" in text


def test_scale_arm_names_reads_only_latency_dicts() -> None:
    assert scale_arm_names(_report()["scale"]) == ["bm25_only"]
    with pytest.raises(SystemExit, match="no measured arm"):
        scale_arm_names([{"sources": 500, "note": "latency only"}])


def test_remeasure_latency_replaces_cached_seconds_with_a_warm_sample() -> None:
    arms: list[dict[str, Any]] = [{"arm": "bm25_only", "latency_seconds": {"p50": 99.0}}]
    remeasure_latency(arms, JointRunner(["bm25_only"], ATOMS, systems.MODELS), _probe_set(8), 4)
    measured = arms[0]["latency_seconds"]
    assert measured["p50"] < 99.0
    assert measured["queries"] == 4
    assert "warm models" in measured["note"]
