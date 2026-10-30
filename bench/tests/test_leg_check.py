"""The leg ablation must stay an ablation: every leg on and off, and a report that says so."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bench import leg_check, leg_report


def test_every_leg_appears_switched_both_ways() -> None:
    dense = {config["dense"] for config in leg_check.CONFIGS}
    visual = {config["visual"] for config in leg_check.CONFIGS}
    assert dense == {True, False}, "the dense leg is only an ablation if both states are scored"
    assert visual == {True, False}, "the picture leg is only an ablation if both states are scored"
    pages = {int(config["top_k"]) for config in leg_check.CONFIGS}
    assert leg_check.SHIPPED_TOP_K in pages, "the page size the product ships must be one of the rows"


def test_the_report_prints_every_arm_with_its_numbers(tmp_path: Path) -> None:
    arm = {
        "label": "words only",
        "top_k": 10,
        "dense": False,
        "visual": False,
        "recall_at_10": 0.832,
        "mrr": 0.683,
        "hit_at_10": 0.833,
        "wilson_lower": 0.787,
        "p50_seconds": 0.0637,
        "p95_seconds": 0.13,
        "median_distinct_sources": 4,
        "by_modality": {"code": 0.953, "pdf": 0.849},
        "modality_counts": {"code": 128, "pdf": 86},
        "newest_gold_first": 0.44,
        "by_category": {"knowledge-update": 1.0, "temporal-reasoning": 0.947},
        "category_counts": {"knowledge-update": 25, "temporal-reasoning": 25},
        "newest_gold_first_by_category": {"knowledge-update": 0.4, "temporal-reasoning": 0.526},
        "newest_gold_first_counts": {"knowledge-update": 19, "temporal-reasoning": 21},
    }
    report: dict[str, Any] = {
        "commit": "abcdef123456",
        "schema_version": 8,
        "source_schema_version": 7,
        "store": "bench/runs/leg_check/data/elysian.sqlite",
        "source_store": "bench/runs/dense_scale",
        "dense_vectors": 153857,
        "picture_index": {"path": "bench/runs/leg_check_index", "atoms": 53668, "dim": 512, "bytes": 109912192},
        "encode_rate": {"pictures": 200, "seconds": 10.0, "per_second": 20.0},
        "queries": 2928,
        "timed_queries": 300,
        "arms": [arm],
        "machine": {
            "system": "Linux",
            "release": "6.18",
            "cpus": 32,
            "threads_per_query": 4,
            "load_average_1_5_15": [1.0, 2.0, 3.0],
        },
    }
    out = tmp_path / "LEGS.md"
    leg_report.write_markdown(report, out)
    text = out.read_text(encoding="utf-8")
    assert "words only" in text
    assert "0.832" in text and "63.7" in text, "recall and latency must sit in the same row"
    assert "code" in text and "0.953" in text, "per-modality recall is where the picture legs show up"
    assert (
        "bench/runs/dense_scale" in text and "153,857 dense vectors" in text
    ), "a dense arm must name the store its vectors came from, not imply the frozen baseline"
    assert (
        "53,668 atoms at 512 dimensions" in text and "44.7" in text
    ), "the picture index needs its shape in the report, and its build cost derived from a measured rate"
    assert (
        "knowledge-update" in text and "1.000" in text and "0.40 (19)" in text
    ), "the two question types the contract names need their own recall and their own n"
    assert (
        "2,928 answerable queries scored whole" in text and "stratified sample of 300" in text
    ), "recall is scored over the whole suite and only latency is sampled, and the report must say so"
    assert "| 0.44 |" in text, "the probe table needs its own newest-first column"
    assert (
        "arrives at v7 and the product migrates it when it opens, so every arm ran on v8" in text
    ), "the schema named in the report has to be the one the product ran on, not the one the copy arrived with"
    assert "unlabelled" not in text, "an unlabelled bucket would hide which set a number came from"
    assert "abcdef123456" in text and "load_average" not in text
