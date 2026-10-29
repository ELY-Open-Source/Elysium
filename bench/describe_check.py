"""What describing the pictures is worth: the same store and queries, with a served VLM's words added.

The frozen stores hold OCR text only, so a screenshot question about an icon, a video question
about what is on screen, and a chart question about a colour have nothing to match. This harness
copies the speech store, re-stamps its holders from the frozen corpus index, ranks every
answerable query, runs the product's `describe_pictures` on the copy, and ranks again. Rows are
split dev / test / whole: anything tuned is tuned on dev, and the bar is read on test.

Run: ELYSIUM_VLM_BASE_URL=http://127.0.0.1:8001/v1 python -m bench.describe_check
Writes: bench/reports/DESCRIBE.md, bench/reports/describe.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from bench.counterpart import load_source_index
from bench.query_set import load_queries
from bench.report import git_commit
from bench.run_external import chance_rows
from bench.scratch import copy_store
from bench.stamp_holders import stamp
from bench.systems import machine_facts
from bench.video_audio_check import (
    MODALITY_ORDER,
    SHIPPED_TOP_K,
    arm,
    rank_arm,
    refuse_frozen_overwrite,
    require_owned,
)

DEFAULT_HOME = Path("bench/runs/video_audio_speech")
DEFAULT_SCRATCH = Path("bench/runs/describe")
DEFAULT_OBJECTS = Path("bench/runs/baseline/objects")
DEFAULT_WORKERS = 32
SPLITS = ("dev", "test", "whole")
REPORT = Path("bench/reports/DESCRIBE.md")
PAYLOAD = Path("bench/reports/describe.json")


def suites() -> dict[str, list[Any]]:
    """Every answerable query, and the dev and test halves the frozen set recorded."""
    answerable = [query for query in load_queries() if query.gold]
    if not answerable:
        raise SystemExit("the frozen suite carries no answerable query; nothing to score")
    split = {name: [query for query in answerable if query.split == name] for name in ("dev", "test")}
    for name, queries in split.items():
        if not queries:
            raise SystemExit(f"no answerable query is marked {name}; the split this harness reports would be empty")
    return {**split, "whole": answerable}


def floors(index: dict[str, Any], queries: list[Any]) -> dict[str, Any]:
    """A random ranking inside each asker's holder, for the split and for each modality in it."""
    return {
        **chance_rows(index, queries),
        "by_modality": {
            name: chance_rows(index, [query for query in queries if query.modality == name])["recall_at_10_holder_scope"]
            for name in MODALITY_ORDER
            if any(query.modality == name for query in queries)
        },
    }


def described_facts(store: Path) -> dict[str, int]:
    """How many pictures carry a model's description, read without opening the store for write."""
    import sqlite3

    with sqlite3.connect(f"file:{store / 'data' / 'elysium.sqlite'}?mode=ro", uri=True) as connection:
        pictures, described = connection.execute(
            "SELECT count(*), coalesce(sum(json_extract(metadata_json, '$.caption') = 'vlm'), 0) FROM atoms "
            "WHERE modality IN ('image', 'ui_screenshot', 'video_frame') AND image_ref IS NOT NULL AND image_ref != ''"
        ).fetchone()
    return {"pictures": int(pictures), "described": int(described)}


def describe_copy(home: Path, workers: int) -> dict[str, Any]:
    """Run the product's backfill on the copy, timed; a served model is required, not assumed."""
    from elysium.config import Settings
    from elysium.db import Database
    from elysium.describe import describe_pictures

    settings = Settings(home=home)
    if settings.vlm_base_url is None:
        raise SystemExit("ELYSIUM_VLM_BASE_URL is not set; start scripts/launch-vllm-live.sh and point it at /v1")
    began = time.perf_counter()
    counts = describe_pictures(settings, Database(settings), workers)
    return {**counts, "seconds": time.perf_counter() - began, "vlm_base_url": settings.vlm_base_url, "model_id": settings.model_id}


def rank_stage(home: Path, groups: dict[str, list[Any]], stage: str, rerank_url: str | None = None) -> list[dict[str, Any]]:
    """One row per split, each ranked through the shipped words-only path, reranked when a judge is served."""
    rows = []
    for name in SPLITS:
        row = rank_arm(home, groups[name], SHIPPED_TOP_K, rerank_url)
        if row is None:
            raise SystemExit(f"{stage}/{name}: nothing to rank, so this run would print a row of zeros")
        rows.append({"arm": f"{stage}: {name}", "stage": stage, "asked": name, "overall": row})
        print(f"  {stage} {name}: recall@10 {row['recall_at_10']:.3f} over {row['queries']}", flush=True)
    return rows


def link_objects(store: Path, objects: Path) -> None:
    """A copy carries the database only; its pictures are read from the content-addressed objects the corpus was ingested into."""
    if not (objects / "images").is_dir():
        raise SystemExit(f"{objects}: no ingested pictures here; pass --objects pointing at the store's objects directory")
    link = store / "objects"
    if link.is_symlink() and link.resolve() == objects.resolve():
        return
    if link.exists() or link.is_symlink():
        raise SystemExit(f"{link} already exists and is not a link to {objects}; remove it or pass another --scratch")
    link.symlink_to(objects.resolve())


