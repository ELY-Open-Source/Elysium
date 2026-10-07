"""Run the retrieval ablation over the frozen corpus and write the baseline report.

Five arms, one database: sparse only, dense only, graph only, the product's weighted
fusion, and fusion plus a cross-encoder reranker. Every number in the report is either
measured or explicitly marked as chance.

Run: python -m bench.run [--arms bm25_only] [--limit 200] [--no-live] [--out bench/reports]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from bench.metrics import aggregate, chance_recall_at_k, score_query
from bench.sets_common import MODALITIES, SETS, read_jsonl, sha256_file
from bench.systems import (
    ARMS,
    DENSE_MODEL,
    MODELS,
    RERANK_MODEL,
    ArmRunner,
    Atom,
    JointRunner,
    arm_needs,
    live_product_rankings,
    load_atoms,
    machine_facts,
)

ROOT = SETS.parent
REPORTS = ROOT / "reports"
DB_HOME = ROOT / "runs" / "baseline"
LIVE_QUERIES = 40  # the product rebuilds BM25 per query, so a live pass costs minutes per query
PROGRESS_EVERY = 250  # an arm takes tens of minutes over 5,308 queries; silence looks like a hang
SCALE_SIZES = (500, 2_000, 10_000, 50_000)
SCALE_PROBES = 40


@dataclass(frozen=True)
class Query:
    query_id: str
    text: str
    modality: str
    gold: frozenset[str]
    holder: str | None
    answerable: bool
    as_of: str | None


def load_queries(modalities: Sequence[str] = MODALITIES) -> list[Query]:
    """Every query the suite froze, in file order."""
    queries: list[Query] = []
    for modality in modalities:
        path = SETS / f"{modality}.jsonl"
        if not path.is_file():
            raise SystemExit(f"{path}: missing set, run python -m bench.build_sets first")
        for record in read_jsonl(path):
            gold = frozenset(hit["source_id"] for hit in record["gold"])
            answerable = not bool(record["unanswerable"])
            if answerable != bool(gold):
                raise SystemExit(
                    f"{path}: {record['query_id']} carries {len(gold)} gold hits but "
                    f"unanswerable={record['unanswerable']}"
                )
            queries.append(
                Query(
                    query_id=record["query_id"],
                    text=record["question"],
                    modality=modality,
                    gold=gold,
                    holder=record["scope"]["holder"],
                    answerable=answerable,
                    as_of=record.get("as_of"),
                )
            )
    if not queries:
        raise SystemExit("no queries loaded")
    return queries


def holder_index(modalities: Sequence[str] = MODALITIES) -> dict[str, str]:
    """source_id -> holder, from the corpus side of the suite."""
    holders: dict[str, str] = {}
    for modality in modalities:
        path = SETS / "corpus" / f"{modality}.jsonl"
        if not path.is_file():
            raise SystemExit(f"{path}: missing corpus index, run python -m bench.build_sets first")
        for record in read_jsonl(path):
            holders[record["source_id"]] = record["holder"]
    return holders


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


def scale_probes(queries: Sequence[Query], count: int = SCALE_PROBES) -> list[Query]:
    """Queries to time at every corpus size.

    Latency does not need gold hits, and a truncated corpus keeps almost none of them,
    so selecting probes by gold would silently drop the small sizes entirely.
    """
    if count <= 0:
        raise SystemExit("the scale curve needs at least one probe query")
    answerable = [query for query in queries if query.answerable]
    if not answerable:
        raise SystemExit("the scale curve needs answerable queries")
    stride = max(1, len(answerable) // count)
    return answerable[::stride][:count]


def scale_curve(queries: Sequence[Query], atoms: Sequence[Atom], arms: Sequence[str]) -> list[dict[str, Any]]:
    """Latency of each arm as the corpus grows, measured on nested source prefixes."""
    sources = sorted({atom.source_id for atom in atoms})
    rows: list[dict[str, Any]] = []
    probes = scale_probes(queries)
    for size in SCALE_SIZES:
        keep = set(sources[:size])
        if not keep:
            raise SystemExit(f"scale size {size} kept no sources")
        subset = [atom for atom in atoms if atom.source_id in keep]
        row: dict[str, Any] = {
            "sources": len(keep),
            "atoms": len(subset),
            "queries": len(probes),
            "note": "latency only: a source prefix drops most gold sources, so recall at these sizes is meaningless",
        }
        for arm in arms:
            if not arm_needs(arm, MODELS):
                continue
            runner = ArmRunner(arm, subset, MODELS)
            for query in probes:
                runner.rank(query.text)
            row[arm] = {"p50": runner.percentile(0.50), "p95": runner.percentile(0.95)}
        rows.append(row)
        print(f"scale {len(keep):6d} sources: " + " ".join(f"{arm}={row[arm]['p50']:.3f}s" for arm in arms if arm in row), flush=True)
    return rows


def live_check(
    queries: Sequence[Query],
    fast_rankings: dict[str, list[str]],
    top_k: int = 10,
    live_queries: int = LIVE_QUERIES,
) -> dict[str, Any]:
    """Compare the unmodified RetrievalService with the fast BM25 path."""
    probe = [query for query in queries if query.answerable]
    stride = max(1, len(probe) // live_queries)
    chosen = probe[::stride][:live_queries]
    if not chosen:
        raise SystemExit("live check needs answerable queries")
    rankings, distinct, timings = live_product_rankings(DB_HOME, [query.text for query in chosen], top_k)
    overlaps = [
        len(set(fast_rankings[query.query_id]) & set(ranking)) / top_k
        for query, ranking in zip(chosen, rankings, strict=True)
        if fast_rankings.get(query.query_id) is not None
    ]
    if not overlaps:
        raise SystemExit("live check found no fast rankings to compare against")
    return {
        "queries": len(chosen),
        "top_k": top_k,
        "p50": sorted(timings)[len(timings) // 2],
        "mean": sum(timings) / len(timings),
        "max": max(timings),
        "top10_overlap_with_bm25_only": sum(overlaps) / len(overlaps),
        "identical_top10": sum(1 for overlap in overlaps if overlap == 1.0) / len(overlaps),
        "distinct_sources_in_top10": {
            "mean": sum(distinct) / len(distinct),
            "min": min(distinct),
            "max": max(distinct),
        },
    }


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True, timeout=30
    )
    commit = result.stdout.strip()
    if len(commit) != 40:
        raise SystemExit(f"git rev-parse HEAD returned {commit!r}, expected a 40 character sha")
    return commit


def meta(corpus_sources: int, queries: Sequence[Query], limit: int | None = None) -> dict[str, Any]:
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


def write_markdown(report: dict[str, Any], path: Path) -> None:
    """Human-readable twin of the JSON report."""
    lines = [
        "# BASELINE: what the product retrieves today",
        "",
        f"- generated {report['meta']['generated_at']} at commit {report['meta']['git_commit'][:12]}",
        (
            f"- corpus {report['meta']['corpus_sources']} sources, {report['meta']['queries']} queries "
            f"({report['meta']['answerable']} answerable)"
        ),
        f"- models: dense `{report['meta']['models']['dense']}`, rerank `{report['meta']['models']['rerank']}`",
        (
            f"- machine: {report['meta']['machine']['cpus']} cores, load average "
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
            "## the unmodified product path",
            "",
            (
                f"- RetrievalService.search: p50 {live['p50']:.2f}s, mean {live['mean']:.2f}s, max {live['max']:.2f}s "
                f"over {live['queries']} queries"
            ),
            (
                f"- top-10 overlap with the fast BM25 path: {live['top10_overlap_with_bm25_only']:.1%}, "
                f"identical order {live['identical_top10']:.1%}"
            ),
            (
                f"- its top-{live['top_k']} atoms cover only "
                f"{live['distinct_sources_in_top10']['mean']:.1f} distinct sources "
                f"(min {live['distinct_sources_in_top10']['min']}): the product ranks atoms and never diversifies, "
                "so ten slots fill with fragments of one document and the overlap with a source-level ranking is near zero"
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


def load_config(parser: argparse.ArgumentParser, args: argparse.Namespace, path: Path) -> None:
    """Fill in whatever the command line left at its default; an explicit flag still wins."""
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"{path}: cannot read the run config ({error})") from error
    if not isinstance(config, dict):
        raise SystemExit(f"{path}: expected a JSON object, got {type(config).__name__}")
    for key, value in config.items():
        if key not in vars(args):
            raise SystemExit(f"{path}: unknown key {key!r}, expected one of {sorted(vars(args))}")
        if getattr(args, key) == parser.get_default(key):
            setattr(args, key, value)
    unknown = [arm for arm in args.arms if arm not in ARMS]
    if unknown:
        raise SystemExit(f"{path}: unknown arm(s) {unknown}, expected one of {list(ARMS)}")


def latency(times: Sequence[float]) -> dict[str, Any]:
    """Latency summary for one arm's per-query wall times."""
    values = np.asarray(times, dtype=np.float64)
    if values.size == 0:
        raise SystemExit("no latency samples recorded for this arm")
    return {
        "queries": int(values.size),
        "mean": float(values.mean()),
        "p50": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)),
        "max": float(values.max()),
    }


