"""What speech is worth on the video questions: the same store and probes, with audio added.

The frozen stores were ingested before ASR landed, so every video answers from frames and OCR
alone and video recall@10 sits at 0.455 while code sits at 0.945. This harness copies the dense
store, re-ingests the same Video-MME files with a speech snapshot wired in, and ranks the same
probes before and after. The only thing that moved between the two rows is the speech.

Run: python -m bench.video_audio_check
Writes: bench/reports/VIDEO_AUDIO.md, bench/reports/video_audio.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from bench.leg_check import SHIPPED_TOP_K, _groups, _source_ids, rank_all
from bench.metrics import aggregate, score_query
from bench.query_set import load_queries, scale_probes, source_times
from bench.report import git_commit
from bench.run import latency
from bench.scratch import copy_store
from bench.sets_common import DATA_ROOT
from bench.systems import machine_facts

DEFAULT_HOME = Path("bench/runs/dense_scale")
DEFAULT_SCRATCH = Path("bench/runs/video_audio")
DEFAULT_ASR = Path("bench/models/faster-whisper-tiny")
DEFAULT_PROBES = 300
VIDEO_MODALITY = "video"
REPORT = Path("bench/reports/VIDEO_AUDIO.md")
PAYLOAD = Path("bench/reports/video_audio.json")


def video_queries() -> list[Any]:
    """Every answerable video question in the frozen suite, measured whole rather than sampled."""
    queries = [query for query in load_queries() if query.modality == VIDEO_MODALITY and query.gold]
    if not queries:
        raise SystemExit("the frozen suite carries no answerable video query; there would be nothing to score")
    return queries


def guard_videos(videos: Path, store: Path) -> list[Path]:
    """The files the store already holds, so re-ingesting adds speech instead of a second copy."""
    import sqlite3

    if not videos.is_dir():
        raise SystemExit(
            f"{videos}: the Video-MME files are not here; they are staged from the corpus zips at "
            "the data root (set ELY_EYE_BENCH_DATA to wherever they live)"
        )
    files = sorted(videos.glob("*.mp4"))
    if not files:
        raise SystemExit(f"{videos}: no .mp4 files to re-ingest")
    with sqlite3.connect(f"file:{store / 'data' / 'ely_eye.sqlite'}?mode=ro", uri=True) as connection:
        stored = {row[0] for row in connection.execute("SELECT source_id FROM sources WHERE kind = 'video'")}
    if not stored:
        raise SystemExit(f"{store}: the store holds no video sources, so speech would have nothing to join to")
    return files


def speech_facts(store: Path) -> dict[str, Any]:
    """How much speech the store carries, and how many words of it."""
    import sqlite3

    with sqlite3.connect(f"file:{store / 'data' / 'ely_eye.sqlite'}?mode=ro", uri=True) as connection:
        atoms, characters = connection.execute(
            "SELECT count(*), coalesce(sum(length(text)), 0) FROM atoms WHERE modality = 'audio'"
        ).fetchone()
    return {"atoms": int(atoms), "characters": int(characters)}


def rank_arm(home: Path, probes: list[Any], top_k: int) -> dict[str, Any]:
    """Rank the probes through the shipped words-only path and score them."""
    from ely_eye.config import Settings
    from ely_eye.db import Database
    from ely_eye.retrieval import RetrievalService

    settings = Settings(
        home=home,
        dense_embeddings_enabled=False,
        embedding_model_dir=None,
        clip_model_dir=None,
    )
    if settings.retrieval_top_k != SHIPPED_TOP_K:
        raise SystemExit(
            f"the product asks for {settings.retrieval_top_k} atoms per search but this harness "
            f"labels its row 'as shipped' at {SHIPPED_TOP_K}; update the label before trusting it"
        )
    database = Database(settings)
    service = RetrievalService(settings=settings, database=database)
    ids = _source_ids(database)
    rankings, distinct, timings = rank_all(service, ids, probes, top_k)
    scores = [
        score_query(query.query_id, ranking, set(query.gold), query.holder)
        for query, ranking in zip(probes, rankings, strict=True)
    ]
    summary = aggregate(scores)
    timing = latency(timings)
    return {
        "queries": len(probes),
        "top_k": top_k,
        "recall_at_10": summary["recall_at_10"],
        "mrr": summary["mrr"],
        "hit_at_10": summary["hit_at_10"],
        "wilson_lower": summary["hit_at_10_wilson_lower"],
        "p50_seconds": timing["p50"],
        "p95_seconds": timing["p95"],
        "median_distinct_sources": statistics.median(distinct),
        **_groups(probes, scores, rankings, source_times()),
    }


def add_speech(home: Path, files: list[Path], asr: Path, limit: int) -> dict[str, Any]:
    """Re-ingest the same files with the speech snapshot, and time the whole pass."""
    from ely_eye.config import Settings
    from ely_eye.ingestion import IngestionService

    if not (asr / "model.bin").exists():
        raise SystemExit(
            f"{asr}: no speech snapshot here; the ingest would defer every video and the after row "
            "would silently equal the before row"
        )
    if limit:
        files = files[:limit]
    settings = Settings(home=home, asr_model_dir=asr)
    service = IngestionService(settings)
    began = time.perf_counter()
    batches = 0
    for index, path in enumerate(files, start=1):
        service.ingest_path(path)
        batches += 1
        if index % 10 == 0:
            print(f"    ingested {index}/{len(files)}", flush=True)
    return {"files": batches, "seconds": time.perf_counter() - began}


def measure(home: Path, scratch: Path, videos: Path, asr: Path, probes: int, limit: int) -> dict[str, Any]:
    """Score the video questions and the standard probe sample before and after the speech pass."""
    if not (home / "data" / "ely_eye.sqlite").exists():
        raise SystemExit(f"{home}: no store to copy; run `python -m bench.dense_scale` first")
    files = guard_videos(videos, home)
    whole = video_queries() if not limit else video_queries()[:limit]
    sample = [query for query in scale_probes(load_queries(), probes) if query.gold]
    if limit:
        sample = [query for query in sample if query.modality == VIDEO_MODALITY][:limit]
    print(f"{len(whole)} answerable video queries, {len(sample)} stratified probes, {len(files)} files", flush=True)

    copy_home, copied = copy_store(home, scratch)
    print(f"copied the store in {copied:.1f}s to {copy_home}", flush=True)
    before_speech = speech_facts(copy_home)
    if before_speech["atoms"]:
        print(f"note: the copy already carries {before_speech['atoms']} speech atoms", flush=True)
    before_video = rank_arm(copy_home, whole, SHIPPED_TOP_K)
    before_sample = rank_arm(copy_home, sample, SHIPPED_TOP_K)
    print(
        f"  before: video recall@10 {before_video['recall_at_10']:.3f}, "
        f"probes {before_sample['recall_at_10']:.3f}",
        flush=True,
    )

    ingest = add_speech(copy_home, files, asr, limit)
    after_speech = speech_facts(copy_home)
    if after_speech["atoms"] == before_speech["atoms"]:
        raise SystemExit(
            f"re-ingesting {len(files)} files added no speech atoms; the snapshot at {asr} is "
            "available but produced nothing, so the after row would be a measurement of nothing"
        )
    after_video = rank_arm(copy_home, whole, SHIPPED_TOP_K)
    after_sample = rank_arm(copy_home, sample, SHIPPED_TOP_K)
    print(
        f"  after:  video recall@10 {after_video['recall_at_10']:.3f}, "
        f"probes {after_sample['recall_at_10']:.3f}, speech atoms {after_speech['atoms']}",
        flush=True,
    )
    return {
        "commit": git_commit(),
        "machine": machine_facts(),
        "source_store": str(home),
        "videos": str(videos),
        "files": len(files),
        "asr_model": str(asr),
        "ingest": ingest,
        "speech_before": before_speech,
        "speech_after": after_speech,
        "before": {"video": before_video, "probes": before_sample},
        "after": {"video": after_video, "probes": after_sample},
    }


def write_markdown(report: dict[str, Any], destination: Path) -> None:
    """Print the two rows beside each other, with the load they were measured under."""
    load = report["machine"].get("load_average_1_5_15")
    lines = [
        "# What speech is worth on the video questions",
        "",
        f"- commit: `{report['commit']}`",
        f"- store measured: a copy of `{report['source_store']}`; the source is never opened for write",
        f"- machine: {report['machine'].get('cpus')} cpus, load {load}",
        f"- speech snapshot: `{report['asr_model']}` (the shipped default; its word error rate is in ASR.md)",
        f"- re-ingest: {report['ingest']['files']} files in {report['ingest']['seconds']:.0f}s",
        (
            f"- speech atoms: {report['speech_before']['atoms']} before → {report['speech_after']['atoms']} after"
            f" ({report['speech_after']['characters']} characters)"
        ),
        "",
        "The only difference between the rows is the speech: same store, same files, same probes, same words-only path.",
        "",
        "| asked | n | recall@10 | MRR | hit@10 | 95% lower | p50 s |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for stage in ("before", "after"):
        for arm, label in (("video", "every video question"), ("probes", "the stratified probe sample")):
            row = report[stage][arm]
            lines.append(
                f"| {label} ({stage}) | {row['queries']} | {row['recall_at_10']:.3f} | {row['mrr']:.3f} | "
                f"{row['hit_at_10']:.3f} | {row['wilson_lower']:.3f} | {row['p50_seconds']:.3f} |"
            )
    gained = report["after"]["video"]["recall_at_10"] - report["before"]["video"]["recall_at_10"]
    overall = report["after"]["probes"]["recall_at_10"] - report["before"]["probes"]["recall_at_10"]
    lines += [
        "",
        f"Speech moved video recall@10 by {gained:+.3f} and the whole probe sample by {overall:+.3f}.",
        "",
        "Latency is read from the same pass and moves with machine load; the recall columns do not.",
        "",
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines), encoding="utf-8")


def refuse_frozen_overwrite(destination: Path) -> None:
    """A reviewer running this in a worktree of its own must not overwrite the committed evidence."""
    if destination.parent == PAYLOAD.parent and destination.exists():
        raise SystemExit(
            f"{destination} is a frozen report; point --report and --payload somewhere else, or "
            "delete the frozen copy on purpose rather than under a harness"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="store to copy")
    parser.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH, help="where the copy lives")
    parser.add_argument("--videos", type=Path, default=DATA_ROOT / "videomme", help="where the mp4s are staged")
    parser.add_argument("--asr", type=Path, default=DEFAULT_ASR, help="speech snapshot")
    parser.add_argument("--probes", type=int, default=DEFAULT_PROBES, help="probe sample size")
    parser.add_argument("--limit", type=int, default=0, help="smoke knob: only this many files and queries")
    parser.add_argument("--report", type=Path, default=REPORT, help="markdown destination")
    parser.add_argument("--payload", type=Path, default=PAYLOAD, help="json destination")
    arguments = parser.parse_args(argv)
    for destination in (arguments.report, arguments.payload):
        refuse_frozen_overwrite(destination)
    report = measure(
        arguments.home, arguments.scratch, arguments.videos, arguments.asr, arguments.probes, arguments.limit
    )
    arguments.payload.parent.mkdir(parents=True, exist_ok=True)
    arguments.payload.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(report, arguments.report)
    print(f"wrote {arguments.report}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
