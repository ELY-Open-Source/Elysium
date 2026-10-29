"""The ranking on the described store as shipped, and with the served 9B reranking each page.

`bench/reports/DESCRIBE.md` measured the store once its pictures carry descriptions. Its rows are the
"before" here; this harness ranks a copy of the same described store with the product as it stands,
split dev / test / whole, and, given a served model, again with `rerank_base_url` set so the model
judges each atom of the 24-atom page yes or no and the page is reordered by that judgement. The
rerank was chosen on dev; test and whole are reported, not tuned on.

Run: python -m bench.rank_check [--rerank-url http://127.0.0.1:8001/v1]
Writes: bench/reports/RANK.md, bench/reports/rank.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from bench.counterpart import load_source_index
from bench.describe_check import SPLITS, described_facts, floors, rank_stage, suites
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


def measure(home: Path, scratch: Path, rerank_url: str | None) -> dict[str, Any]:
    groups = suites()
    copy_home, _ = copy_store(home, scratch)
    restamped = stamp(copy_home / "data" / "elysium.sqlite")
    require_owned(copy_home, "shipped")
    facts = described_facts(copy_home)
    if facts["described"] != facts["pictures"]:
        raise SystemExit(f"{facts['pictures'] - facts['described']} pictures in {home} are undescribed; this is not the DESCRIBE store")
    arms = rank_stage(copy_home, groups, "shipped")
    if rerank_url is not None:
        arms += rank_stage(copy_home, groups, "reranked", rerank_url)
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
        "rerank": None if rerank_url is None else {"url": rerank_url},
        "arms": arms,
    }


def write_markdown(report: dict[str, Any], destination: Path) -> None:
    before = {"arms": [{**row, "stage": "before"} for row in report["before"]["arms"]]}
    stages = [("before", before, "before"), ("now", report, "shipped")]
    if report["rerank"] is not None:
        stages.append(("reranked by the 9B", report, "reranked"))
    lines = [
        "# The ranking on the described store",
        "",
        f"- commit: `{report['commit']}`",
        f"- store measured: a copy of `{report['source_store']}`, holders re-stamped; {report['pictures']['described']} of {report['pictures']['pictures']} pictures carry a description",
        f"- before: the `after` rows of `{report['before']['report']}`, commit `{report['before']['commit']}`",
        f"- machine: {report['machine'].get('cpus')} cpus, load {report['machine'].get('load_average_1_5_15')}",
        "- the external counterpart on the same suite: `bench/reports/BASELINE_EXTERNAL.md`",
        "",
        "| split | n | chance (inside the asker's holder) | " + " | ".join(f"recall@10 {label}" for label, _, _ in stages) + " | MRR now | 95% lower now |",
        "| --- | --- | --- |" + " --- |" * len(stages) + " --- | --- |",
    ]
    for name in SPLITS:
        floor = report["chance"] if name == "whole" else report["chance"][name]
        now = arm(report, "shipped", name)
        cells = " | ".join(f"{arm(source, stage, name)['recall_at_10']:.3f}" for _, source, stage in stages)
        lines.append(f"| {name} | {now['queries']} | {floor['recall_at_10_holder_scope']:.4f} | {cells} | {now['mrr']:.3f} | {now['hit_at_10_wilson_lower']:.3f} |")
    if report["rerank"] is not None:
        lines += ["", "| split | MRR reranked | 95% lower reranked |", "| --- | --- | --- |"]
        for name in SPLITS:
            judged = arm(report, "reranked", name)
            lines.append(f"| {name} | {judged['mrr']:.3f} | {judged['hit_at_10_wilson_lower']:.3f} |")
    for name in SPLITS:
        floor = (report["chance"] if name == "whole" else report["chance"][name])["by_modality"]
        lines += ["", f"## recall@10 by modality, {name}", "", "| row | " + " | ".join(MODALITY_ORDER) + " |", "| --- |" + " --- |" * len(MODALITY_ORDER)]
        lines.append("| chance | " + " | ".join("—" if m not in floor else f"{floor[m]:.4f}" for m in MODALITY_ORDER) + " |")
        for label, source, stage in stages:
            cells = arm(source, stage, name)
            lines.append(f"| {label} | " + " | ".join("—" if m not in cells["by_modality"] else f"{cells['by_modality'][m]:.3f}" for m in MODALITY_ORDER) + " |")
    lines += ["", "Latency moves with machine load and is kept in the JSON only; the recall columns do not.", ""]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="the described store to copy")
    parser.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH, help="where the copy lives")
    parser.add_argument("--rerank-url", default=None, help="a served model's /v1 URL; adds the reranked rows")
    parser.add_argument("--report", type=Path, default=REPORT, help="markdown destination")
    parser.add_argument("--payload", type=Path, default=PAYLOAD, help="json destination")
    arguments = parser.parse_args(argv)
    for destination in (arguments.report, arguments.payload):
        refuse_frozen_overwrite(destination)
    report = measure(arguments.home, arguments.scratch, arguments.rerank_url)
    arguments.payload.parent.mkdir(parents=True, exist_ok=True)
    arguments.payload.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(report, arguments.report)
    print(f"wrote {arguments.report}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
