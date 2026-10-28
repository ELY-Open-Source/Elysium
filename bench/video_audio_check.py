"""What speech is worth on the video questions: the same store and queries, with audio added.

The frozen stores were ingested before ASR landed, so every video answers from frames and OCR
alone. This harness copies the dense store, re-ingests the same Video-MME files with a speech
snapshot wired in, and ranks every answerable query before and after. The only thing that moved
between the two rows is the speech. The whole suite is scored, not a sample, because speech can
cost the other modalities as much as it gives video, and a sample misreads a modality's share.

The re-ingest takes hours, so `--speech-home` ranks a store a previous run already re-ingested
instead; the harness checks that store carries speech and the same video sources before trusting it.

Run: python -m bench.video_audio_check [--speech-home bench/runs/video_audio_speech]
Writes: bench/reports/VIDEO_AUDIO.md, bench/reports/video_audio.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
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
from bench.stamp_holders import stamp
from bench.systems import machine_facts

DEFAULT_HOME = Path("bench/runs/dense_scale")
DEFAULT_SCRATCH = Path("bench/runs/video_audio")
DEFAULT_ASR = Path("bench/models/faster-whisper-tiny")
MODALITY_ORDER = ("code", "conversation", "image", "pdf", "ui_screenshot", "video")
VIDEO_MODALITY = "video"
REPORT = Path("bench/reports/VIDEO_AUDIO.md")
PAYLOAD = Path("bench/reports/video_audio.json")


def video_queries() -> list[Any]:
    """Every answerable video question in the frozen suite, measured whole rather than sampled."""
    queries = [query for query in load_queries() if query.modality == VIDEO_MODALITY and query.gold]
    if not queries:
        raise SystemExit("the frozen suite carries no answerable video query; there would be nothing to score")
    return queries


def video_sources(store: Path) -> set[str]:
    """The video sources a store holds, read without opening it for write."""
    import sqlite3

    with sqlite3.connect(f"file:{store / 'data' / 'elysium.sqlite'}?mode=ro", uri=True) as connection:
        return {row[0] for row in connection.execute("SELECT source_id FROM sources WHERE kind = 'video'")}


def guard_videos(videos: Path, store: Path) -> list[Path]:
    """The files the store already holds, so re-ingesting adds speech instead of a second copy."""
    if not videos.is_dir():
        raise SystemExit(
            f"{videos}: the Video-MME files are not here; they are staged from the corpus zips at "
            "the data root (set ELYSIUM_BENCH_DATA to wherever they live)"
        )
    files = sorted(videos.glob("*.mp4"))
    if not files:
        raise SystemExit(f"{videos}: no .mp4 files to re-ingest")
    if not video_sources(store):
        raise SystemExit(f"{store}: the store holds no video sources, so speech would have nothing to join to")
    return files


def speech_facts(store: Path) -> dict[str, Any]:
    """How much speech the store carries, and how many words of it."""
    import sqlite3

    with sqlite3.connect(f"file:{store / 'data' / 'elysium.sqlite'}?mode=ro", uri=True) as connection:
        atoms, characters = connection.execute(
            "SELECT count(*), coalesce(sum(length(text)), 0) FROM atoms WHERE modality = 'audio'"
        ).fetchone()
    return {"atoms": int(atoms), "characters": int(characters)}


def unowned(store: Path) -> int:
    """Atoms nobody holds answer every caller, so one left over turns a scoped suite into a whole-corpus one."""
    import sqlite3

    with sqlite3.connect(f"file:{store / 'data' / 'elysium.sqlite'}?mode=ro", uri=True) as connection:
        return int(connection.execute("SELECT count(*) FROM atoms WHERE holder_id = ''").fetchone()[0])


def require_owned(store: Path, label: str) -> None:
    """Refuse to rank a store where re-ingest left atoms that every holder can read."""
    left = unowned(store)
    if left:
        raise SystemExit(
            f"{label}: {left} atoms in {store} have no holder, so every query would rank them; "
            "the rows would measure leaked visibility rather than speech"
        )


def rank_arm(home: Path, probes: list[Any], top_k: int) -> dict[str, Any] | None:
    """Rank the probes through the shipped words-only path and score them; None skips the arm."""
    from elysium.config import Settings
    from elysium.db import Database
    from elysium.retrieval import RetrievalService

    if not probes:
        return None
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
    from elysium.config import Settings
    from elysium.ingestion import IngestionService

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


def answerable_suite(limit: int) -> list[Any]:
    """Every answerable query in the frozen suite; the smoke knob keeps a stratified slice of it."""
    every = load_queries()
    if limit:
        return [query for query in scale_probes(every, limit) if query.gold]
    answerable = [query for query in every if query.gold]
    if not answerable:
        raise SystemExit("the frozen suite carries no answerable query; nothing to score")
    return answerable


def reuse_speech(home: Path, speech_home: Path, scratch: Path) -> dict[str, Any]:
    """Trust an already re-ingested store only if it is the same videos with speech added."""
    if speech_home.resolve() == scratch.resolve():
        raise SystemExit(
            f"--speech-home {speech_home} is the scratch this run copies into; the copy would "
            "overwrite the very store it was asked to reuse"
        )
    if not (speech_home / "data" / "elysium.sqlite").exists():
        raise SystemExit(f"{speech_home}: no store to reuse; drop --speech-home to re-ingest")
    facts = speech_facts(speech_home)
    if not facts["atoms"]:
        raise SystemExit(f"{speech_home}: the store carries no speech atoms, so the after row would equal the before row")
    if video_sources(speech_home) != video_sources(home):
        raise SystemExit(
            f"{speech_home} holds different video sources from {home}; the rows would differ by more than speech"
        )
    return {"reused": str(speech_home), "files": len(video_sources(speech_home)), "seconds": None}


def measure(
    home: Path, scratch: Path, videos: Path, asr: Path, limit: int, speech_home: Path | None
) -> dict[str, Any]:
    """Score the video questions and the whole answerable suite before and after the speech pass."""
    if not (home / "data" / "elysium.sqlite").exists():
        raise SystemExit(f"{home}: no store to copy; run `python -m bench.dense_scale` first")
    reused = None if speech_home is None else reuse_speech(home, speech_home, scratch)
    files = guard_videos(videos, home) if reused is None else []
    whole = video_queries() if not limit else video_queries()[:limit]
    suite = answerable_suite(limit)
    print(f"{len(whole)} answerable video queries, {len(suite)} answerable queries, {len(files)} files", flush=True)

    copy_home, copied = copy_store(home, scratch / "before" if reused else scratch)
    print(f"copied the store in {copied:.1f}s to {copy_home}", flush=True)
    require_owned(copy_home, "before")
    before_speech = speech_facts(copy_home)
    if before_speech["atoms"]:
        print(f"note: the copy already carries {before_speech['atoms']} speech atoms", flush=True)
    before_video = _required(rank_arm(copy_home, whole, SHIPPED_TOP_K), "every video question")
    before_suite = _required(rank_arm(copy_home, suite, SHIPPED_TOP_K), "every answerable question")
    print(
        f"  before: video recall@10 {before_video['recall_at_10']:.3f}, "
        f"suite {before_suite['recall_at_10']:.3f}",
        flush=True,
    )

    if reused is None:
        ingest = add_speech(copy_home, files, asr, limit)
        after_home = copy_home
    else:
        ingest = reused
        after_home, copied = copy_store(Path(reused["reused"]), scratch / "after")
        print(f"copied the speech store in {copied:.1f}s to {after_home}", flush=True)
        # A store re-ingested before ingest kept provenance lost its holders; these are the corpus facts it would have kept.
        ingest["restamped"] = stamp(after_home / "data" / "elysium.sqlite")
    require_owned(after_home, "after")
    after_speech = speech_facts(after_home)
    if after_speech["atoms"] == before_speech["atoms"]:
        raise SystemExit(
            f"re-ingesting {len(files)} files added no speech atoms; the snapshot at {asr} is "
            "available but produced nothing, so the after row would be a measurement of nothing"
        )
    after_video = _required(rank_arm(after_home, whole, SHIPPED_TOP_K), "every video question")
    after_suite = _required(rank_arm(after_home, suite, SHIPPED_TOP_K), "every answerable question")
    print(
        f"  after:  video recall@10 {after_video['recall_at_10']:.3f}, "
        f"suite {after_suite['recall_at_10']:.3f}, speech atoms {after_speech['atoms']}",
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
        "before": {"video": before_video, "suite": before_suite},
        "after": {"video": after_video, "suite": after_suite},
    }


def _required(row: dict[str, Any] | None, label: str) -> dict[str, Any]:
    """The video arm is never empty; a row of zeros there would be a silent lie."""
    if row is None:
        raise SystemExit(f"{label}: nothing to rank, so this run would print a row of zeros")
    return row


def _ingest_line(ingest: dict[str, Any]) -> str:
    """How the speech got into the after store: timed here, or reused from an earlier pass."""
    if ingest.get("reused"):
        restamped = ingest["restamped"]
        return (
            f"- re-ingest: reused `{ingest['reused']}` ({ingest['files']} video sources), not re-timed in this run; "
            f"that store was re-ingested before ingest kept provenance, so the copy's holders were re-stamped "
            f"from the frozen corpus index ({restamped['atoms']} atoms, {restamped['atoms_without_holder']} left without one)"
        )
    return f"- re-ingest: {ingest['files']} files in {ingest['seconds']:.0f}s"


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
        _ingest_line(report["ingest"]),
        (
            f"- speech atoms: {report['speech_before']['atoms']} before → {report['speech_after']['atoms']} after"
            f" ({report['speech_after']['characters']} characters)"
        ),
        "- chance floor and the external counterpart for the same suite: `bench/reports/BASELINE_EXTERNAL.md`",
        "",
        "The only difference between the rows is the speech: same store, same files, same queries, same words-only path.",
        "",
        "| asked | n | recall@10 | MRR | hit@10 | 95% lower | p50 s |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    arms = (("video", "every video question"), ("suite", "every answerable question"))
    for stage in ("before", "after"):
        for arm, label in arms:
            row = report[stage][arm]
            lines.append(
                f"| {label} ({stage}) | {row['queries']} | {row['recall_at_10']:.3f} | {row['mrr']:.3f} | "
                f"{row['hit_at_10']:.3f} | {row['wilson_lower']:.3f} | {row['p50_seconds']:.3f} |"
            )
    lines += [
        "",
        "## recall@10 by modality, every answerable question",
        "",
        "| stage | " + " | ".join(MODALITY_ORDER) + " |",
        "| --- |" + " --- |" * len(MODALITY_ORDER),
    ]
    for stage in ("before", "after"):
        modalities = report[stage]["suite"]["by_modality"]
        cells = " | ".join("—" if name not in modalities else f"{modalities[name]:.3f}" for name in MODALITY_ORDER)
        lines.append(f"| {stage} | {cells} |")
    counts = report["after"]["suite"]["modality_counts"]
    lines.append("")
    lines.append("_Query counts: " + ", ".join(f"{name} {counts.get(name, 0)}" for name in MODALITY_ORDER) + "._")
    gained = report["after"]["video"]["recall_at_10"] - report["before"]["video"]["recall_at_10"]
    overall = report["after"]["suite"]["recall_at_10"] - report["before"]["suite"]["recall_at_10"]
    lines += [
        "",
        f"Speech moved video recall@10 by {gained:+.3f} and the whole answerable suite by {overall:+.3f}.",
        "",
        "Latency is read from the same pass and moves with machine load; the recall columns do not.",
        "",
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines), encoding="utf-8")


def _tracked(path: Path) -> bool:
    """Only committed evidence is frozen; a harness's own untracked output is fair game.

    The question goes to the repository that owns the path, so a reviewer working in a worktree
    cannot point at another checkout's committed report and be told it is untracked.
    """
    owner = path.resolve().parent
    return (
        subprocess.run(
            ["git", "-C", str(owner), "ls-files", "--error-unmatch", path.resolve().name],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def refuse_frozen_overwrite(destination: Path) -> None:
    """A reviewer running this in a worktree of its own must not overwrite the committed evidence."""
    if destination.exists() and _tracked(destination):
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
    parser.add_argument(
        "--speech-home", type=Path, default=None, help="a store an earlier run already re-ingested with speech"
    )
    parser.add_argument("--limit", type=int, default=0, help="smoke knob: only this many files and queries")
    parser.add_argument("--report", type=Path, default=REPORT, help="markdown destination")
    parser.add_argument("--payload", type=Path, default=PAYLOAD, help="json destination")
    arguments = parser.parse_args(argv)
    for destination in (arguments.report, arguments.payload):
        refuse_frozen_overwrite(destination)
    report = measure(
        arguments.home, arguments.scratch, arguments.videos, arguments.asr, arguments.limit, arguments.speech_home
    )
    arguments.payload.parent.mkdir(parents=True, exist_ok=True)
    arguments.payload.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(report, arguments.report)
    print(f"wrote {arguments.report}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
