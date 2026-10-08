"""What the dense leg costs at the size the library actually reaches, and what a million would.

The baseline store holds 165,973 atoms. This check builds the product's own vector table inside
a copy of that store, times real searches, proves the engine's answers match a brute-force scan,
and then states what one million memories would cost on the same machine — with the assumption
written down instead of implied.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from bench.query_set import load_queries, scale_probes
from bench.report import git_commit
from bench.run import latency
from bench.scratch import copy_store
from bench.systems import DENSE_MODEL, MODELS, machine_facts

if TYPE_CHECKING:
    from ely_eye.db import Database

DEFAULT_HOME = Path("bench/runs/baseline")
DEFAULT_SCRATCH = Path("bench/runs/dense_scale")
MIN_ATOMS = 100_000
TOP_K = 10
CORRECTNESS_PROBES = 40
EXTRAPOLATE_TO = 1_000_000
WRITE_PROBES = 50


def _one_write(index: Any, atom_id: str) -> float:
    """Time one memory going into an index that already holds the whole corpus."""
    began = time.perf_counter()
    index.sync_atoms([atom_id])
    return time.perf_counter() - began


def vector_footprint(database: Any, table: str) -> tuple[int, str]:
    """What the vector table costs on disk, and how that was counted.

    The database file itself is a poor measure: free pages absorb a table this size, so the file
    can stay exactly the same length while the table grows. dbstat counts the pages the vec0
    shadow tables actually hold, and it works without the vec0 extension loaded.
    """
    with database.connect() as connection:
        try:
            pages = connection.execute(
                "SELECT COALESCE(SUM(pgsize), 0) FROM dbstat WHERE name LIKE ?", (f"{table}%",)
            ).fetchone()[0]
            if int(pages):
                return int(pages), "dbstat page sizes over the vec0 shadow tables"
        except sqlite3.OperationalError:
            pass
        payload = connection.execute(
            "SELECT COALESCE(SUM(length(embedding)), 0) FROM vec_atoms"
        ).fetchone()[0]
    return int(payload), "vector bytes only, this sqlite3 has no dbstat"


def stored_vectors(database: Database) -> tuple[list[str], np.ndarray]:
    """Every vector the engine holds, for a scan it can be checked against."""
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT atom_id, embedding FROM vec_atoms ORDER BY atom_id
            """
        ).fetchall()
    if not rows:
        raise SystemExit("the vector table is empty, so there is nothing to measure")
    ids = [str(row["atom_id"]) for row in rows]
    matrix = np.stack([np.frombuffer(row["embedding"], dtype=np.float32) for row in rows])
    return ids, matrix


def agreement(ids: list[str], matrix: np.ndarray, probes: Sequence[tuple[np.ndarray, list[str]]]) -> dict[str, Any]:
    """How often the engine's top ten agrees with a full scan, counting a tie as a tie."""
    if not probes:
        raise SystemExit("correctness needs at least one probe")
    matched = 0
    compared = 0
    for vector, returned in probes:
        cosine = matrix @ vector
        order = np.argsort(-cosine, kind="stable")
        threshold = cosine[order[TOP_K - 1]]
        correct = {ids[index] for index in order if cosine[index] >= threshold}
        matched += sum(1 for atom_id in returned if atom_id in correct)
        compared += min(len(returned), TOP_K)
    return {
        "probes": len(probes),
        "top_k": TOP_K,
        "tie_aware_agreement": matched / compared if compared else 0.0,
        "note": "a returned atom counts when its true cosine is at least the k-th best, so ties cannot fail the check",
    }


