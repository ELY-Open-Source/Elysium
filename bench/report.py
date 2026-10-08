"""The report the ablation leaves behind: metadata, the chance floor, and the markdown table."""

from __future__ import annotations

import json
import platform
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bench.metrics import chance_recall_at_k
from bench.query_set import Query
from bench.sets_common import MODALITIES, ROOT, SETS, sha256_file
from bench.systems import DENSE_MODEL, RERANK_MODEL, machine_facts


def chance_row(queries: Sequence[Query], corpus_sources: int) -> dict[str, float]:
    """What a random ranking would score on the same queries."""
    answerable = [query for query in queries if query.answerable]
    if not answerable:
        raise SystemExit("chance needs answerable queries")
    return {
        "corpus_sources": corpus_sources,
        "recall_at_1": sum(chance_recall_at_k(len(query.gold), corpus_sources, 1) for query in answerable) / len(answerable),
        "recall_at_5": sum(chance_recall_at_k(len(query.gold), corpus_sources, 5) for query in answerable) / len(answerable),
        "recall_at_10": sum(chance_recall_at_k(len(query.gold), corpus_sources, 10) for query in answerable) / len(answerable),
    }



def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True, timeout=30
    )
    commit = result.stdout.strip()
    if len(commit) != 40:
        raise SystemExit(f"git rev-parse HEAD returned {commit!r}, expected a 40 character sha")
    return commit



def store_schema_version(store: Path) -> int:
    """The schema the measured store actually carries, read from the file."""
    import sqlite3

    if not store.exists():
        raise SystemExit(f"{store}: the measured store is missing")
    connection = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
    try:
        row = connection.execute("PRAGMA user_version").fetchone()
    finally:
        connection.close()
    return int(row[0])



def meta(
    corpus_sources: int, queries: Sequence[Query], limit: int | None = None, store: Path | None = None
) -> dict[str, Any]:
    manifest_path = SETS / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"{manifest_path}: cannot read the frozen set manifest: {error}") from error
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "python": platform.python_version(),
        "machine": machine_facts(),
        "corpus_manifest_sha256": manifest.get("corpus_manifest_sha256"),
        "sets": {name: sha256_file(SETS / f"{name}.jsonl") for name in MODALITIES},
        "queries": len(queries),
        "answerable": sum(1 for query in queries if query.answerable),
        "limit_per_modality": limit,
        "corpus_sources": corpus_sources,
        "store_schema_version_at_start": None if store is None else store_schema_version(store),
        "models": {"dense": DENSE_MODEL, "rerank": RERANK_MODEL},
    }



def scale_arm_names(rows: Sequence[dict[str, Any]]) -> list[str]:
    """Arms a scale row reports: only keys whose value is a latency dict, in order.

    A scale row also carries strings (the note explaining what the row means), and
    treating those as arms is how the report writer first crashed.
    """
    names: list[str] = []
    for row in rows:
        for name, value in row.items():
            if isinstance(value, dict) and name not in names:
                names.append(name)
    if not names:
        raise SystemExit("scale rows report no measured arm")
    return names



