"""Ingest the frozen benchmark sets through the unmodified pre-P0 IngestionService.

The baseline number must come from the code as it was before any P0 change, so this
script never edits the product: it drives IngestionService over every file the corpus
index names, one sharded SQLite per worker, then merges the shards into one database.
Shards are content-addressed on disk, so merging is a plain row copy.

Run: python -m bench.ingest_baseline [--workers 16] [--modality pdf]
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import resource
import shutil
import sqlite3
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from ely_eye.storage import (  # the product's own source-id rule
    safe_source_id,
    sha256_bytes,
)

from bench.sets_common import MODALITIES, SETS, read_jsonl, record_path

REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "bench" / "runs" / "baseline"
SHARDS = RUNS / "shards"
TABLES = ("sources", "atoms", "atom_fts", "cartridges", "cache_events", "evidence_edges")
# Virtual-address ceiling per worker. ONNX Runtime and torch reserve far more address space than
# they touch, so a 3 GiB ceiling killed OCR on large images ("Unable to allocate 582. MiB for an
# array with shape (5632, 9024, 3)") even though resident memory stayed near 1.5 GiB.
WORKER_MEMORY_BYTES = 6 * 1024**3
MAX_POOL_ATTEMPTS = 5
DELETE_STATEMENTS = (
    'DELETE FROM "evidence_edges"',
    'DELETE FROM "cache_events"',
    'DELETE FROM "atom_fts"',
    'DELETE FROM "cartridges"',
    'DELETE FROM "atoms"',
    'DELETE FROM "sources"',
)
COPY_STATEMENTS = (
    'INSERT OR IGNORE INTO "sources" SELECT * FROM shard."sources"',
    'INSERT OR IGNORE INTO "atoms" SELECT * FROM shard."atoms"',
    (
        'INSERT OR IGNORE INTO "atom_fts" (atom_id, source, text) '
        'SELECT DISTINCT atom_id, source, text FROM shard."atom_fts"'
    ),
    'INSERT OR IGNORE INTO "cartridges" SELECT * FROM shard."cartridges"',
    'INSERT OR IGNORE INTO "cache_events" SELECT * FROM shard."cache_events"',
    'INSERT OR IGNORE INTO "evidence_edges" SELECT * FROM shard."evidence_edges"',
)
COUNT_STATEMENTS = {
    "sources": 'SELECT count(*) FROM "sources"',
    "atoms": 'SELECT count(*) FROM "atoms"',
    "atom_fts": 'SELECT count(*) FROM "atom_fts"',
    "cartridges": 'SELECT count(*) FROM "cartridges"',
    "cache_events": 'SELECT count(*) FROM "cache_events"',
    "evidence_edges": 'SELECT count(*) FROM "evidence_edges"',
}


def corpus_paths(modality: str) -> list[Path]:
    """Absolute path of every file one modality's corpus index names."""
    records = list(read_jsonl(SETS / "corpus" / f"{modality}.jsonl"))
    paths: list[Path] = []
    seen: dict[Path, str] = {}
    for record in records:
        path = record_path(record).resolve()
        if not path.is_file():
            raise SystemExit(f"{modality}: corpus record {record['source_id']} names a missing file {path}")
        previous = seen.get(path)
        if previous is not None and previous != record["source_id"]:
            raise SystemExit(f"{modality}: {path} is claimed by both {previous} and {record['source_id']}")
        seen[path] = record["source_id"]
        paths.append(path)
    return paths


def source_map() -> dict[str, str]:
    """Map an absolute file path to the benchmark source id that owns it."""
    mapping: dict[str, str] = {}
    for modality in MODALITIES:
        for record in read_jsonl(SETS / "corpus" / f"{modality}.jsonl"):
            path = record_path(record).resolve()
            mapping[str(path)] = record["source_id"]
    return mapping


def shard_plan(modalities: Sequence[str], workers: int, limit: int | None) -> list[list[Path]]:
    """Round-robin files across workers so long videos do not pile up in one shard."""
    plan: list[list[Path]] = [[] for _ in range(workers)]
    index = 0
    for modality in modalities:
        paths = corpus_paths(modality)
        for path in paths[:limit] if limit else paths:
            plan[index % workers].append(path)
            index += 1
    return [shard for shard in plan if shard]


