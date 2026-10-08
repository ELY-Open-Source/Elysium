"""The leg ablation must stay an ablation: every leg on and off, and a report that says so."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bench import leg_check


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
    }
    report: dict[str, Any] = {
        "commit": "abcdef123456",
        "schema_version": 8,
        "store": "bench/runs/leg_check/data/ely_eye.sqlite",
        "probes": 300,
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
    leg_check.write_markdown(report, out)
    text = out.read_text(encoding="utf-8")
    assert "words only" in text
    assert "0.832" in text and "63.7" in text, "recall and latency must sit in the same row"
    assert "code" in text and "0.953" in text, "per-modality recall is where the picture legs show up"
    assert "abcdef123456" in text and "load_average" not in text