def measure(home: Path, scratch: Path, probes: int, model_dir: Path) -> dict[str, Any]:
    from ely_eye.config import Settings
    from ely_eye.db import Database
    from ely_eye.embeddings import EmbeddingService
    from ely_eye.vector_index import VectorIndex, expected_vectors

    copy_home, copy_seconds = copy_store(home, scratch)
    settings = Settings(
        home=copy_home,
        dense_embeddings_enabled=True,
        embedding_model_dir=model_dir,
        embedding_model_id=DENSE_MODEL,
    )
    database = Database(settings)
    atoms = database.atom_count()
    if atoms < MIN_ATOMS:
        raise SystemExit(f"{database.path}: {atoms} atoms, this check needs at least {MIN_ATOMS}")

    embeddings = EmbeddingService(settings, database)
    index = VectorIndex(settings, database, embeddings)
    print(f"{atoms} atoms copied in {copy_seconds:.1f}s, encoding with {DENSE_MODEL}", flush=True)
    began = time.perf_counter()
    index.sync()
    build_seconds = time.perf_counter() - began
    vec_bytes, bytes_method = vector_footprint(database, "vec_atoms")
    print(f"index built in {build_seconds:.1f}s", flush=True)

    began = time.perf_counter()
    index.sync()
    repair_seconds = time.perf_counter() - began
    print(f"nothing to repair, the scan took {repair_seconds:.1f}s", flush=True)

    queries = scale_probes(load_queries(), probes)
    index.search(embeddings.embed_query(queries[0].text), TOP_K)
    search_times: list[float] = []
    encode_times: list[float] = []
    returned: list[tuple[str, list[str]]] = []
    for query in queries:
        began = time.perf_counter()
        vector = embeddings.embed_query(query.text)
        encode_times.append(time.perf_counter() - began)
        began = time.perf_counter()
        hits = index.search(vector, TOP_K)
        search_times.append(time.perf_counter() - began)
        returned.append((query.text, list(hits)))
        if len(search_times) % 100 == 0:
            print(f"searched {len(search_times)}/{len(queries)}, p50 {sorted(search_times)[len(search_times) // 2] * 1000:.1f}ms", flush=True)

    ids, matrix = stored_vectors(database)
    print(f"{len(ids)} vectors read back, checking the engine against a brute-force scan", flush=True)
    checked_probes = []
    for query in queries[:CORRECTNESS_PROBES]:
        vector = embeddings.embed_query(query.text)
        checked_probes.append((vector, list(index.search(vector, TOP_K))))
    checked = agreement(ids, matrix, checked_probes)
    print(f"agreement {checked['tie_aware_agreement']:.3f} over {checked['probes']} probes", flush=True)

    written = [hit[0] for _, hit in returned[:WRITE_PROBES] if hit]
    writes = latency([_one_write(index, atom_id) for atom_id in written])
    print(f"{len(written)} writes into a full index, p50 {writes['p50'] * 1000:.0f}ms", flush=True)

    facts = index.stats()
    encoded = int(facts["vectors"])
    per_vector = vec_bytes / encoded if encoded else 0.0
    texts_per_second = encoded / build_seconds if build_seconds else 0.0
    timing = latency(search_times)
    return {
        "commit": git_commit(),
        "database": str(database.path),
        "atoms": atoms,
        "memories_with_words": expected_vectors(database),
        "vectors": encoded,
        "pending": facts["pending"],
        "dim": facts["dim"],
        "model": facts["model"],
        "copy_seconds": copy_seconds,
        "build_seconds": build_seconds,
        "texts_per_second": texts_per_second,
        "repair_seconds": repair_seconds,
        "writes": len(written),
        "write_latency": writes,
        "probes": len(queries),
        "probe_modalities": sorted({query.modality for query in queries}),
        "latency": timing,
        "encode_latency": latency(encode_times),
        "correctness": checked,
        "bytes_per_vector": per_vector,
        "vector_bytes": vec_bytes,
        "bytes_method": bytes_method,
        "extrapolation": {
            "to": EXTRAPOLATE_TO,
            "assumption": (
                "sqlite-vec 0.1.9 scans every vector, so latency and bytes grow linearly with the "
                "count; the model, the machine and the thread budget stay the same"
            ),
            "p50_seconds": timing["p50"] * EXTRAPOLATE_TO / atoms,
            "p95_seconds": timing["p95"] * EXTRAPOLATE_TO / atoms,
            "write_p50_seconds": writes["p50"] * EXTRAPOLATE_TO / atoms,
            "gibibytes": per_vector * EXTRAPOLATE_TO / 1024**3,
            "build_seconds": EXTRAPOLATE_TO / texts_per_second if texts_per_second else None,
        },
        "machine": machine_facts(),
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    timing = report["latency"]
    encode = report["encode_latency"]
    write = report["write_latency"]
    machine = report["machine"]
    future = report["extrapolation"]
    path.write_text(
        "\n".join(
            [
                f"# DENSE: the vector leg at corpus size (commit {report['commit'][:9]})",
                "",
                f"- database: `{report['database']}`",
                (
                    f"- atoms: {report['atoms']}, memories with words: {report['memories_with_words']}, "
                    f"vectors: {report['vectors']}, pending: {report['pending']}"
                ),
                f"- model: `{report['model']}`, width {report['dim']}",
                (
                    f"- build: {report['build_seconds']:.1f}s for {report['vectors']} memories "
                    f"({report['texts_per_second']:.0f} per second)"
                ),
                (
                    f"- writing one memory into a full index: p50 {write['p50'] * 1000:.0f}ms · "
                    f"p95 {write['p95'] * 1000:.0f}ms over {write['queries']} writes"
                ),
                f"- the repair scan (`ely-eye build-dense-index`) over a full index: {report['repair_seconds']:.1f}s, and it is not on the search path",
                (
                    f"- search p50 {timing['p50'] * 1000:.1f}ms · p95 {timing['p95'] * 1000:.1f}ms · "
                    f"max {timing['max'] * 1000:.1f}ms over {timing['queries']} queries"
                ),
                (
                    f"- of which encoding the question: p50 {encode['p50'] * 1000:.1f}ms · "
                    f"p95 {encode['p95'] * 1000:.1f}ms"
                ),
                (
                    f"- against a brute-force scan: {report['correctness']['tie_aware_agreement']:.3f} "
                    f"of the top {report['correctness']['top_k']} over {report['correctness']['probes']} probes "
                    f"({report['correctness']['note']})"
                ),
                (
                    f"- bytes per stored vector: {report['bytes_per_vector']:.0f} "
                    f"({report['vector_bytes']} bytes for {report['vectors']} vectors, {report['bytes_method']})"
                ),
                (
                    f"- machine: {machine['system']} {machine['release']}, {machine['cpus']} cores, "
                    f"{machine['threads_per_query']} threads per query, load {machine['load_average_1_5_15']}"
                ),
                "",
                "## One million memories on this machine",
                "",
                f"- p50 {future['p50_seconds'] * 1000:.0f}ms · p95 {future['p95_seconds'] * 1000:.0f}ms",
                f"- vector table: {future['gibibytes']:.1f} GiB",
                f"- first build: {future['build_seconds'] / 60:.1f} minutes",
                f"- writing one memory: {future['write_p50_seconds'] * 1000:.0f}ms — a vec0 delete by id scans the table, so this grows with the count too",
                f"- assumption: {future['assumption']}",
                "",
                (
                    "_Latency is wall time per search on the machine named above with the thread budget the "
                    "benchmark pins; a run on a loaded machine is not comparable._"
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME)
    parser.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH)
    parser.add_argument("--probes", type=int, default=300)
    parser.add_argument("--model-dir", type=Path, default=MODELS / "paraphrase-multilingual-MiniLM-L12-v2")
    parser.add_argument("--out", type=Path, default=Path("bench/reports/DENSE.md"))
    parser.add_argument("--json-out", type=Path, default=Path("bench/reports/dense.json"))
    args = parser.parse_args()
    if args.probes <= 0:
        raise SystemExit(f"--probes must be positive, got {args.probes}")
    if not args.model_dir.is_dir():
        raise SystemExit(f"{args.model_dir}: no embedding snapshot, run python -m bench.fetch_models")

    report = measure(args.home, args.scratch, args.probes, args.model_dir)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(report, args.out)
    timing = report["latency"]
    print(
        f"{report['vectors']} vectors: build {report['build_seconds']:.1f}s, "
        f"search p50 {timing['p50'] * 1000:.1f}ms p95 {timing['p95'] * 1000:.1f}ms, "
        f"agreement {report['correctness']['tie_aware_agreement']:.3f}",
        flush=True,
    )


if __name__ == "__main__":
    main()
