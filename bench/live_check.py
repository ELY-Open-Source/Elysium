"""Elysium against real Mem0 on one shared pool: recall@10 against 9B tokens per question.

Three steps, so the external libraries can run in their own environment:
  pool      draw the pool, build and describe Elysium's store, write what the others are given
  elysium   rank the pool's questions through the shipped search, then with the 9B judge
  report    score every arm with the same metric and write LIVE.md, live.json and live_cost.svg
Between `elysium` and `report`, run `bench.live_external` in `.venv-external`.

Cost is 9B tokens (prompt plus generated) per question: what the system spent writing the pool,
divided by the questions asked of it, plus what each question spent. Elysium's writing cost is
describing the pool's pictures; Mem0's is its LLM extraction. Read from vLLM's counters.

Run: ELYSIUM_VLM_BASE_URL=http://127.0.0.1:8001/v1 python -m bench.live_check pool
     python -m bench.live_check elysium --rerank-url http://127.0.0.1:8001/v1
     python -m bench.live_check report
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from bench.leg_check import SHIPPED_TOP_K, _source_ids, rank_all
from bench.live_chart import write_chart
from bench.live_pool import build
from bench.metrics import aggregate, score_query
from bench.query_set import load_queries
from bench.report import git_commit
from bench.systems import machine_facts
from bench.video_audio_check import MODALITY_ORDER, refuse_frozen_overwrite
from bench.vllm_counters import counters, spent

SCRATCH = Path("bench/runs/live")
REPORT = Path("bench/reports/LIVE.md")
PAYLOAD = Path("bench/reports/live.json")
CHART = Path("bench/reports/live_cost.svg")
SYSTEMS = {"elysium": "Elysium", "mem0": "Mem0"}


def probes_of(pool: dict[str, Any]) -> list[Any]:
    wanted = set(pool["probes"])
    found = [query for query in load_queries() if query.query_id in wanted]
    if len(found) != len(wanted):
        raise SystemExit(f"the pool names {len(wanted)} questions but the frozen suite holds {len(found)} of them")
    return found


def elysium_arms(pool: dict[str, Any], rerank_url: str) -> list[dict[str, Any]]:
    """The shipped words search and the same page judged by the 9B, each through the product."""
    from elysium.config import Settings
    from elysium.db import Database
    from elysium.retrieval import RetrievalService

    home = Path(pool["elysium_store"]["home"])
    probes = probes_of(pool)
    arms = []
    for name, url in (("elysium", None), ("elysium + 9B judge", rerank_url)):
        settings = Settings(home=home, dense_embeddings_enabled=False, embedding_model_dir=None, clip_model_dir=None, rerank_base_url=url)
        database = Database(settings)
        service = RetrievalService(settings=settings, database=database)
        before = counters(rerank_url)
        rankings, _, timings = rank_all(service, _source_ids(database), probes, SHIPPED_TOP_K)
        arms.append({
            "arm": name,
            "items_written": None,
            "write": None,
            "query": {"seconds": sum(timings), "tokens": spent(before, counters(rerank_url))},
            "rankings": {query.query_id: ranking for query, ranking in zip(probes, rankings, strict=True)},
            "latency": timings,
        })
        print(f"  {name}: ranked {len(probes)}", flush=True)
    return arms


def score(arm: dict[str, Any], probes: list[Any], pools: dict[str, list[str]], described: dict[str, int]) -> dict[str, Any]:
    """The suite's own metric on each arm's rankings, plus the cost per question; a source from outside the pool is a bug.

    Every arm reads the pictures through the descriptions Elysium's ingest wrote, so their tokens are
    part of every arm's cost; an arm's own write cost is what its library spent on top.
    """
    scores = []
    for query in probes:
        ranked = arm["rankings"].get(query.query_id, [])
        stray = sorted(set(ranked) - set(pools[str(query.holder)]))
        if stray:
            raise SystemExit(f"{arm['arm']} answered {query.query_id} with {stray[0]}, which is not in the asker's pool")
        scores.append(score_query(query.query_id, ranked, set(query.gold), query.holder))
    write = arm["write"]["tokens"] if arm["write"] else {"prompt": 0, "generated": 0}
    asked = len(probes)
    latency = sorted(arm["latency"])
    return {
        "arm": arm["arm"],
        "system": SYSTEMS[arm["arm"].split(" ", 1)[0]],
        "items_written": arm["items_written"],
        "write_seconds": arm["write"]["seconds"] if arm["write"] else 0.0,
        "write_tokens": write,
        "writes_failed": (arm["write"] or {}).get("failed", []),
        "query_tokens": arm["query"]["tokens"],
        "tokens_per_question": (sum(described.values()) + sum(write.values()) + sum(arm["query"]["tokens"].values())) / asked,
        "p50_seconds": latency[len(latency) // 2],
        "p95_seconds": latency[int(0.95 * (len(latency) - 1))],
        "overall": aggregate(scores),
        "by_modality": {
            m: aggregate([s for s, q in zip(scores, probes, strict=True) if q.modality == m])["recall_at_10"]
            for m in MODALITY_ORDER
            if any(q.modality == m for q in probes)
        },
    }


def report(pool: dict[str, Any], arms: list[dict[str, Any]], external: dict[str, Any]) -> dict[str, Any]:
    probes = probes_of(pool)
    rows = [score(arm, probes, pool["pools"], pool["elysium_store"]["tokens"]) for arm in arms]
    for row in rows:
        row.update({key: row["overall"][key] for key in ("recall_at_10", "hit_at_10", "hit_at_10_wilson_lower")})
    per_modality = {m: sum(1 for q in probes if q.modality == m) for m in MODALITY_ORDER}
    return {
        "meta": {"queries": len(probes), "answerable": sum(1 for q in probes if q.answerable), "limit_per_modality": per_modality},
        "commit": git_commit(),
        "machine": machine_facts(),
        "questions": len(probes),
        "by_modality_questions": per_modality,
        "pool": {key: pool[key] for key in ("seed", "spec", "chunk_chars", "sources_without_text")},
        "pool_sources": sum(len(sources) for sources in pool["pools"].values()),
        "items_given": len(pool["items"]),
        "chance": {"recall_at_10": pool["chance_recall_at_10"]},
        "descriptions": {"tokens": pool["elysium_store"]["tokens"], "seconds": pool["elysium_store"]["described"]["seconds"], "pictures": pool["elysium_store"]["described"]["described"]},
        "external_limit": external["limit"],
        "arms": rows,
    }


def write_markdown(payload: dict[str, Any], destination: Path) -> None:
    lines = [
        "# Elysium and Mem0 on one pool",
        "",
        f"- commit: `{payload['commit']}`; machine: {payload['machine'].get('cpus')} cpus, load {payload['machine'].get('load_average_1_5_15')}",
        (
            f"- {payload['questions']} test questions ({', '.join(f'{m} {n}' for m, n in payload['by_modality_questions'].items())}), "
            f"{payload['pool_sources']} sources, {payload['items_given']} items of at most {payload['pool']['chunk_chars']} characters given to Mem0"
        ),
        f"- chance (a random ranking of the asker's pool): recall@10 {payload['chance']['recall_at_10']:.4f}",
        "- LLM for every system: the same local Qwen3.5-9B on vLLM, thinking off; embedder for Mem0: local MiniLM",
        "- cost: 9B tokens per question = (descriptions + the arm's own writing) / questions + tokens spent asking",
        (
            f"- descriptions, shared by every arm: {payload['descriptions']['pictures']} pictures described by Elysium's ingest in "
            f"{payload['descriptions']['seconds']:.0f} s, {payload['descriptions']['tokens']['prompt']:,} + {payload['descriptions']['tokens']['generated']:,} tokens; Mem0 reads the same words"
        ),
        "",
        "- Mem0: `add()` into a Qdrant server with its BM25 hybrid and spaCy entity linking, raw (`infer=False`) and inferred; its rerank is its `llm_reranker` on the 9B",
        "",
        "| arm | recall@10 | hit@10 Wilson lower | MRR | 9B tokens / question | own write tokens (prompt + generated) | writes failed | own write s | p50 s | p95 s |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["arms"]:
        write = row["write_tokens"]
        lines.append(
            f"| {row['arm']} | {row['recall_at_10']:.3f} | {row['hit_at_10_wilson_lower']:.3f} | {row['overall']['mrr']:.3f} | "
            f"{row['tokens_per_question']:,.0f} | {write['prompt']:,} + {write['generated']:,} | {len(row['writes_failed'])} | {row['write_seconds']:.0f} | {row['p50_seconds']:.2f} | {row['p95_seconds']:.2f} |"
        )
    modalities = list(payload["arms"][0]["by_modality"])
    lines += ["", "## recall@10 by modality", "", "| arm | " + " | ".join(modalities) + " |", "| --- |" + " --- |" * len(modalities)]
    for row in payload["arms"]:
        lines.append(f"| {row['arm']} | " + " | ".join(f"{row['by_modality'][m]:.3f}" for m in modalities) + " |")
    failures = [(row["arm"], row["writes_failed"][0]) for row in payload["arms"] if row["writes_failed"]]
    if failures:
        lines += ["", "A failed write is an item the library raised on; the first of each arm:", ""] + [f"- {arm}: `{first}`" for arm, first in failures]
    lines += ["", f"![recall against cost]({CHART.name})", "", "Latency and write seconds move with machine load; one run."]
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=("pool", "elysium", "report"))
    parser.add_argument("--scratch", type=Path, default=SCRATCH)
    parser.add_argument("--vllm", default="http://127.0.0.1:8001/v1")
    parser.add_argument("--rerank-url", default="http://127.0.0.1:8001/v1")
    parser.add_argument("--workers", type=int, default=32)
    arguments = parser.parse_args(argv)
    scratch = arguments.scratch
    if arguments.step == "pool":
        built = build(scratch, arguments.vllm, arguments.workers)
        print(f"pool: {len(built['probes'])} questions, {len(built['items'])} items", flush=True)
        return 0
    pool = json.loads((scratch / "pool.json").read_text(encoding="utf-8"))
    if arguments.step == "elysium":
        (scratch / "elysium.json").write_text(json.dumps({"arms": elysium_arms(pool, arguments.rerank_url)}), encoding="utf-8")
        return 0
    for destination in (REPORT, PAYLOAD, CHART):
        refuse_frozen_overwrite(destination)
    external = json.loads((scratch / "external_mem0.json").read_text(encoding="utf-8"))
    ours = json.loads((scratch / "elysium.json").read_text(encoding="utf-8"))
    payload = report(pool, ours["arms"] + external["arms"], external)
    PAYLOAD.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(payload, REPORT)
    write_chart(payload, CHART)
    print(f"wrote {REPORT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
