"""What a longer description is worth: figures and screenshots re-described at the product's 512-token budget.

The DESCRIBE store was written at 192 tokens, which cut most figure and screenshot descriptions
mid-sentence. This harness copies that store, puts each `image` and `ui_screenshot` atom back to
its undescribed words from the store DESCRIBE started from, runs the product's `describe_pictures`
on the copy at the shipped budget, and ranks every split as shipped and, given a served judge,
reranked. Video frames keep their 192-token words: at 512 tokens 60 of 60 sampled frames finished,
median 149. The "before" rows are `bench/reports/rank.json`, the same store before this rewrite.

Run: ELYSIAN_VLM_BASE_URL=http://127.0.0.1:8001/v1 python -m bench.redescribe_check [--rerank-url ...]
Writes: bench/reports/REDESCRIBE.md, bench/reports/redescribe.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from bench.counterpart import load_source_index
from bench.describe_check import (
    DEFAULT_OBJECTS,
    DEFAULT_WORKERS,
    SPLITS,
    describe_copy,
    described_facts,
    floors,
    link_objects,
    rank_stage,
    suites,
)
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
UNDESCRIBED = Path("bench/runs/describe/before")
DEFAULT_SCRATCH = Path("bench/runs/redescribe")
BEFORE = Path("bench/reports/rank.json")
REPORT = Path("bench/reports/REDESCRIBE.md")
PAYLOAD = Path("bench/reports/redescribe.json")
REWRITTEN = ("image", "ui_screenshot")
BUDGET = 512


def undescribe(home: Path, undescribed: Path) -> int:
    """Each rewritten modality's atoms take back the words, trust and metadata they had before any description."""
    from elysian.config import Settings
    from elysian.db import Database
    from elysian.row_codec import row_to_atom

    database = Database(Settings(home=home))
    with database.connect() as connection:
        ids = [
            str(row["atom_id"])
            for row in connection.execute(
                "SELECT atom_id FROM atoms WHERE modality IN (SELECT value FROM json_each(?)) AND image_ref IS NOT NULL AND image_ref != ''",
                (json.dumps(REWRITTEN),),
            )
        ]
    # Read-only: opening the source as a Database would migrate it in place.
    with sqlite3.connect(f"file:{undescribed / 'data' / 'elysian.sqlite'}?mode=ro", uri=True) as source:
        source.row_factory = sqlite3.Row
        rows = source.execute("SELECT * FROM atoms WHERE atom_id IN (SELECT value FROM json_each(?))", (json.dumps(ids),)).fetchall()
    old = {atom.atom_id: atom for atom in map(row_to_atom, rows)}
    missing = [atom_id for atom_id in ids if atom_id not in old]
    if missing:
        raise SystemExit(f"{len(missing)} pictures in {home} are not in {undescribed}, e.g. {missing[0]}; it is not the store DESCRIBE started from")
    if any(atom.metadata.get("caption") for atom in old.values()):
        raise SystemExit(f"{undescribed} already carries descriptions; it cannot give back the undescribed words")
    fields = ("text", "token_equivalent", "trust", "metadata")
    database.upsert_atoms([atom.model_copy(update={name: getattr(old[atom.atom_id], name) for name in fields}) for atom in database.get_atoms(ids)])
    return len(ids)


def measure(home: Path, scratch: Path, workers: int, rerank_url: str | None) -> dict[str, Any]:
    from elysian.config import Settings

    if Settings().vlm_max_new_tokens != BUDGET:
        raise SystemExit(f"the product describes at {Settings().vlm_max_new_tokens} tokens but this report is labelled {BUDGET}")
    groups = suites()
    copy_home, _ = copy_store(home, scratch)
    link_objects(copy_home, DEFAULT_OBJECTS)
    cleared = undescribe(copy_home, UNDESCRIBED)
    restamped = stamp(copy_home / "data" / "elysian.sqlite")
    require_owned(copy_home, "shipped")
    describe = describe_copy(copy_home, workers)
    if describe["described"] != cleared:
        raise SystemExit(f"cleared {cleared} descriptions but {describe['described']} were rewritten")
    facts = described_facts(copy_home)
    if facts["described"] != facts["pictures"]:
        raise SystemExit(f"{facts['pictures'] - facts['described']} pictures are left undescribed")
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
        "rewritten": {"modalities": list(REWRITTEN), "pictures": cleared, "budget": BUDGET, **describe},
        "pictures": facts,
        "before": {"report": str(BEFORE), "commit": before["commit"], "arms": before["arms"]},
        "rerank": None if rerank_url is None else {"url": rerank_url},
        "arms": arms,
    }


