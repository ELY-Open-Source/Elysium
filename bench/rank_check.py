"""The ranking on the described store as shipped, and on dev what a 9B relevance judge would do to it.

`bench/reports/DESCRIBE.md` measured the store once its pictures carry descriptions. Its rows are the
"before" here; this harness ranks a copy of the same described store with the product as it stands,
split dev / test / whole, and on dev alone can ask the served 9B to judge each of the first 40 atoms
yes or no and reorder them by that judgement. Anything decided is decided on dev.

Run: python -m bench.rank_check [--judge-url http://127.0.0.1:8001/v1]
Writes: bench/reports/RANK.md, bench/reports/rank.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from bench.counterpart import load_source_index
from bench.describe_check import SPLITS, described_facts, floors, rank_stage, suites
from bench.leg_check import _source_ids
from bench.metrics import aggregate, score_query
from bench.query_set import load_queries
from bench.report import git_commit
from bench.scratch import copy_store
from bench.stamp_holders import stamp
from bench.systems import machine_facts
from bench.video_audio_check import (
    MODALITY_ORDER,
    arm,
    refuse_frozen_overwrite,
    require_owned,
)

DEFAULT_HOME = Path("bench/runs/describe/after")
DEFAULT_SCRATCH = Path("bench/runs/rank")
BEFORE = Path("bench/reports/describe.json")
REPORT = Path("bench/reports/RANK.md")
PAYLOAD = Path("bench/reports/rank.json")
JUDGE_WINDOW = 40
JUDGE_CHARS = 2000
JUDGE_WORKERS = 64
JUDGE_SYSTEM = (
    'Judge whether the Document meets the requirements based on the Query and the Instruct provided. '
    'Note that the answer can only be "yes" or "no".'
)
JUDGE_INSTRUCT = "Given a search query, judge whether this stored memory is the one the query is looking for"


def judge(client: httpx.Client, url: str, model: str, query: str, text: str) -> float:
    """P(yes) over yes+no for one candidate, every spelling of each summed; a reply with neither is an error."""
    body = {
        "model": model,
        "max_tokens": 1,
        "temperature": 0,
        "logprobs": True,
        "top_logprobs": 10,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": f"<Instruct>: {JUDGE_INSTRUCT}\n<Query>: {query}\n<Document>: {text[:JUDGE_CHARS]}"},
        ],
    }
    response = client.post(f"{url}/chat/completions", json=body)
    response.raise_for_status()
    top = response.json()["choices"][0]["logprobs"]["content"][0]["top_logprobs"]
    # "yes", " yes" and "Yes" are separate tokens for one answer; their chances add, none overwrites another.
    odds: dict[str, float] = {}
    for entry in top:
        word = entry["token"].strip().lower()
        odds[word] = odds.get(word, 0.0) + math.exp(entry["logprob"])
    yes, no = odds.get("yes", 0.0), odds.get("no", 0.0)
    if yes + no == 0.0:
        raise SystemExit(f"the judge answered neither yes nor no for {query!r}: {[entry['token'] for entry in top]}")
    return yes / (yes + no)


def judge_arm(home: Path, queries: list[Any], url: str) -> dict[str, Any]:
    """The first JUDGE_WINDOW atoms of each search, reordered by the judge, then scored by source."""
    from elysium.config import Settings
    from elysium.db import Database
    from elysium.retrieval import RetrievalService
    from elysium.schemas import SearchFilters

    settings = Settings(home=home, dense_embeddings_enabled=False, embedding_model_dir=None, clip_model_dir=None)
    database = Database(settings)
    service = RetrievalService(settings=settings, database=database)
    ids = _source_ids(database)
    scores, by_modality = [], {}
    with httpx.Client(timeout=300.0) as client, ThreadPoolExecutor(JUDGE_WORKERS) as pool:
        for index, query in enumerate(queries):
            hits = service.search(query.text, top_k=JUDGE_WINDOW, filters=SearchFilters(as_holder=query.holder)).hits
            texts = [hit.atom.text or "" for hit in hits]
            verdicts = list(pool.map(judge, [client] * len(texts), [url] * len(texts), [settings.model_id] * len(texts), [query.text] * len(texts), texts))
            order = sorted(range(len(hits)), key=lambda position: (-verdicts[position], position))
            ranking: list[str] = []
            for position in order:
                source = ids[hits[position].atom.source_id]
                if source not in ranking:
                    ranking.append(source)
            score = score_query(query.query_id, ranking, set(query.gold), query.holder)
            scores.append(score)
            by_modality.setdefault(query.modality, []).append(score.recall_at_10)
            if (index + 1) % 100 == 0:
                print(f"    judged {index + 1}/{len(queries)}", flush=True)
    summary = aggregate(scores)
    row = {
        "queries": len(queries),
        "top_k": JUDGE_WINDOW,
        "recall_at_10": summary["recall_at_10"],
        "mrr": summary["mrr"],
        "hit_at_10": summary["hit_at_10"],
        "hit_at_10_wilson_lower": summary["hit_at_10_wilson_lower"],
        "by_modality": {name: sum(rows) / len(rows) for name, rows in sorted(by_modality.items())},
    }
    print(f"  judge dev: recall@10 {row['recall_at_10']:.3f} over {row['queries']}", flush=True)
    return {"arm": "judge: dev", "stage": "judge", "asked": "dev", "overall": row}


def measure(home: Path, scratch: Path, judge_url: str | None) -> dict[str, Any]:
    groups = suites()
    copy_home, _ = copy_store(home, scratch)
    restamped = stamp(copy_home / "data" / "elysium.sqlite")
    require_owned(copy_home, "shipped")
    facts = described_facts(copy_home)
    if facts["described"] != facts["pictures"]:
        raise SystemExit(f"{facts['pictures'] - facts['described']} pictures in {home} are undescribed; this is not the DESCRIBE store")
    arms = rank_stage(copy_home, groups, "shipped")
    if judge_url is not None:
        arms.append(judge_arm(copy_home, groups["dev"], judge_url))
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    index = load_source_index()
    return {
        "meta": {"queries": len(load_queries()), "answerable": len(groups["whole"]), "limit_per_modality": None},
        "chance": {**floors(index, groups["whole"]), **{name: floors(index, groups[name]) for name in ("dev", "test")}},
        "commit": git_commit(),
        "machine": machine_facts(),
        "source_store": str(home),
        "holders_restamped": restamped,
        "pictures": facts,
        "before": {"report": str(BEFORE), "commit": before["commit"], "arms": [row for row in before["arms"] if row["stage"] == "after"]},
        "judge": None if judge_url is None else {"url": judge_url, "window": JUDGE_WINDOW, "chars": JUDGE_CHARS},
        "arms": arms,
    }


def write_markdown(report: dict[str, Any], destination: Path) -> None:
    before = {"arms": [{**row, "stage": "before"} for row in report["before"]["arms"]]}
    lines = [
        "# The ranking on the described store",
        "",
        f"- commit: `{report['commit']}`",
        f"- store measured: a copy of `{report['source_store']}`, holders re-stamped; {report['pictures']['described']} of {report['pictures']['pictures']} pictures carry a description",
        f"- before: the `after` rows of `{report['before']['report']}`, commit `{report['before']['commit']}`",
        f"- machine: {report['machine'].get('cpus')} cpus, load {report['machine'].get('load_average_1_5_15')}",
        "- the external counterpart on the same suite: `bench/reports/BASELINE_EXTERNAL.md`",
        "",
        "| split | n | chance (inside the asker's holder) | recall@10 before | recall@10 now | MRR now | 95% lower now |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name in SPLITS:
        floor = report["chance"] if name == "whole" else report["chance"][name]
        old, now = arm(before, "before", name), arm(report, "shipped", name)
        lines.append(
            f"| {name} | {now['queries']} | {floor['recall_at_10_holder_scope']:.4f} | {old['recall_at_10']:.3f} | "
            f"{now['recall_at_10']:.3f} | {now['mrr']:.3f} | {now['hit_at_10_wilson_lower']:.3f} |"
        )
    for name in SPLITS:
        floor = (report["chance"] if name == "whole" else report["chance"][name])["by_modality"]
        lines += ["", f"## recall@10 by modality, {name}", "", "| row | " + " | ".join(MODALITY_ORDER) + " |", "| --- |" + " --- |" * len(MODALITY_ORDER)]
        lines.append("| chance | " + " | ".join("—" if m not in floor else f"{floor[m]:.4f}" for m in MODALITY_ORDER) + " |")
        rows = [("before", arm(before, "before", name)), ("now", arm(report, "shipped", name))]
        if name == "dev" and report["judge"] is not None:
            rows.append((f"9B judge over the first {report['judge']['window']} atoms", arm(report, "judge", "dev")))
        for label, cells in rows:
            lines.append(f"| {label} | " + " | ".join("—" if m not in cells["by_modality"] else f"{cells['by_modality'][m]:.3f}" for m in MODALITY_ORDER) + " |")
    if report["judge"] is not None:
        judged = arm(report, "judge", "dev")
        lines += ["", f"The judge on dev: recall@10 {judged['recall_at_10']:.3f} against {arm(report, 'shipped', 'dev')['recall_at_10']:.3f} as shipped, MRR {judged['mrr']:.3f}."]
    lines += ["", "Latency moves with machine load and is kept in the JSON only; the recall columns do not.", ""]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="the described store to copy")
    parser.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH, help="where the copy lives")
    parser.add_argument("--judge-url", default=None, help="a served model's /v1 URL; adds the dev judge arm")
    parser.add_argument("--report", type=Path, default=REPORT, help="markdown destination")
    parser.add_argument("--payload", type=Path, default=PAYLOAD, help="json destination")
    arguments = parser.parse_args(argv)
    for destination in (arguments.report, arguments.payload):
        refuse_frozen_overwrite(destination)
    report = measure(arguments.home, arguments.scratch, arguments.judge_url)
    arguments.payload.parent.mkdir(parents=True, exist_ok=True)
    arguments.payload.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(report, arguments.report)
    print(f"wrote {arguments.report}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
