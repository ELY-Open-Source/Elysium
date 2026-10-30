"""The shared pool keeps every modality and its gold, and a ranking from outside the asker's pool is refused."""

import pytest

from bench.counterpart import load_source_index
from bench.live_check import score
from bench.live_pool import SPEC, chance, draw
from bench.query_set import Query, load_queries


def test_the_pool_draws_every_modality_and_keeps_each_questions_gold() -> None:
    probes, pools = draw(load_queries(), load_source_index())

    assert {query.modality for query in probes} == set(SPEC)
    for query in probes:
        assert query.split == "test"
        assert set(query.gold) <= set(pools[str(query.holder)]), f"{query.query_id} lost its gold from the pool"
    assert draw(load_queries(), load_source_index()) == (probes, pools), "the draw must be the same every run"


def test_chance_is_a_random_ranking_of_the_askers_pool() -> None:
    small = Query("q1", "?", "pdf", frozenset({"a"}), "h1", True, None)
    large = Query("q2", "?", "pdf", frozenset({"b"}), "h2", True, None)
    pools = {"h1": [f"s{n}" for n in range(5)], "h2": [f"t{n}" for n in range(40)]}

    assert chance([small, large], pools) == (1.0 + 10 / 40) / 2


def test_a_source_outside_the_askers_pool_is_refused() -> None:
    query = Query("q1", "?", "pdf", frozenset({"gold"}), "h1", True, None)
    arm = {
        "arm": "mem0",
        "items_written": 1,
        "write": None,
        "query": {"seconds": 1.0, "tokens": {"prompt": 10, "generated": 0}},
        "rankings": {"q1": ["gold"]},
        "latency": [1.0],
    }

    assert score(arm, [query], {"h1": ["gold", "other"]}, {"prompt": 5, "generated": 5})["tokens_per_question"] == 20
    arm["rankings"] = {"q1": ["elsewhere", "gold"]}
    with pytest.raises(SystemExit, match="not in the asker's pool"):
        score(arm, [query], {"h1": ["gold", "other"]}, {"prompt": 0, "generated": 0})
