"""Who gets timed: the probe sample must cover the suite it claims to measure."""

from __future__ import annotations

from collections import Counter

import pytest

from bench.query_set import Query, load_queries, scale_probes


def _suite(sizes: dict[str, int]) -> list[Query]:
    queries: list[Query] = []
    for modality, size in sizes.items():
        queries.extend(
            Query(
                query_id=f"{modality}-{index}",
                text="t",
                modality=modality,
                gold=frozenset({f"{modality}-s{index}"}),
                holder="h",
                answerable=True,
                as_of=None,
            )
            for index in range(size)
        )
    return queries


SIZES = {"code": 1237, "pdf": 766, "ui_screenshot": 320, "image": 240, "video": 215, "conversation": 150}


def test_a_probe_sample_covers_every_modality_it_claims_to_measure() -> None:
    probes = scale_probes(_suite(SIZES), 300)
    mix = Counter(query.modality for query in probes)
    assert len(probes) == 300
    assert set(mix) == set(SIZES), f"a modality missing from the sample is unmeasured: {dict(mix)}"
    assert mix["code"] > mix["conversation"], "the sample should still lean toward the big modalities"
    assert probes == scale_probes(_suite(SIZES), 300), "the curve must be reproducible across runs"


def test_the_frozen_sample_holds_a_conversation_query() -> None:
    """The suite's smallest modality is the one a plain stride over file order used to drop."""
    mix = Counter(query.modality for query in scale_probes(load_queries(), 300))
    assert set(mix) == set(SIZES), f"the frozen sample is missing {sorted(set(SIZES) - set(mix))}: {dict(mix)}"


def test_a_sample_smaller_than_the_modality_count_drops_the_smallest_pools() -> None:
    mix = Counter(query.modality for query in scale_probes(_suite(SIZES), 2))
    assert set(mix) == {"code", "pdf"}
    assert sum(mix.values()) == 2


def test_a_query_carries_the_category_its_set_recorded() -> None:
    """LongMemEval labels each question's kind; the acceptance measurement groups by it."""
    assert {query.category for query in load_queries(["conversation"])} == {
        "knowledge-update",
        "multi-session",
        "single-session-assistant",
        "single-session-preference",
        "single-session-user",
        "temporal-reasoning",
    }
    assert {query.category for query in load_queries(["pdf"])} == {None}, "a set without types stays ungrouped"


def test_an_unanswerable_query_is_never_timed() -> None:
    queries = [
        Query(
            query_id=f"q{index}",
            text="t",
            modality="pdf",
            gold=frozenset() if index % 2 else frozenset({f"s{index}"}),
            holder="h",
            answerable=index % 2 == 0,
            as_of=None,
        )
        for index in range(20)
    ]
    probes = scale_probes(queries, 4)
    assert len(probes) == 4 and all(query.answerable for query in probes)
    with pytest.raises(SystemExit, match="needs answerable"):
        scale_probes([query for query in queries if not query.answerable], 4)