def write_markdown(report: dict[str, Any], destination: Path) -> None:
    before = {"arms": [{**row, "stage": f"before {row['stage']}"} for row in report["before"]["arms"]]}
    stages = [("192 tokens", before, "before shipped"), ("512 tokens", report, "shipped")]
    if report["rerank"] is not None:
        stages += [("192 tokens, reranked", before, "before reranked"), ("512 tokens, reranked", report, "reranked")]
    rewritten = report["rewritten"]
    lines = [
        "# Figures and screenshots described at 512 tokens",
        "",
        f"- commit: `{report['commit']}`",
        f"- store measured: a copy of `{report['source_store']}`, holders re-stamped; {rewritten['pictures']} pictures ({', '.join(rewritten['modalities'])}) re-described at {rewritten['budget']} tokens in {rewritten['seconds']:.0f}s by `{rewritten['model_id']}`; video frames keep their 192-token words",
        f"- before: `{report['before']['report']}`, commit `{report['before']['commit']}`",
        f"- machine: {report['machine'].get('cpus')} cpus, load {report['machine'].get('load_average_1_5_15')}",
        "- the external counterpart on the same suite: `bench/reports/BASELINE_EXTERNAL.md`",
        "",
        "| split | n | chance (inside the asker's holder) | " + " | ".join(f"recall@10 {label}" for label, _, _ in stages) + " |",
        "| --- | --- | --- |" + " --- |" * len(stages),
    ]
    for name in SPLITS:
        floor = report["chance"] if name == "whole" else report["chance"][name]
        cells = " | ".join(f"{arm(source, stage, name)['recall_at_10']:.3f}" for _, source, stage in stages)
        lines.append(f"| {name} | {arm(report, 'shipped', name)['queries']} | {floor['recall_at_10_holder_scope']:.4f} | {cells} |")
    lines += ["", "| split | row | MRR | 95% lower |", "| --- | --- | --- | --- |"]
    for name in SPLITS:
        for label, source, stage in [row for row in stages if row[1] is report]:
            cells = arm(source, stage, name)
            lines.append(f"| {name} | {label} | {cells['mrr']:.3f} | {cells['hit_at_10_wilson_lower']:.3f} |")
    for name in SPLITS:
        floor = (report["chance"] if name == "whole" else report["chance"][name])["by_modality"]
        lines += ["", f"## recall@10 by modality, {name}", "", "| row | " + " | ".join(MODALITY_ORDER) + " |", "| --- |" + " --- |" * len(MODALITY_ORDER)]
        lines.append("| chance | " + " | ".join("—" if m not in floor else f"{floor[m]:.4f}" for m in MODALITY_ORDER) + " |")
        for label, source, stage in stages:
            cells = arm(source, stage, name)["by_modality"]
            lines.append(f"| {label} | " + " | ".join("—" if m not in cells else f"{cells[m]:.3f}" for m in MODALITY_ORDER) + " |")
    lines += ["", "Latency moves with machine load and is kept in the JSON only; the recall columns do not.", ""]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="the described store to copy")
    parser.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH, help="where the copy lives")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="description requests in flight")
    parser.add_argument("--rerank-url", default=None, help="a served model's /v1 URL; adds the reranked rows")
    parser.add_argument("--report", type=Path, default=REPORT, help="markdown destination")
    parser.add_argument("--payload", type=Path, default=PAYLOAD, help="json destination")
    arguments = parser.parse_args(argv)
    for destination in (arguments.report, arguments.payload):
        refuse_frozen_overwrite(destination)
    report = measure(arguments.home, arguments.scratch, arguments.workers, arguments.rerank_url)
    arguments.payload.parent.mkdir(parents=True, exist_ok=True)
    arguments.payload.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(report, arguments.report)
    print(f"wrote {arguments.report}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
