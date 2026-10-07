"""Run the Mem0- and Zep-style counterparts over the frozen sets (b-4), same queries, same metrics.

The point of this runner is an external reference point measured on our own corpus: a flat
memory store with holder scoping and no invalidation (Mem0-style), and the same items with
time-bounded validity (Zep-style). Whatever ely-eye scores, it must beat these two on the
same queries, or the memory story is not real.

Run: python -m bench.run_external            # after bench.ingest_baseline has merged the corpus
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bench.counterpart import (
    Counterpart,
    build_counterparts,
    build_items,
    load_item_atoms,
    load_source_index,
)
from bench.ingest_baseline import RUNS, database_path
from bench.metrics import aggregate, score_query
from bench.run import Query, git_commit, holder_index, load_queries
from bench.sets_common import ROOT
from bench.systems import machine_facts

REPORTS = ROOT / "reports"
TOP_K = 10
HOLDER_SCOPE = "holder scope"
WHOLE_CORPUS_SCOPE = "whole corpus"
SCOPES = (HOLDER_SCOPE, WHOLE_CORPUS_SCOPE)
PROGRESS_EVERY = 500


def score_store(store: Counterpart, queries: list[Query], holder_of: dict[str, str], scope: str) -> dict[str, Any]:
    """Rank every query against one counterpart store and aggregate the same metrics the arms use.

    scope "holder" answers only from the asking holder's memory; scope "whole corpus" hides the
    holder boundary instead, which is the only difference from what the product's arms are shown.
    Without both rows the gain from scoping cannot be told apart from the gain from ranking.
    """
    store.timings.clear()
    scores = []
    for index, query in enumerate(queries, start=1):
        holder = query.holder if scope == HOLDER_SCOPE else None
        ranked = store.search(query.text, holder, query.as_of, TOP_K)
        scores.append(score_query(query.query_id, ranked, set(query.gold), holder=holder, holder_of=holder_of))
        if index % PROGRESS_EVERY == 0:
            print(f"   {store.name} [{scope}] {index}/{len(queries)}", flush=True)
    summary: dict[str, Any] = {
        "store": f"{store.name} [{scope}]",
        "items": len(store.items),
        "closed_items": sum(1 for item in store.items if item.valid_to is not None),
        "overall": aggregate(scores),
        "by_modality": {
            modality: aggregate([s for s, q in zip(scores, queries, strict=True) if q.modality == modality])
            for modality in sorted({q.modality for q in queries})
        },
        "latency_seconds": {
            "queries": len(store.timings),
            "mean": sum(store.timings) / len(store.timings) if store.timings else 0.0,
            "p50": store.percentile(0.50) if store.timings else 0.0,
            "p95": store.percentile(0.95) if store.timings else 0.0,
            "max": max(store.timings) if store.timings else 0.0,
        },
    }
    return summary


def write_markdown(report: dict[str, Any], path: Path) -> None:
    """A table a reader can check: every number carries its n and its 95% lower bound."""
    meta = report["meta"]
    lines = [
        "# BASELINE_EXTERNAL: memory counterparts on the same corpus",
        "",
        f"- generated {meta['generated_at']} at commit {meta['git_commit'][:12]}",
        f"- {meta['queries']} queries ({meta['answerable']} answerable) against {meta['sources']} sources",
        (
            f"- machine: {meta['machine']['cpus']} cores, load average "
            f"{meta['machine']['load_average_1_5_15'][0]:.1f} when the report was written"
        ),
        (
            "- extraction is lexical for both stores; Mem0's real add() and Zep's graph builder call a "
            "generator model, which this round does not have"
        ),
        "",
        (
            "| store | items | closed | recall@10 | hit@10 | hit@10 Wilson 95% lower | MRR | "
            "abstain (answerable) | abstain (unanswerable) | p50 s | p95 s |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for store in report["stores"]:
        overall = store["overall"]
        latency = store["latency_seconds"]
        lines.append(
            f"| {store['store']} | {store['items']} | {store['closed_items']} | {overall['recall_at_10']:.3f} "
            f"| {overall['hit_at_10']:.3f} | {overall['hit_at_10_wilson_lower']:.3f} | {overall['mrr']:.3f} "
            f"| {overall['abstention_rate_answerable']:.3f} | {overall['abstention_rate_unanswerable']:.3f} "
            f"| {latency['p50']:.3f} | {latency['p95']:.3f} |"
        )
    lines += ["", f"n per modality: {json.dumps(meta['queries_by_modality'], sort_keys=True)}", ""]
    lines += [
        "",
        "`[holder scope]` answers only from the asking holder's memory; `[whole corpus]` searches every",
        "holder's memory, which is what the product's arms are shown. The gap between the two rows is the",
        "value of the holder boundary, not of a better ranker.",
        "",
    ]
    for store in report["stores"]:
        lines.append(f"## {store['store']} by modality")
        lines.append("")
        lines.append("| modality | n answerable | recall@10 | hit@10 | Wilson lower | MRR |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for modality, row in sorted(store["by_modality"].items()):
            lines.append(
                f"| {modality} | {row['n_answerable']} | {row['recall_at_10']:.3f} | {row['hit_at_10']:.3f} "
                f"| {row['hit_at_10_wilson_lower']:.3f} | {row['mrr']:.3f} |"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="score at most this many queries per modality (smoke runs)")
    parser.add_argument("--modality", action="append", choices=None)
    parser.add_argument("--out", type=Path, default=REPORTS / "baseline_external.json")
    parser.add_argument("--db", type=Path, default=database_path(RUNS), help="atoms to build items from (smoke runs use a shard)")
    args = parser.parse_args()

    modalities = args.modality or None
    queries = load_queries(modalities) if modalities else load_queries()
    if args.limit:
        kept: list[Query] = []
        for modality in sorted({q.modality for q in queries}):
            kept.extend([q for q in queries if q.modality == modality][: args.limit])
        queries = kept
    if not queries:
        raise SystemExit("no queries selected")

    index = load_source_index()
    atoms = load_item_atoms(args.db)
    items = build_items(atoms, index)
    if not items:
        raise SystemExit("no memory items built; the corpus produced no text")
    print(f"== {len(items)} memory items from {len(atoms)} atoms and {len(index)} indexed sources")

    holder_of = holder_index()
    stores = build_counterparts(items)
    report: dict[str, Any] = {
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_commit": git_commit(),
            "queries": len(queries),
            "answerable": sum(1 for q in queries if q.answerable),
            "limit_per_modality": args.limit,
            "queries_by_modality": {m: sum(1 for q in queries if q.modality == m) for m in sorted({q.modality for q in queries})},
            "sources": len(index),
            "top_k": TOP_K,
            "extraction": "lexical (see bench/counterpart.py); LLM extraction deferred with the generator",
            "machine": machine_facts(),
        },
        "stores": [score_store(store, queries, holder_of, scope) for store in stores for scope in SCOPES],
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    markdown = args.out.with_name("BASELINE_EXTERNAL.md")
    write_markdown(report, markdown)
    for store in report["stores"]:
        overall = store["overall"]
        print(
            f"{store['store']:14s} recall@10 {overall['recall_at_10']:.3f} hit@10 {overall['hit_at_10']:.3f} "
            f"(Wilson lower {overall['hit_at_10_wilson_lower']:.3f}) mrr {overall['mrr']:.3f} "
            f"p50 {store['latency_seconds']['p50']:.3f}s"
        )
    print(f"== wrote {args.out} and {markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