def _pin_inference_threads() -> None:
    """Pin every ONNX Runtime session to one thread; the model and its output are unchanged.

    rapidocr-onnxruntime 1.2.3 exposes no thread knob and ONNX Runtime defaults to every
    core, so each of 16 workers opened ~90 inference threads and the machine thrashed at a
    load average above 400. Wrapping InferenceSession is the only lever the library gives.
    """
    from typing import Any

    import onnxruntime as ort

    original = ort.InferenceSession

    def pinned(model_path: str | bytes | os.PathLike[str], *args: Any, **kwargs: Any) -> ort.InferenceSession:
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        # The CPU arena keeps freed blocks mapped, so a worker that OCRs thousands of pages grows its
        # resident set until it hits its ceiling on an 11 MiB array. Hand the memory back instead.
        options.enable_cpu_mem_arena = False
        kwargs["sess_options"] = options
        return original(model_path, *args, **kwargs)

    ort.InferenceSession = pinned  # type: ignore[method-assign]


def _single_threaded() -> None:
    """One CPU thread per worker: 16 workers on 32 cores, no oversubscription.

    OpenCV also defaults to every core, which is why cv2 is pinned alongside ONNX.
    """
    for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[variable] = "1"
    import cv2

    cv2.setNumThreads(1)
    _pin_inference_threads()
    _cap_worker_memory()


def _cap_worker_memory() -> None:
    """Cap each worker at 3 GiB so one pathological file raises MemoryError instead of being OOM-killed.

    A 16-worker run was killed by the kernel (anon-rss 10.0 GB) and took the whole process pool
    down with it; a per-worker ceiling turns that into a recorded per-file failure.
    """
    resource.setrlimit(resource.RLIMIT_AS, (WORKER_MEMORY_BYTES, WORKER_MEMORY_BYTES))


def ingest_shard(job: tuple[int, list[Path]]) -> dict:
    """Worker: ingest this shard's files into its own ELY_EYE_HOME, skipping finished ones."""
    index, paths = job
    _single_threaded()
    started = time.monotonic()
    home = SHARDS / f"shard-{index:02d}"
    home.mkdir(parents=True, exist_ok=True)
    ledger = home / "done.jsonl"
    done = set()
    if ledger.is_file():
        for number, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                done.add(json.loads(line)["path"])
            except (json.JSONDecodeError, KeyError) as error:
                raise SystemExit(f"{ledger}:{number}: unreadable resume ledger: {error}") from error

    from ely_eye.config import Settings
    from ely_eye.ingestion import IngestionService

    service = IngestionService(settings=Settings(home=home))
    ingested = 0
    atoms = 0
    failed = 0
    for path in paths:
        if str(path) in done:
            continue
        try:
            response = service.ingest_path(path)
            outcome = {"path": str(path), "sources": response.source_count, "atoms": response.atom_count}
            atoms += response.atom_count
            ingested += 1
        except Exception as error:  # noqa: BLE001 - a corpus sweep must record the file that broke it, not die with it
            outcome = {"path": str(path), "error": f"{type(error).__name__}: {error}"}
            failed += 1
            print(f"shard-{index:02d} FAILED {path.name}: {outcome['error']}", file=sys.stderr, flush=True)
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(outcome) + "\n")
        if ingested % 25 == 0:
            # ONNX Runtime keeps the address space it has touched, and one shard runs thousands of
            # files, so the arena has to be handed back or the worker hits its ceiling on an 11 MiB array.
            gc.collect()
            elapsed = time.monotonic() - started
            print(f"shard-{index:02d} {ingested}/{len(paths)} files in {elapsed / 60:.1f} min", flush=True)
    return {
        "shard": index,
        "files": len(paths),
        "ingested_now": ingested,
        "failed": failed,
        "skipped": len(paths) - ingested - failed,
        "atoms": atoms,
        "minutes": round((time.monotonic() - started) / 60, 2),
    }


def database_path(home: Path) -> Path:
    from ely_eye.config import Settings

    return Settings(home=home).db_path


