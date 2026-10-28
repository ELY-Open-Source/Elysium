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
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from bench.metrics import aggregate, score_query
from bench.query_set import Query, holder_index, load_queries, scale_probes
from bench.report import chance_row, meta, write_markdown
from bench.sets_common import MODALITIES, ROOT
from bench.systems import (
    ARMS,
    MODELS,
    ArmRunner,
    Atom,
    JointRunner,
    arm_needs,
    live_product_rankings,
    load_atoms,
)

REPORTS = ROOT / "reports"
DB_HOME = ROOT / "runs" / "baseline"
LIVE_QUERIES = 300  # the acceptance bar names n>=300; the SQL path answers in well under a second
PROGRESS_EVERY = 250  # an arm takes tens of minutes over 5,308 queries; silence looks like a hang
SCALE_SIZES = (500, 2_000, 10_000, 50_000)


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
    scratch: Path | None = None,
) -> dict[str, Any]:
    """Score the unmodified RetrievalService on its own, as its holder would ask it.

    The arms measure retrieval configurations; the acceptance bar is about the product. A query is
    asked as the holder the frozen set assigns it, because a transactive memory is used that way.
    """
    probe = [query for query in queries if query.answerable]
    stride = max(1, len(probe) // live_queries)
    chosen = probe[::stride][:live_queries]
    if not chosen:
        raise SystemExit("live check needs answerable queries")
    rankings, distinct, timings = live_product_rankings(
        DB_HOME,
        [query.text for query in chosen],
        top_k,
        as_holders=[query.holder for query in chosen],
        scratch=scratch,
    )
    overlaps = [
        len(set(fast_rankings[query.query_id]) & set(ranking)) / top_k
        for query, ranking in zip(chosen, rankings, strict=True)
        if fast_rankings.get(query.query_id) is not None
    ]
    if not overlaps:
        raise SystemExit("live check found no fast rankings to compare against")
    scores = [
        score_query(query.query_id, ranking, set(query.gold), query.holder)
        for query, ranking in zip(chosen, rankings, strict=True)
    ]
    metrics: dict[str, Any] = dict(aggregate(scores))
    ordered = sorted(timings)
    metrics.update(
        {
            "queries": len(chosen),
            "top_k": top_k,
            "p50": ordered[len(ordered) // 2],
            "p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
            "mean": sum(ordered) / len(ordered),
            "max": max(ordered),
            "top10_overlap_with_bm25_only": sum(overlaps) / len(overlaps),
            "identical_top10": sum(1 for overlap in overlaps if overlap == 1.0) / len(overlaps),
            "distinct_sources_in_top10": {
                "mean": sum(distinct) / len(distinct),
                "min": min(distinct),
                "max": max(distinct),
            },
        }
    )
    return metrics


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
    parser.add_argument(
        "--live-scratch",
        type=Path,
        default=ROOT / "runs" / "live",
        help="copy the store here before the product path opens it, so the frozen baseline stays frozen",
    )
    parser.add_argument("--no-scale", action="store_true", help="skip the latency/scale curve")
    parser.add_argument(
        "--remeasure-latency",
        type=int,
        default=0,
        help="re-time this many sampled queries with warm models instead of trusting cached per-query seconds",
    )
    parser.add_argument("--out", type=Path, default=REPORTS)
    parser.add_argument(
        "--name",
        default="BASELINE",
        help="report name: writes NAME.md and name.json (BASELINE stays the frozen pre-P0 snapshot)",
    )
    parser.add_argument("--config", type=Path, help="JSON defaults for these flags (bench/configs/ablation.json)")
    args = parser.parse_args()
    if args.config:
        load_config(parser, args, args.config)

    modalities = args.modality or list(MODALITIES)
    # action="extend" appends to the default, so an explicit --arms would otherwise run every arm plus the requested ones.
    arms_requested: list[str] = list(args.arms or ARMS)
    queries = load_queries(modalities)
    if args.limit:
        capped: list[Query] = []
        for modality in modalities:
            picked = [query for query in queries if query.modality == modality][: args.limit]
            capped.extend(picked)
        queries = capped
    atoms = load_atoms(DB_HOME / "data" / "elysium.sqlite")
    holders = holder_index(modalities)
    corpus_sources = len({atom.source_id for atom in atoms})
    print(f"{len(queries)} queries, {len(atoms)} atoms, {corpus_sources} sources", flush=True)

    report: dict[str, Any] = {
        "meta": meta(corpus_sources, queries, args.limit, store=DB_HOME / "data" / "elysium.sqlite"),
        "chance": chance_row(queries, corpus_sources),
    }
    # One pass over the queries: each signal is computed once, every arm derives from it, and each query is checkpointed so a kill costs one query.
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
        report["live_product"] = live_check(
            queries, fast_rankings, live_queries=args.live_queries, scratch=args.live_scratch
        )
    if not args.no_scale:
        report["scale"] = scale_curve(queries, atoms, [arm for arm in arms_requested if arm in ("bm25_only", "dense_only")])

    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.name.lower()
    (args.out / f"{stem}.json").write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    write_markdown(report, args.out / f"{args.name}.md", name=args.name)
    print(f"== wrote {args.out / (stem + '.json')} and {args.out / (args.name + '.md')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
