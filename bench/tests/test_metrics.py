"""Hand-computed checks for every metric, so a wrong number cannot hide behind a green run."""

from __future__ import annotations

import pytest

from bench.metrics import (
    aggregate,
    chance_recall_at_k,
    first_hit_rank,
    ndcg_at_10,
    recall_at_k,
    reciprocal_rank,
    score_query,
    wilson_lower_bound,
)


def test_recall_at_k_counts_distinct_gold_in_window() -> None:
    assert recall_at_k(["a", "b", "c", "d"], {"c"}, 1) == 0.0
    assert recall_at_k(["a", "b", "c", "d"], {"c"}, 3) == 1.0
    assert recall_at_k(["c", "x", "a"], {"a", "c"}, 1) == 0.5
    assert recall_at_k(["c", "x", "a"], {"a", "c"}, 3) == 1.0
    assert recall_at_k(["a", "a", "b"], {"a", "b"}, 3) == 1.0  # duplicates count once


def test_recall_is_zero_when_gold_is_empty() -> None:
    assert recall_at_k(["a"], set(), 3) == 0.0


def test_reciprocal_rank_uses_first_hit_only() -> None:
    assert reciprocal_rank(["x", "a", "y", "b"], {"b"}) == 0.25
    assert reciprocal_rank(["x", "a", "y", "b"], {"a", "b"}) == 0.5
    assert reciprocal_rank(["x", "y"], {"z"}) == 0.0
    assert first_hit_rank(["x", "a", "y", "b"], {"b"}) == 4
    assert first_hit_rank(["x", "y"], {"z"}) is None


def test_ndcg_matches_hand_computation() -> None:
    # DCG = 1/log2(2) + 1/log2(4) = 1.5; IDCG = 1/log2(2) + 1/log2(3) = 1.6309297535714574
    assert ndcg_at_10(["a", "x", "b"], {"a", "b"}) == pytest.approx(1.5 / 1.6309297535714574)
    assert ndcg_at_10(["a", "b"], {"a", "b"}) == pytest.approx(1.0)
    assert ndcg_at_10(["x", "y"], {"a"}) == 0.0


def test_ndcg_ignores_results_past_ten() -> None:
    ranked = ["x"] * 10 + ["a"]
    assert ndcg_at_10(ranked, {"a"}) == 0.0


def test_wilson_lower_bound_matches_published_interval() -> None:
    # 90/100 at 95% two-sided is [0.8257, 0.9456] in standard tables.
    assert wilson_lower_bound(90, 100) == pytest.approx(0.8257, abs=1e-3)
    assert wilson_lower_bound(0, 10) == 0.0
    assert wilson_lower_bound(10, 10) == pytest.approx(0.7225, abs=1e-3)
    assert wilson_lower_bound(1, 10) < 0.5


def test_wilson_rejects_impossible_counts() -> None:
    with pytest.raises(SystemExit):
        wilson_lower_bound(5, 0)
    with pytest.raises(SystemExit):
        wilson_lower_bound(11, 10)


def test_chance_recall_is_uniform_baseline() -> None:
    assert chance_recall_at_k(1, 1000, 10) == pytest.approx(0.01)
    assert chance_recall_at_k(4, 100, 10) == pytest.approx(0.1)
    assert chance_recall_at_k(0, 100, 10) == 0.0
    with pytest.raises(SystemExit):
        chance_recall_at_k(1, 0, 10)


def test_score_query_records_holder_and_abstention() -> None:
    holder_of = {"a": "alice", "b": "bob"}
    scored = score_query("q1", ["b"], {"b"}, holder="alice", holder_of=holder_of)
    assert scored.gold == 1
    assert scored.recall_at_1 == 1.0
    assert scored.abstained is False
    assert scored.top_hit_from_holder is False
    assert score_query("q2", [], {"b"}, holder="alice", holder_of=holder_of).abstained is True


def test_aggregate_separates_answerable_from_unanswerable() -> None:
    scores = [
        score_query("hit", ["a", "x", "y"], {"a"}, holder="alice"),
        score_query("miss", ["x", "y", "a"], {"a"}, holder="alice"),
        score_query("none", [], set(), holder="alice"),
    ]
    summary = aggregate(scores)
    assert summary["n_answerable"] == 2
    assert summary["n_unanswerable"] == 1
    assert summary["recall_at_1"] == pytest.approx(0.5)
    assert summary["recall_at_10"] == pytest.approx(1.0)
    assert summary["mrr"] == pytest.approx((1.0 + 1 / 3) / 2)
    assert summary["hit_at_10"] == 1.0
    assert summary["abstention_rate_answerable"] == 0.0
    assert summary["abstention_rate_unanswerable"] == 1.0


def test_aggregate_needs_answerable_queries() -> None:
    with pytest.raises(SystemExit):
        aggregate([score_query("none", [], set())])