def ledger_outcomes() -> tuple[set[str], set[str]]:
    """Return (ingested paths, failed paths) recorded across every shard ledger."""
    ingested: set[str] = set()
    failed: set[str] = set()
    for ledger in sorted(SHARDS.glob("shard-*/done.jsonl")):
        for number, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                path = entry["path"]
            except (json.JSONDecodeError, KeyError) as error:
                raise SystemExit(f"{ledger}:{number}: unreadable resume ledger: {error}") from error
            (failed if "error" in entry else ingested).add(path)
    return ingested, failed


def retry_failed() -> int:
    """Drop failed ledger entries so those files are attempted again, archiving what was dropped."""
    archive = RUNS / "failures.jsonl"
    dropped = 0
    for ledger in sorted(SHARDS.glob("shard-*/done.jsonl")):
        kept: list[str] = []
        removed: list[dict] = []
        for number, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as error:
                raise SystemExit(f"{ledger}:{number}: unreadable resume ledger: {error}") from error
            if "error" in entry:
                removed.append(entry)
            else:
                kept.append(line)
        if not removed:
            continue
        with archive.open("a", encoding="utf-8") as handle:
            for entry in removed:
                handle.write(json.dumps({"shard": ledger.parent.name, **entry}) + "\n")
        ledger.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        dropped += len(removed)
    return dropped


