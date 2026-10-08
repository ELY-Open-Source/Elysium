"""What each way of storing a vector actually buys: latency, recall past the ties, and bytes.

The product stores float32 today. This check answers, on the real corpus and with the thread
budget the benchmark pins, whether int8, a sign bit, or a shorter vector would buy anything —
and where the crossover is, so the answer does not have to be guessed at a million memories.
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import time
from pathlib import Path
from typing import Any

import numpy as np
import sqlite_vec

from bench.report import git_commit
from bench.run import latency
from bench.systems import machine_facts

DEFAULT_VECTORS = Path(
    "bench/runs/baseline/index/paraphrase-multilingual-MiniLM-L12-v2-7a66920843343254.npy"
)
PROBES = 200
TOP = 10
K = 10
COARSE = 200
SEED = 7
TRUNCATIONS = (192, 128, 64)
BYTES_PER_VECTOR = {"float32": 1536, "int8": 384, "bit": 48}


def load_matrix(path: Path) -> np.ndarray:
    if not path.is_file():
        raise SystemExit(f"{path}: no frozen vector matrix, build it with python -m bench.run")
    matrix = np.load(path)
    if matrix.ndim != 2:
        raise SystemExit(f"{path}: expected a matrix of vectors, got shape {matrix.shape}")
    return matrix


def tie_aware_hits(cosine: np.ndarray, threshold: np.ndarray, returned: list[int], probe: int) -> int:
    """The corpus holds byte-identical atoms, so the top-K id set is ambiguous: a returned atom
    counts when its true cosine is at least the k-th best, which is what a caller would accept."""
    return sum(1 for row in returned[:K] if cosine[row][probe] >= threshold[probe] - 1e-6)


def run_arm(
    name: str,
    arm: Any,
    count: int,
    warm: int,
    cosine: np.ndarray,
    threshold: np.ndarray,
) -> dict[str, Any]:
    for index in range(warm):
        arm(index)
    times: list[float] = []
    hits = 0
    for index in range(count):
        began = time.perf_counter()
        returned = arm(index)
        times.append(time.perf_counter() - began)
        hits += tie_aware_hits(cosine, threshold, returned, index)
    timing = latency(times)
    return {
        "arm": name,
        "queries": count,
        "p50_ms": round(timing["p50"] * 1000, 1),
        "p95_ms": round(timing["p95"] * 1000, 1),
        f"recall_at_{K}": round(hits / (count * K), 3),
    }


def vec_table(kind: str, count: int, dim: int, payload: Any) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.enable_load_extension(True)
    sqlite_vec.load(connection)
    if kind == "float":
        connection.executescript(
            f"""
            CREATE VIRTUAL TABLE vv USING vec0(
                embedding float[{dim}] distance_metric=cosine, atom_id text, holder_id text
            );
            """
        )
        insert = """
        INSERT INTO vv(rowid, embedding, atom_id, holder_id) VALUES (?, ?, ?, ?)
        """
    elif kind == "int8":
        connection.executescript(
            f"""
            CREATE VIRTUAL TABLE vv USING vec0(
                embedding int8[{dim}], atom_id text, holder_id text
            );
            """
        )
        insert = """
        INSERT INTO vv(rowid, embedding, atom_id, holder_id) VALUES (?, vec_int8(?), ?, ?)
        """
    else:
        connection.executescript(
            f"""
            CREATE VIRTUAL TABLE vv USING vec0(
                embedding bit[{dim}], atom_id text, holder_id text
            );
            """
        )
        insert = """
        INSERT INTO vv(rowid, embedding, atom_id, holder_id) VALUES (?, vec_bit(?), ?, ?)
        """
    for start in range(0, count, 20_000):
        stop = min(start + 20_000, count)
        connection.executemany(
            insert,
            [(row, payload(row), str(row), f"h{row % 2}") for row in range(start, stop)],
        )
    return connection


def knn(connection: sqlite3.Connection, kind: str, query: Any, top: int, holder: str | None = None) -> list[int]:
    """Nearest rowids. Every statement here is written out in full: the only choice is which one."""
    if holder is None:
        if kind == "float":
            rows = connection.execute(
                """
                SELECT rowid FROM vv WHERE embedding MATCH ? AND k = ? ORDER BY distance
                """,
                (query, top),
            ).fetchall()
        elif kind == "int8":
            rows = connection.execute(
                """
                SELECT rowid FROM vv WHERE embedding MATCH vec_int8(?) AND k = ? ORDER BY distance
                """,
                (query, top),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT rowid FROM vv WHERE embedding MATCH vec_bit(?) AND k = ? ORDER BY distance
                """,
                (query, top),
            ).fetchall()
    elif kind == "float":
        rows = connection.execute(
            """
            SELECT rowid FROM vv WHERE embedding MATCH ? AND k = ? AND holder_id = ? ORDER BY distance
            """,
            (query, top, holder),
        ).fetchall()
    elif kind == "int8":
        rows = connection.execute(
            """
            SELECT rowid FROM vv WHERE embedding MATCH vec_int8(?) AND k = ? AND holder_id = ? ORDER BY distance
            """,
            (query, top, holder),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT rowid FROM vv WHERE embedding MATCH vec_bit(?) AND k = ? AND holder_id = ? ORDER BY distance
            """,
            (query, top, holder),
        ).fetchall()
    return [int(row[0]) for row in rows]


def measure(vectors: np.ndarray, probes: int) -> dict[str, Any]:
    count, dim = vectors.shape
    if probes > count:
        raise SystemExit(f"--probes {probes} exceeds the {count} vectors in the corpus")
    chosen = random.Random(SEED).sample(range(count), probes)
    queries = vectors[chosen].copy()
    cosine = vectors @ queries.T
    threshold = -np.sort(-cosine, axis=0)[K - 1]

    int8 = np.ascontiguousarray(np.clip(np.round(vectors * 127), -127, 127).astype(np.int8))
    queries_int8 = np.ascontiguousarray(np.clip(np.round(queries * 127), -127, 127).astype(np.int8))
    packed = np.packbits((vectors >= 0).astype(np.uint8), axis=1)
    queries_packed = np.packbits((queries >= 0).astype(np.uint8), axis=1)
    unpacked = np.unpackbits(packed, axis=1)
    queries_unpacked = np.unpackbits(queries_packed, axis=1)
    population = unpacked.sum(axis=1).astype(np.int32)

    rows: list[dict[str, Any]] = []
    tables: dict[str, sqlite3.Connection] = {}
    for kind, payload, query_bytes in (
        ("float", lambda row: vectors[row].tobytes(), lambda probe: queries[probe].tobytes()),
        ("int8", lambda row: int8[row].tobytes(), lambda probe: queries_int8[probe].tobytes()),
        ("bit", lambda row: packed[row].tobytes(), lambda probe: queries_packed[probe].tobytes()),
    ):
        tables[kind] = vec_table(kind, count, dim, payload)
        rows.append(
            run_arm(
                f"sqlite-vec {kind}",
                lambda probe, kind=kind, query_bytes=query_bytes: knn(tables[kind], kind, query_bytes(probe), TOP),
                probes,
                20,
                cosine,
                threshold,
            )
        )
        rows.append(
            run_arm(
                f"sqlite-vec {kind} + holder filter",
                lambda probe, kind=kind, query_bytes=query_bytes: knn(
                    tables[kind], kind, query_bytes(probe), TOP, holder="h0"
                ),
                probes,
                20,
                cosine,
                threshold,
            )
        )

    rows.append(
        run_arm(
            "numpy float32 scan (the truth)",
            lambda probe: list(np.argsort(-(vectors @ queries[probe]))[:TOP]),
            probes,
            10,
            cosine,
            threshold,
        )
    )

    def hamming(probe: int) -> list[int]:
        shared = unpacked @ queries_unpacked[probe]
        return list(np.argsort(-(2 * shared - population))[:TOP])

    rows.append(run_arm("numpy hamming (sign bit)", hamming, probes, 10, cosine, threshold))

    for dims in TRUNCATIONS:
        rows.append(
            run_arm(
                f"numpy float32 first {dims} dims",
                lambda probe, dims=dims: list(np.argsort(-(vectors[:, :dims] @ queries[probe][:dims]))[:TOP]),
                min(probes, 50),
                5,
                cosine,
                threshold,
            )
        )

    def rerank_outside(probe: int) -> list[int]:
        coarse = knn(tables["bit"], "bit", queries_packed[probe].tobytes(), COARSE)
        order = np.argsort(-(vectors[coarse] @ queries[probe]))[:TOP]
        return [coarse[row] for row in order]

    rows.append(run_arm(f"bit coarse@{COARSE} -> float32 rerank in numpy", rerank_outside, probes, 10, cosine, threshold))

    return {
        "commit": git_commit(),
        "vectors": count,
        "dimensions": dim,
        "probes": probes,
        "top_k": TOP,
        "recall_note": (
            "probes are drawn from the corpus itself, so these arms are compared with each other, "
            "not quoted as retrieval quality; a hit is any returned atom whose true cosine is at "
            f"least the {K}-th best, because byte-identical atoms make the id set ambiguous"
        ),
        "bytes_per_vector": BYTES_PER_VECTOR,
        "arms": rows,
        "machine": machine_facts(),
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    machine = report["machine"]
    lines = [
        f"# QUANT: what each vector encoding buys (commit {report['commit'][:9]})",
        "",
        (
            f"- corpus: {report['vectors']} vectors, {report['dimensions']} dimensions, "
            f"{report['probes']} probes, top {report['top_k']}"
        ),
        (
            f"- machine: {machine['system']} {machine['release']}, {machine['cpus']} cores, "
            f"{machine['threads_per_query']} threads per query, load {machine['load_average_1_5_15']}"
        ),
        f"- {report['recall_note']}",
        "",
        f"| arm | p50 ms | p95 ms | recall@{K} |",
        "| --- | --- | --- | --- |",
    ]
    for row in report["arms"]:
        lines.append(
            f"| {row['arm']} | {row['p50_ms']} | {row['p95_ms']} | {row[f'recall_at_{K}']} |"
        )
    lines += [
        "",
        "| encoding | bytes per vector |",
        "| --- | --- |",
    ]
    lines += [f"| {name} | {size} |" for name, size in report["bytes_per_vector"].items()]
    lines += [
        "",
        (
            "_Latency is wall time per query on the machine named above with the thread budget the "
            "benchmark pins; a run on a loaded machine is not comparable._"
        ),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vectors", type=Path, default=DEFAULT_VECTORS)
    parser.add_argument("--probes", type=int, default=PROBES)
    parser.add_argument("--out", type=Path, default=Path("bench/reports/QUANT.md"))
    parser.add_argument("--json-out", type=Path, default=Path("bench/reports/quant.json"))
    args = parser.parse_args()
    if args.probes <= 0:
        raise SystemExit(f"--probes must be positive, got {args.probes}")

    report = measure(load_matrix(args.vectors), args.probes)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(report, args.out)
    for row in report["arms"]:
        print(f"{row['arm']:42} p50 {row['p50_ms']:7.1f}ms  recall@{K} {row[f'recall_at_{K}']}", flush=True)


if __name__ == "__main__":
    main()
