"""Print the curve `COMMON_TERM_FRACTION` was picked from.

A magic number is a claim until something shows the trade-off behind it. This harness asks the
frozen suite the way its holder would, once per candidate bound, and puts recall and latency in
the same row: keeping every word makes the query expensive, dropping too many makes it blind.

Run: python -m bench.term_sweep [--probes 173]
Writes: bench/reports/TERMS.md, bench/reports/term_sweep.json
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from bench.metrics import aggregate, score_query
from bench.query_set import load_queries, scale_probes
from bench.report import git_commit
from bench.run import latency
from bench.scratch import copy_store
from bench.systems import live_product_rankings, machine_facts

FRACTIONS = [0.20, 0.10, 0.05, 0.02, 0.01, 0.005]
TOP_K = 10
DEFAULT_PROBES = 173
DEFAULT_HOME = Path("bench/runs/baseline")
DEFAULT_SCRATCH = Path("bench/runs/term_sweep")


def measure(home: Path, scratch: Path, probes: int) -> dict[str, Any]:
    """Score the shipped search path at each bound, on a copy of the frozen store."""
    from elysium import text_index

    copy_home, copy_seconds = copy_store(home, scratch)
    chosen = scale_probes(load_queries(), probes)
    shipped = text_index.COMMON_TERM_FRACTION
    arms: list[dict[str, Any]] = []
    try:
        for fraction in FRACTIONS:
            text_index.COMMON_TERM_FRACTION = fraction
            rankings, distinct, timings = live_product_rankings(
                copy_home,
                [query.text for query in chosen],
                TOP_K,
                as_holders=[query.holder for query in chosen],
            )
            scores = [
                score_query(query.query_id, ranking, set(query.gold), query.holder)
                for query, ranking in zip(chosen, rankings, strict=True)
            ]
            summary = aggregate(scores)
            timing = latency(timings)
            arms.append(
                {
                    "fraction": fraction,
                    "shipped": fraction == shipped,
                    "recall_at_10": summary["recall_at_10"],
                    "mrr": summary["mrr"],
                    "hit_at_10": summary["hit_at_10"],
                    "p50_seconds": timing["p50"],
                    "p95_seconds": timing["p95"],
                    "median_distinct_sources": statistics.median(distinct),
                }
            )
            print(
                f"fraction {fraction:.3f}: recall@10 {summary['recall_at_10']:.3f}, "
                f"p50 {timing['p50'] * 1000:.1f}ms",
                flush=True,
            )
    finally:
        text_index.COMMON_TERM_FRACTION = shipped

    peak = max(arms, key=lambda arm: arm["recall_at_10"])
    return {
        "commit": git_commit(),
        "store": str(copy_home / "data" / "elysium.sqlite"),
        "copy_seconds": copy_seconds,
        "probes": len(chosen),
        "shipped_fraction": shipped,
        "peak_fraction": peak["fraction"],
        "arms": arms,
        "machine": machine_facts(),
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    machine = report["machine"]
    rows = [
        "| bound | recall@10 | MRR | hit@10 | p50 ms | p95 ms | median distinct sources |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for arm in report["arms"]:
        mark = " **(shipped)**" if arm["shipped"] else ""
        rows.append(
            f"| {arm['fraction']:.3f}{mark} | {arm['recall_at_10']:.3f} | {arm['mrr']:.3f} | "
            f"{arm['hit_at_10']:.3f} | {arm['p50_seconds'] * 1000:.1f} | {arm['p95_seconds'] * 1000:.1f} | "
            f"{arm['median_distinct_sources']} |"
        )
    path.write_text(
        "\n".join(
            [
                "# TERMS: which query words are worth paying for",
                "",
                f"- commit: `{report['commit']}`",
                f"- store: {report['store']} (copied from the frozen baseline in {report['copy_seconds']:.1f}s)",
                (
                    f"- {report['probes']} answerable probes, each asked as the holder the frozen set "
                    f"assigns it, ranked by the unmodified `RetrievalService`"
                ),
                (
                    f"- the bound the product ships is {report['shipped_fraction']}; the measured recall "
                    f"peak sits at {report['peak_fraction']}"
                ),
                (
                    f"- machine: {machine['system']} {machine['release']}, {machine['cpus']} cores, "
                    f"{machine['threads_per_query']} threads per query, load {machine['load_average_1_5_15']}"
                ),
                "",
                *rows,
                "",
                (
                    "The bound is a share of the library: a word carried by more atoms than that is "
                    "dropped from the OR query, because bm25 scores every row the query touches. "
                    "It is relative to the corpus on purpose — a corpus of PDFs and a corpus of shell "
                    "history disagree about which of their own words are noise."
                ),
                "",
                (
                    "_Latency is wall time per search on the machine named above with the thread budget "
                    "the benchmark pins; a run on a loaded machine is not comparable._"
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME)
    parser.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH)
    parser.add_argument("--probes", type=int, default=DEFAULT_PROBES)
    parser.add_argument("--out", type=Path, default=Path("bench/reports/TERMS.md"))
    parser.add_argument("--json-out", type=Path, default=Path("bench/reports/term_sweep.json"))
    args = parser.parse_args()

    report = measure(args.home, args.scratch, args.probes)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(report, args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