def merge() -> dict:
    """Copy every shard's rows and content-addressed objects into the merged database."""
    main_db = database_path(RUNS)
    main_db.parent.mkdir(parents=True, exist_ok=True)
    from ely_eye.config import Settings
    from ely_eye.db import Database

    Database(Settings(home=RUNS)).init()
    connection = sqlite3.connect(main_db)
    tables = [
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    ]
    missing = sorted(set(TABLES) - set(tables))
    if missing:
        raise SystemExit(f"{main_db}: schema is missing tables {missing}")
    for statement in DELETE_STATEMENTS:
        connection.execute(statement)

    shard_dirs = sorted(path for path in SHARDS.glob("shard-*") if path.is_dir())
    if not shard_dirs:
        raise SystemExit(f"{SHARDS}: no shards to merge")
    copied_objects = 0
    for shard in shard_dirs:
        shard_db = database_path(shard)
        if not shard_db.is_file():
            raise SystemExit(f"{shard}: no database at {shard_db}")
        connection.execute("ATTACH DATABASE ? AS shard", (str(shard_db),))
        for statement in COPY_STATEMENTS:
            cursor = connection.cursor()
            cursor.execute(statement)
            cursor.close()
        connection.commit()
        connection.execute("DETACH DATABASE shard")
        shard_objects = shard / "objects"
        if shard_objects.is_dir():
            for source in shard_objects.rglob("*"):
                if not source.is_file():
                    continue
                target = RUNS / "objects" / source.relative_to(shard_objects)
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copy2(source, target)
                    copied_objects += 1
    connection.commit()

    # A file processed in two attempts lands in two shards. The atoms table
    # dedupes on atom_id; fts5 has no key and kept every copy (288,266 rows for
    # 165,973 atoms), which would inflate the product's text search statistics.
    connection.execute("DELETE FROM atom_fts")
    connection.execute(
        "INSERT INTO atom_fts (atom_id, source, text) SELECT atom_id, source, text FROM atoms"
    )
    connection.commit()

    counts = {}
    for table, statement in COUNT_STATEMENTS.items():
        counts[table] = connection.execute(statement).fetchone()[0]
    connection.close()

    mapping = source_map()
    done, failed = ledger_outcomes()
    unknown = sorted((done | failed) - set(mapping))
    if unknown:
        raise SystemExit(f"{main_db}: {len(unknown)} ledger entries are not corpus files, first {unknown[:3]}")
    rows = sqlite3.connect(main_db).execute("SELECT path, source_id FROM sources").fetchall()
    unmapped = [path for path, _ in rows if path not in mapping]
    if unmapped:
        raise SystemExit(f"{main_db}: {len(unmapped)} sources are not named by the corpus index, first {unmapped[:3]}")
    product_paths = {path for path, _ in rows}
    product_ids = {source_id for _, source_id in rows}
    # The product names a source by content hash, so two byte-identical files
    # collapse into one source row (500 duplicate LongMemEval sessions).
    collapsed_input = sorted(path for path in done - product_paths if safe_source_id(Path(path), sha256_bytes(Path(path).read_bytes())) in product_ids)
    unaccounted = sorted(done - product_paths - set(collapsed_input))
    if unaccounted:
        raise SystemExit(
            f"{main_db}: {len(unaccounted)} ingested files produced no product source, first {unaccounted[:3]}"
        )
    collapsed: dict[str, list[str]] = {}
    for path, source_id in rows:
        collapsed.setdefault(source_id, []).append(mapping[path])
    covered = {source_id for ids in collapsed.values() for source_id in ids}
    total = set(mapping.values())
    counts["corpus_files"] = len(mapping)
    counts["files_ingested"] = len(done)
    counts["files_failed"] = len(failed & set(mapping))
    counts["files_not_ingested"] = len(set(mapping) - done - failed)
    counts["benchmark_sources_total"] = len(total)
    counts["benchmark_sources_covered"] = len(covered)
    counts["product_sources"] = len(collapsed)
    counts["duplicate_content_files"] = len(collapsed_input)
    counts["shared_source_ids"] = sum(1 for ids in collapsed.values() if len(ids) > 1)
    if counts["atom_fts"] != counts["atoms"]:
        raise SystemExit(
            f"{main_db}: atom_fts holds {counts['atom_fts']} rows for {counts['atoms']} atoms"
        )
    counts["uncovered_sources"] = len(total - covered)
    if counts["files_not_ingested"] == 0 and covered != total:
        # Two honest reasons: byte-identical inputs collapse into one content-hashed
        # source, and files the product cannot ingest at all. Anything else is a bug.
        explained = counts["duplicate_content_files"] + counts["files_failed"]
        if counts["uncovered_sources"] > explained:
            raise SystemExit(
                f"{main_db}: {counts['uncovered_sources']} benchmark sources have no product source but only "
                f"{explained} are explained by {counts['duplicate_content_files']} duplicate-content files and "
                f"{counts['files_failed']} failures"
            )
    counts["objects_copied"] = copied_objects
    (RUNS / "path_to_source_id.json").write_text(json.dumps(mapping, indent=1, sort_keys=True), encoding="utf-8")
    (RUNS / "ingest_report.json").write_text(json.dumps(counts, indent=1, sort_keys=True), encoding="utf-8")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--modality", action="append", choices=list(MODALITIES))
    parser.add_argument("--limit", type=int, help="ingest at most this many files per modality (smoke runs)")
    parser.add_argument("--merge-only", action="store_true")
    parser.add_argument("--retry-failed", action="store_true", help="re-attempt files a previous pass recorded as failed")
    args = parser.parse_args()

    if args.retry_failed:
        counts = merge() if args.merge_only else None
        dropped = retry_failed()
        print(f"== re-queued {dropped} failed files; their errors are archived in {RUNS / 'failures.jsonl'}")
        if counts is not None:
            print(json.dumps(counts, indent=1, sort_keys=True))
        return 0

    modalities = args.modality or list(MODALITIES)
    if not args.merge_only:
        plan = shard_plan(modalities, args.workers, args.limit)
        print(f"== ingesting {sum(len(shard) for shard in plan)} files across {len(plan)} shards", flush=True)
        for attempt in range(1, MAX_POOL_ATTEMPTS + 1):
            try:
                with ProcessPoolExecutor(max_workers=len(plan)) as pool:
                    for result in pool.map(ingest_shard, [(index, shard) for index, shard in enumerate(plan)]):
                        print(
                            f"shard {result['shard']:02d}: {result['ingested_now']} ingested, "
                            f"{result['failed']} failed, {result['skipped']} already done, {result['atoms']} atoms",
                            flush=True,
                        )
                break
            except BrokenProcessPool as error:
                print(
                    f"== worker pool died (attempt {attempt}/{MAX_POOL_ATTEMPTS}): {error}; resuming from ledgers",
                    file=sys.stderr,
                    flush=True,
                )
                if attempt == MAX_POOL_ATTEMPTS:
                    raise SystemExit(f"worker pool died {MAX_POOL_ATTEMPTS} times; ledgers keep progress") from error

    counts = merge()
    print(json.dumps(counts, indent=1, sort_keys=True))
    print(f"== merged baseline database at {database_path(RUNS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