def rss_gib() -> float:
    """Resident memory of this process; a nine-hour run needs to show its growth."""
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024 / 1024
    except OSError:
        return 0.0
    return 0.0


def fingerprint(arms: Sequence[str], queries: Sequence[Query], atoms: Sequence[Atom]) -> str:
    """Identity of a rankings cache: the arms, the query set, and the corpus behind them."""
    corpus = hashlib.sha256("\n".join(atom.atom_id for atom in atoms).encode("utf-8")).hexdigest()[:16]
    payload = "\n".join(
        [",".join(arms), ",".join(query.query_id for query in queries), str(len(atoms)), corpus]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_rankings(path: Path, mark: str) -> dict[str, dict[str, Any]]:
    """Read a resumable rankings cache; a header mismatch is an error, not a silent restart."""
    if not path.exists():
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise SystemExit(f"{path}: cannot read the rankings cache ({error})") from error
    rows: dict[str, dict[str, Any]] = {}
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise SystemExit(f"{path}:{index}: not JSON ({error})") from error
        if index == 1:
            if row.get("fingerprint") != mark:
                raise SystemExit(
                    f"{path}: cached rankings belong to a different run, delete the file to start fresh"
                )
            continue
        rows[str(row["query_id"])] = dict(row["arms"])
    return rows


def remeasure_latency(
    arms: list[dict[str, Any]], joint: JointRunner, queries: Sequence[Query], count: int
) -> None:
    """Re-time a stride sample with warm models and replace each arm's latency section.

    Cached per-query seconds are whatever the machine was doing at the time: a run sharing the
    cores with another job, or a harness that paid model loading per query, reported that as
    retrieval latency. Recall stays a full-pass number; only the timing column is re-measured
    here, and the sample size is recorded so the two are never confused.
    """
    sample = scale_probes(queries, count)
    times: dict[str, list[float]] = {arm["arm"]: [] for arm in arms}
    for index, query in enumerate(sample, start=1):
        for name, (_, seconds) in joint.rank_all(query.text).items():
            if name in times:
                times[name].append(seconds)
        if index % PROGRESS_EVERY == 0:
            print(f"   latency {index}/{len(sample)}, rss {rss_gib():.1f} GiB", flush=True)
    for arm in arms:
        measured: dict[str, Any] = latency(times[arm["arm"]])
        measured["note"] = "re-timed on a stride sample with warm models; recall comes from the full pass"
        arm["latency_seconds"] = measured


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arms", nargs="+", choices=ARMS, action="extend", default=None)
    parser.add_argument("--modality", action="append", choices=MODALITIES, default=None)
    parser.add_argument("--limit", type=int, default=None, help="score at most this many queries per modality")
    parser.add_argument("--no-live", action="store_true", help="skip the unmodified RetrievalService path")
    parser.add_argument("--live-queries", type=int, default=LIVE_QUERIES)
    parser.add_argument("--no-scale", action="store_true", help="skip the latency/scale curve")
    parser.add_argument(
        "--remeasure-latency",
        type=int,
        default=0,
        help="re-time this many sampled queries with warm models instead of trusting cached per-query seconds",
    )
    parser.add_argument("--out", type=Path, default=REPORTS)
    parser.add_argument("--config", type=Path, help="JSON defaults for these flags (bench/configs/ablation.json)")
    args = parser.parse_args()
    if args.config:
        load_config(parser, args, args.config)

    modalities = args.modality or list(MODALITIES)
    # action="extend" appends to the default, so an explicit --arms would otherwise
    # run every arm plus the requested ones.
    arms_requested: list[str] = list(args.arms or ARMS)
    queries = load_queries(modalities)
    if args.limit:
        capped: list[Query] = []
        for modality in modalities:
            picked = [query for query in queries if query.modality == modality][: args.limit]
            capped.extend(picked)
        queries = capped
    atoms = load_atoms(DB_HOME / "data" / "ely_eye.sqlite")
    holders = holder_index(modalities)
    corpus_sources = len({atom.source_id for atom in atoms})
    print(f"{len(queries)} queries, {len(atoms)} atoms, {corpus_sources} sources", flush=True)

    report: dict[str, Any] = {
        "meta": meta(corpus_sources, queries, args.limit),
        "chance": chance_row(queries, corpus_sources),
    }
    # One pass over the queries: each signal is computed once and every arm is derived
    # from it, and each query is checkpointed so a kill costs one query, not an arm.
    mark = fingerprint(arms_requested, queries, atoms)
    rankings_path = DB_HOME / "rankings.jsonl"
    done = load_rankings(rankings_path, mark)
    joint = JointRunner(arms_requested, atoms, MODELS)
    resumed = 0
    with rankings_path.open("a", encoding="utf-8") as cache:
        if not done:
            cache.write(f"{json.dumps({'fingerprint': mark})}\n")
        for index, query in enumerate(queries, start=1):
            if query.query_id in done:
                resumed += 1
                continue
            per_arm = joint.rank_all(query.text)
            done[query.query_id] = {
                arm: {"ranked": order, "seconds": seconds} for arm, (order, seconds) in per_arm.items()
            }
            cache.write(f"{json.dumps({'query_id': query.query_id, 'arms': done[query.query_id]})}\n")
            if index % PROGRESS_EVERY == 0:
                cache.flush()
                print(f"   {index}/{len(queries)} queries, rss {rss_gib():.1f} GiB", flush=True)
    if resumed:
        print(f"   resumed {resumed} queries from {rankings_path}", flush=True)

    arms: list[dict[str, Any]] = []
    fast_rankings: dict[str, list[str]] = {}
    for arm in [arm for arm in ARMS if arm in arms_requested]:
        scores = []
        times: list[float] = []
        for query in queries:
            record = done.get(query.query_id)
            if record is None or arm not in record:
                raise SystemExit(f"{rankings_path}: no cached ranking for {query.query_id} arm {arm}")
            times.append(float(record[arm]["seconds"]))
            ranked = [str(source_id) for source_id in record[arm]["ranked"]]
            scores.append(score_query(query.query_id, ranked, set(query.gold), holder=query.holder, holder_of=holders))
            if arm == "bm25_only":
                fast_rankings[query.query_id] = ranked
        summary: dict[str, Any] = {"arm": arm, "overall": aggregate(scores)}
        summary["by_modality"] = {
            modality: aggregate([s for s, q in zip(scores, queries, strict=True) if q.modality == modality])
            for modality in sorted({q.modality for q in queries})
        }
        summary["latency_seconds"] = latency(times)
        arms.append(summary)
        print(
            f"== {arm} recall@10 {summary['overall']['recall_at_10']:.3f} "
            f"hit@10 {summary['overall']['hit_at_10']:.3f} "
            f"(95% lower {summary['overall']['hit_at_10_wilson_lower']:.3f}) "
            f"abstain {summary['overall']['abstention_rate_unanswerable']:.0%} "
            f"p95 {summary['latency_seconds']['p95']:.3f}s",
            flush=True,
        )
    report["arms"] = arms
    if args.remeasure_latency:
        remeasure_latency(arms, joint, queries, args.remeasure_latency)
    # A crash in the live or scale phase should not cost every finished arm.
    (DB_HOME / "partial_report.json").write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    if not args.no_live:
        report["live_product"] = live_check(queries, fast_rankings, live_queries=args.live_queries)
    if not args.no_scale:
        report["scale"] = scale_curve(queries, atoms, [arm for arm in arms_requested if arm in ("bm25_only", "dense_only")])

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "baseline.json").write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    write_markdown(report, args.out / "BASELINE.md")
    print(f"== wrote {args.out / 'baseline.json'} and {args.out / 'BASELINE.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