def write_markdown(report: dict[str, Any], path: Path, name: str = "BASELINE") -> None:
    """Human-readable twin of the JSON report."""
    schema = report["meta"].get("store_schema_version_at_start")
    lines = [
        f"# {name}: what the product retrieves at this build",
        "",
        f"- generated {report['meta']['generated_at']} at commit {report['meta']['git_commit'][:12]}",
        ("" if schema is None else f"- measured store schema: v{schema}"),
        (
            f"- corpus {report['meta']['corpus_sources']} sources, {report['meta']['queries']} queries "
            f"({report['meta']['answerable']} answerable)"
        ),
        f"- models: dense `{report['meta']['models']['dense']}`, rerank `{report['meta']['models']['rerank']}`",
        (
            f"- machine: {report['meta']['machine']['cpus']} cores, "
            f"{report['meta']['machine']['threads_per_query']} threads per query, load average "
            f"{report['meta']['machine']['load_average_1_5_15'][0]:.1f} when the report was written"
        ),
        "",
        "| arm | recall@1 | recall@5 | recall@10 | nDCG@10 | MRR | hit@10 (95% lower) | p50 s | p95 s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    chance = report["chance"]
    lines.append(
        f"| chance (random ranking) | {chance['recall_at_1']:.3f} | {chance['recall_at_5']:.3f} "
        f"| {chance['recall_at_10']:.3f} | - | - | - | - | - |"
    )
    if note := next((arm["latency_seconds"].get("note") for arm in report["arms"] if arm["latency_seconds"].get("note")), None):
        lines += ["", f"_{note} (n={report['arms'][0]['latency_seconds']['queries']} queries)_"]
    for arm in report["arms"]:
        overall = arm["overall"]
        latency = arm["latency_seconds"]
        lines.append(
            f"| {arm['arm']} | {overall['recall_at_1']:.3f} | {overall['recall_at_5']:.3f} "
            f"| {overall['recall_at_10']:.3f} | {overall['ndcg_at_10']:.3f} | {overall['mrr']:.3f} "
            f"| {overall['hit_at_10']:.3f} ({overall['hit_at_10_wilson_lower']:.3f}) "
            f"| {latency['p50']:.3f} | {latency['p95']:.3f} |"
        )
    shown = [modality for modality in MODALITIES if any(modality in arm["by_modality"] for arm in report["arms"])]
    if not shown:
        raise SystemExit("no per-modality scores to write")
    lines += ["", "## recall@10 by modality", "", "| arm | " + " | ".join(shown) + " |", "|---|" + "---|" * len(shown)]
    for arm in report["arms"]:
        cells = [
            f"{arm['by_modality'][modality]['recall_at_10']:.3f}" if modality in arm["by_modality"] else "-"
            for modality in shown
        ]
        lines.append(f"| {arm['arm']} | " + " | ".join(cells) + " |")
    total = report["meta"]["queries"]
    if total <= 0:
        raise SystemExit("the report records no queries")
    share = 1 - report["meta"]["answerable"] / total
    lines += ["", f"## unanswerable queries ({share:.1%} of the suite)", ""]
    for arm in report["arms"]:
        overall = arm["overall"]
        lines.append(
            f"- {arm['arm']}: abstains on {overall['abstention_rate_unanswerable']:.0%} of unanswerable queries, "
            f"and its top hit comes from the query's own holder for {overall['top_hit_from_holder_unanswerable']:.0%} of them; "
            "the rest are confident answers pulled out of somebody else's memory"
        )
    if "live_product" in report:
        live = report["live_product"]
        lines += [
            "",
            "## the product path, asked as its holder",
            "",
            (
                f"- RetrievalService.search as the query's own holder: recall@10 {live['recall_at_10']:.3f}, "
                f"MRR {live['mrr']:.3f}, hit@10 {live['hit_at_10']:.3f} (95% lower {live['hit_at_10_wilson_lower']:.3f}) "
                f"over n={live['queries']} answerable queries"
            ),
            (
                f"- latency p50 {live['p50']:.3f}s, p95 {live['p95']:.3f}s, mean {live['mean']:.3f}s, "
                f"max {live['max']:.3f}s"
            ),
            (
                f"- top-10 overlap with the fast BM25 path: {live['top10_overlap_with_bm25_only']:.1%}, "
                f"identical order {live['identical_top10']:.1%}"
            ),
            (
                f"- its top-{live['top_k']} atoms cover "
                f"{live['distinct_sources_in_top10']['mean']:.1f} distinct sources on average "
                f"(min {live['distinct_sources_in_top10']['min']}): the product ranks atoms and never diversifies, "
                "so ten slots can fill with fragments of one document"
            ),
        ]
    if report.get("scale"):
        measured = scale_arm_names(report["scale"])
        header = " | ".join(f"{arm} p50/p95 s" for arm in measured)
        lines += ["", "## latency vs corpus size", "", f"| sources | atoms | {header} |", "|" + "---|" * (2 + len(measured))]
        for row in report["scale"]:
            cells = [f"{row[arm]['p50']:.3f}/{row[arm]['p95']:.3f}" for arm in measured]
            lines.append(f"| {row['sources']} | {row['atoms']} | " + " | ".join(cells) + " |")
        note = report["scale"][0].get("note")
        if note:
            lines += ["", f"_{note}_"]
        load = report["meta"]["machine"]["load_average_1_5_15"][0]
        lines.append(
            f"\n_latency was measured at load average {load:.1f} on {report['meta']['machine']['cpus']} cores; "
            "a busy machine inflates these figures, so read them as a ceiling_"
        )
    lines += [
        "",
        "## reading",
        "",
        "- recall counts a source as found only when it is the source a third party marked correct.",
        "- abstention is the only honest number for unanswerable queries: a retriever that always",
        "  returns ten results never says it does not know.",
        "- chance is the floor any of these arms must beat; a number near chance is not a capability.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