def measure(home: Path, scratch: Path, workers: int, described_home: Path | None, objects: Path) -> dict[str, Any]:
    """Score dev, test and the whole suite before and after the pictures are described."""
    groups = suites()
    before_home, _ = copy_store(home, scratch / "before")
    restamped = stamp(before_home / "data" / "elysium.sqlite")
    require_owned(before_home, "before")
    if described_facts(before_home)["described"]:
        raise SystemExit(f"{home} already carries described pictures; the before row would not be a before")
    before = rank_stage(before_home, groups, "before")

    source = home if described_home is None else described_home
    after_home, _ = copy_store(source, scratch / "after")
    link_objects(after_home, objects)
    stamp(after_home / "data" / "elysium.sqlite")
    require_owned(after_home, "after")
    describe = describe_copy(after_home, workers) if described_home is None else {"reused": str(described_home)}
    facts = described_facts(after_home)
    if facts["described"] != facts["pictures"]:
        raise SystemExit(f"{facts['pictures'] - facts['described']} pictures in {after_home} are still undescribed")
    after = rank_stage(after_home, groups, "after")

    index = load_source_index()
    return {
        "meta": {"queries": len(load_queries()), "answerable": len(groups["whole"]), "limit_per_modality": None},
        "chance": {**floors(index, groups["whole"]), **{name: floors(index, groups[name]) for name in ("dev", "test")}},
        "commit": git_commit(),
        "machine": machine_facts(),
        "source_store": str(home),
        "holders_restamped": restamped,
        "describe": describe,
        "pictures": facts,
        "arms": before + after,
    }


def write_markdown(report: dict[str, Any], destination: Path) -> None:
    """Dev, test and whole, before and after, each beside its own chance floor."""
    describe = report["describe"]
    how = (
        f"reused `{describe['reused']}`"
        if "reused" in describe
        else f"{describe['described']} pictures in {describe['seconds']:.0f}s by `{describe['model_id']}` at {describe['vlm_base_url']}"
    )
    lines = [
        "# What describing the pictures is worth",
        "",
        f"- commit: `{report['commit']}`",
        f"- store measured: a copy of `{report['source_store']}`, holders re-stamped from the frozen corpus index; the source is never opened for write",
        f"- machine: {report['machine'].get('cpus')} cpus, load {report['machine'].get('load_average_1_5_15')}",
        f"- descriptions: {how}; {report['pictures']['described']} of {report['pictures']['pictures']} pictures carry one",
        "- the external counterpart on the same suite: `bench/reports/BASELINE_EXTERNAL.md`",
        "",
        "The only difference between the rows is the pictures' descriptions: same store, same queries, same words-only path.",
        "",
        "| split | n | chance (inside the asker's holder) | recall@10 before | recall@10 after | MRR after | 95% lower after |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name in SPLITS:
        floor = report["chance"] if name == "whole" else report["chance"][name]
        before, after = arm(report, "before", name), arm(report, "after", name)
        lines.append(
            f"| {name} | {after['queries']} | {floor['recall_at_10_holder_scope']:.4f} | {before['recall_at_10']:.3f} | "
            f"{after['recall_at_10']:.3f} | {after['mrr']:.3f} | {after['hit_at_10_wilson_lower']:.3f} |"
        )
    for name in SPLITS:
        floor = (report["chance"] if name == "whole" else report["chance"][name])["by_modality"]
        lines += ["", f"## recall@10 by modality, {name}", "", "| stage | " + " | ".join(MODALITY_ORDER) + " |", "| --- |" + " --- |" * len(MODALITY_ORDER)]
        lines.append("| chance | " + " | ".join("—" if m not in floor else f"{floor[m]:.4f}" for m in MODALITY_ORDER) + " |")
        for stage in ("before", "after"):
            cells = arm(report, stage, name)["by_modality"]
            lines.append(f"| {stage} | " + " | ".join("—" if m not in cells else f"{cells[m]:.3f}" for m in MODALITY_ORDER) + " |")
    lines += ["", "Latency moves with machine load and is kept in the JSON only; the recall columns do not.", ""]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="store to copy")
    parser.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH, help="where the copies live")
    parser.add_argument("--objects", type=Path, default=DEFAULT_OBJECTS, help="the objects the store's pictures live in")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="description requests in flight")
    parser.add_argument("--described-home", type=Path, default=None, help="a store an earlier run already described")
    parser.add_argument("--report", type=Path, default=REPORT, help="markdown destination")
    parser.add_argument("--payload", type=Path, default=PAYLOAD, help="json destination")
    arguments = parser.parse_args(argv)
    for destination in (arguments.report, arguments.payload):
        refuse_frozen_overwrite(destination)
    report = measure(arguments.home, arguments.scratch, arguments.workers, arguments.described_home, arguments.objects)
    arguments.payload.parent.mkdir(parents=True, exist_ok=True)
    arguments.payload.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(report, arguments.report)
    print(f"wrote {arguments.report}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
