"""Time the product's own search at the size the acceptance contract names.

The baseline recorded RetrievalService.search at p50 20.16s over 165,973 atoms because it
pulled every atom into Python and rebuilt a BM25 index per query. This check answers one
question with a number: what does the same call cost now, on the same corpus, on an idle
machine, with the same thread budget the benchmark pins?
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from bench.query_set import load_queries, scale_probes
from bench.report import git_commit
from bench.run import latency
from bench.systems import copy_store, machine_facts

DEFAULT_HOME = Path("bench/runs/baseline")
DEFAULT_SCRATCH = Path("bench/runs/scale")
MIN_ATOMS = 100_000
DEFAULT_PROBES = 300


def measure(home: Path, scratch: Path, probes: int) -> dict[str, Any]:
    """Open a copy of the product store (migrating it if it is old) and time real searches."""
    from ely_eye.config import Settings
    from ely_eye.db import Database
    from ely_eye.retrieval import RetrievalService

    copy_home, copy_seconds = copy_store(home, scratch)
    settings = Settings(home=copy_home)
    started = time.perf_counter()
    database = Database(settings)
    migration_seconds = time.perf_counter() - started
    atoms = database.atom_count()
    if atoms < MIN_ATOMS:
        raise SystemExit(f"{database.path}: {atoms} atoms, this check needs at least {MIN_ATOMS}")
    with database.connect() as connection:
        schema = int(connection.execute("PRAGMA user_version").fetchone()[0])
    print(f"{atoms} atoms copied in {copy_seconds:.1f}s, migrated in {migration_seconds:.1f}s", flush=True)

    queries = scale_probes(load_queries(), probes)
    service = RetrievalService(settings, database)
    service.search(queries[0].text)  # warm the index and any model before the first sample
    times: list[float] = []
    for query in queries:
        began = time.perf_counter()
        service.search(query.text)
        times.append(time.perf_counter() - began)
        if len(times) % 100 == 0:
            print(f"searched {len(times)}/{len(queries)}", flush=True)

    return {
        "commit": git_commit(),
        "database": str(database.path),
        "atoms": atoms,
        "copy_seconds": copy_seconds,
        "schema_version": schema,
        "migration_seconds": migration_seconds,
        "dense_embeddings_enabled": settings.dense_embeddings_enabled,
        "probes": len(queries),
        "probe_modalities": sorted({query.modality for query in queries}),
        "latency": latency(times),
        "machine": machine_facts(),
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    timing = report["latency"]
    machine = report["machine"]
    path.write_text(
        "\n".join(
            [
                "# SCALE: the product's own search at corpus size",
                "",
                f"- commit: `{report['commit']}`",
                f"- database: {report['database']}",
                (
                    f"- copied from the frozen baseline in {report['copy_seconds']:.1f}s and migrated "
                    f"in {report['migration_seconds']:.1f}s to schema {report['schema_version']}; "
                    "the baseline store itself is left untouched"
                ),
                (
                    f"- atoms: {report['atoms']}, probes: {report['probes']} "
                    f"({', '.join(report['probe_modalities'])})"
                ),
                f"- dense embeddings: {report['dense_embeddings_enabled']}",
                (
                    f"- p50 {timing['p50']:.4f}s · p95 {timing['p95']:.4f}s · max {timing['max']:.4f}s "
                    f"over {timing['queries']} queries"
                ),
                (
                    f"- machine: {machine['system']} {machine['release']}, {machine['cpus']} cores, "
                    f"{machine['threads_per_query']} threads per query, "
                    f"load {machine['load_average_1_5_15']}"
                ),
                "",
                "The baseline recorded p50 20.16s on this corpus because the old search pulled every",
                "atom into Python and rebuilt a BM25 index per query.",
                "",
                (
                    "_Latency is wall time per search call on an idle machine with the thread budget "
                    "the benchmark pins; a run on a loaded machine is not comparable._"
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
    parser.add_argument("--probes", type=int, default=DEFAULT_PROBES)
    parser.add_argument("--out", type=Path, default=Path("bench/reports/SCALE.md"))
    parser.add_argument("--json-out", type=Path, default=Path("bench/reports/scale.json"))
    args = parser.parse_args()
    if args.probes <= 0:
        raise SystemExit(f"--probes must be positive, got {args.probes}")

    report = measure(args.home, args.scratch, args.probes)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(report, args.out)
    timing = report["latency"]
    print(
        f"{report['atoms']} atoms, {report['probes']} probes: "
        f"p50 {timing['p50']:.4f}s p95 {timing['p95']:.4f}s",
        flush=True,
    )


if __name__ == "__main__":
    main()
