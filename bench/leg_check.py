"""What each retrieval leg is actually worth, on the frozen suite, asked as its holder.

The product fuses three legs with reciprocal rank fusion: a sparse page, a dense vector leg, and a
picture leg that only speaks up when the words come back thin. Each one costs latency and a model
snapshot, and the suite is the only honest referee. This harness turns each leg on and off over the
same probes and prints recall, first-hit quality, latency, and per-modality recall in one table, so
a default like `dense_embeddings_enabled=False` is a measurement rather than a preference.

Run: python -m bench.leg_check [--probes 300]
Writes: bench/reports/LEGS.md, bench/reports/leg_check.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from bench.metrics import aggregate, newest_gold_first, score_query
from bench.query_set import load_queries, scale_probes, source_times
from bench.report import git_commit
from bench.run import latency
from bench.scratch import copy_store
from bench.systems import machine_facts

DEFAULT_HOME = Path("bench/runs/dense_scale")
DEFAULT_SCRATCH = Path("bench/runs/leg_check")
DEFAULT_OBJECTS = Path("bench/runs/baseline/objects")
DEFAULT_CLIP_INDEX = Path("bench/runs/leg_check_index")
DEFAULT_CLIP_MODEL = Path("bench/models/chinese-clip-vit-base-patch16")
DEFAULT_EMBEDDING_MODEL = Path("bench/models/paraphrase-multilingual-MiniLM-L12-v2")
ENCODE_SAMPLE = 200

# The page the product asks for by default; measure() checks it against Settings, so "as shipped" cannot rot into a hypothesis.
SHIPPED_TOP_K = 24

# (label, atoms asked, dense leg, picture leg); the picture leg answers only on a thin page, which is the product's rule.
CONFIGS: list[dict[str, Any]] = [
    {"label": "words only", "top_k": 10, "dense": False, "visual": False},
    {"label": "words only (the configured 24)", "top_k": SHIPPED_TOP_K, "dense": False, "visual": False},
    {"label": "words only, wider page", "top_k": 30, "dense": False, "visual": False},
    {"label": "+ dense leg", "top_k": 10, "dense": True, "visual": False},
    {"label": "+ dense leg, wider page", "top_k": 30, "dense": True, "visual": False},
    {"label": "+ picture leg", "top_k": 10, "dense": False, "visual": True},
    {"label": "+ picture leg, wider page", "top_k": 30, "dense": False, "visual": True},
]


def prepare(
    home: Path,
    scratch: Path,
    objects: Path,
    clip_index: Path,
    *,
    dense: bool,
    visual: bool,
    clip_model: Path,
    embedding_model: Path,
) -> Path:
    """Build a scratch store that can run every leg: vectors, the picture index, and the bytes.

    The picture index and the CLIP snapshot are 48 minutes of encoding, so they are carried in from
    wherever they were built rather than rebuilt per row.
    """
    copy_home, _ = copy_store(home, scratch)
    if visual:
        for name in ("clip_image_index.npy", "clip_image_index_atoms.json"):
            source = clip_index / name
            if not source.exists():
                raise SystemExit(
                    f"{source}: the picture index has not been built; run `ely-eye index-visual` "
                    "with ELY_EYE_CLIP_MODEL_DIR set, or point --clip-index at its cache"
                )
            (copy_home / "cache").mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, copy_home / "cache" / name)
        if not (clip_model / "onnx" / "model_fp16.onnx").exists():
            raise SystemExit(f"{clip_model / 'onnx' / 'model_fp16.onnx'}: the CLIP snapshot is missing")
        if not objects.is_dir():
            raise SystemExit(f"{objects}: the picture leg needs the object store to check image bytes")
        link = copy_home / "objects"
        if not link.exists() and not link.is_symlink():
            link.symlink_to(objects.resolve())
    if dense and not (embedding_model / "config.json").exists():
        raise SystemExit(f"{embedding_model}: the embedding snapshot is missing; the dense leg cannot run")

    return copy_home


def _dense_vectors(store: Path) -> int:
    """Vectors the source store already carries, read without opening it for write."""
    import sqlite3

    import sqlite_vec
    from ely_eye import vector_index

    if vector_index.TABLE != "vec_atoms":
        raise SystemExit(f"the dense table is now {vector_index.TABLE}; update this harness's count")
    if not store.is_file():
        raise SystemExit(f"{store}: no product database")
    with sqlite3.connect(f"file:{store}?mode=ro", uri=True) as connection:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'vec_atoms'").fetchone():
            return 0
        return int(connection.execute("SELECT count(*) FROM vec_atoms").fetchone()[0])


def picture_facts(clip_index: Path) -> dict[str, Any]:
    """What the picture index really holds, read off the artifact instead of remembered in prose."""
    import numpy as np

    vectors_path = clip_index / "clip_image_index.npy"
    atoms_path = clip_index / "clip_image_index_atoms.json"
    vectors = np.load(vectors_path)
    with atoms_path.open(encoding="utf-8") as handle:
        try:
            atoms = json.load(handle)
        except json.JSONDecodeError as error:
            raise ValueError(f"{atoms_path}: the picture index's atom list is unreadable ({error})") from error
    if len(atoms) != int(vectors.shape[0]):
        raise SystemExit(
            f"{clip_index}: the picture index disagrees with itself — {len(atoms)} atom ids for "
            f"{vectors.shape[0]} vectors"
        )
    return {
        "path": str(clip_index),
        "atoms": len(atoms),
        "dim": int(vectors.shape[-1]),
        "bytes": int(vectors_path.stat().st_size),
    }


def encode_rate(clip_model: Path, objects: Path, count: int) -> dict[str, Any]:
    """Pictures per second the encoder manages, measured on a sample instead of remembered."""
    import time

    from ely_eye.clip_encoder import ClipEncoder
    from PIL import Image

    suffixes = {".png", ".jpg", ".jpeg"}
    sample = sorted(p for p in objects.rglob("*") if p.suffix.lower() in suffixes)[:count]
    if len(sample) < count:
        raise SystemExit(f"{objects}: only {len(sample)} pictures to time the encoder on")
    encoder = ClipEncoder(clip_model)
    began = time.perf_counter()
    rows = 0
    for start in range(0, len(sample), 8):
        batch = [Image.open(path).convert("RGB") for path in sample[start : start + 8]]
        rows += len(encoder.encode_images(batch))
    seconds = time.perf_counter() - began
    if rows != len(sample):
        raise SystemExit(f"the encoder returned {rows} vectors for {len(sample)} pictures")
    return {"pictures": rows, "seconds": seconds, "per_second": rows / seconds}


def _schema(home: Path) -> int:
    import sqlite3

    with sqlite3.connect(home / "data" / "ely_eye.sqlite") as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


def rank_all(service: Any, ids: dict[str, str], probes: list[Any], top_k: int) -> tuple[list[list[str]], list[int], list[float]]:
    """Ask the product as each probe's own holder and collapse atoms to sources by first hit."""
    from ely_eye.schemas import SearchFilters

    rankings: list[list[str]] = []
    distinct: list[int] = []
    timings: list[float] = []
    for index, query in enumerate(probes):
        began = time.perf_counter()
        hits = service.search(query.text, top_k=top_k, filters=SearchFilters(as_holder=query.holder)).hits
        timings.append(time.perf_counter() - began)
        sources: list[str] = []
        for hit in hits:
            source = ids[hit.atom.source_id]
            if source not in sources:
                sources.append(source)
        distinct.append(len(sources))
        rankings.append(sources)
        if (index + 1) % 100 == 0:
            print(f"    {index + 1}/{len(probes)}", flush=True)
    return rankings, distinct, timings


def _groups(
    answerable: list[Any], scores: list[Any], rankings: list[list[str]], times: dict[str, str]
) -> dict[str, Any]:
    """recall@10 by modality and by the question type the set recorded, plus who came back first."""
    by_modality: dict[str, list[float]] = {}
    by_category: dict[str, list[float]] = {}
    newest: dict[str, list[bool]] = {}
    every_newest: list[bool] = []
    for query, score, ranking in zip(answerable, scores, rankings, strict=True):
        by_modality.setdefault(query.modality, []).append(score.recall_at_10)
        by_category.setdefault(query.category or "unlabelled", []).append(score.recall_at_10)
        flag = newest_gold_first(ranking, set(query.gold), times)
        if flag is not None:
            newest.setdefault(query.category or "unlabelled", []).append(flag)
            every_newest.append(flag)
    return {
        "by_modality": {name: sum(rows) / len(rows) for name, rows in sorted(by_modality.items())},
        "modality_counts": {name: len(rows) for name, rows in sorted(by_modality.items())},
        "by_category": {name: sum(rows) / len(rows) for name, rows in sorted(by_category.items())},
        "category_counts": {name: len(rows) for name, rows in sorted(by_category.items())},
        "newest_gold_first": sum(every_newest) / len(every_newest) if every_newest else None,
        "newest_gold_first_by_category": {name: sum(rows) / len(rows) for name, rows in sorted(newest.items())},
        "newest_gold_first_counts": {name: len(rows) for name, rows in sorted(newest.items())},
    }


def measure(home: Path, scratch: Path, objects: Path, clip_index: Path, probes: int, models: dict[str, Path]) -> dict[str, Any]:
    """Score every configuration on the same probes, one warm service per configuration."""
    from ely_eye.config import Settings
    from ely_eye.db import Database
    from ely_eye.retrieval import RetrievalService

    shipped = Settings().retrieval_top_k
    if shipped != SHIPPED_TOP_K:
        raise SystemExit(
            f"the product asks for {shipped} atoms per search but this harness pins "
            f"SHIPPED_TOP_K={SHIPPED_TOP_K}; update the rows before trusting the 'as shipped' label"
        )

    chosen = scale_probes(load_queries(), probes)
    answerable = [query for query in chosen if query.gold]
    if not answerable:
        raise SystemExit("the frozen suite carries no answerable query; nothing to score")
    print(f"{len(answerable)} answerable probes", flush=True)
    times = source_times()

    vectors = _dense_vectors(home / "data" / "ely_eye.sqlite")
    if vectors == 0 and any(config["dense"] for config in CONFIGS):
        raise SystemExit(
            f"{home}: the store carries no dense vectors, so a dense arm here would rank an empty "
            "index and the 24-minute build would hide outside the measured latency. Build them with "
            "python -m bench.dense_scale, or point --home at a store that already has them."
        )

    arms: list[dict[str, Any]] = []
    picture: dict[str, Any] | None = None
    rate: dict[str, Any] | None = None
    schema = 0
    for config in CONFIGS:
        print(f"  {config['label']}: dense={config['dense']} visual={config['visual']}", flush=True)
        copy_home = prepare(
            home,
            scratch,
            objects,
            clip_index,
            dense=config["dense"],
            visual=config["visual"],
            clip_model=models["clip"],
            embedding_model=models["embedding"],
        )
        schema = _schema(copy_home)
        if config["visual"]:
            picture = picture_facts(clip_index)
            if rate is None:
                rate = encode_rate(models["clip"], objects, ENCODE_SAMPLE)
        settings = Settings(
            home=copy_home,
            dense_embeddings_enabled=config["dense"],
            embedding_model_dir=models["embedding"] if config["dense"] else None,
            clip_model_dir=models["clip"] if config["visual"] else None,
        )
        database = Database(settings)
        service = RetrievalService(settings=settings, database=database)
        ids = _source_ids(database)
        rankings, distinct, timings = rank_all(service, ids, answerable, int(config["top_k"]))
        scores = [
            score_query(query.query_id, ranking, set(query.gold), query.holder)
            for query, ranking in zip(answerable, rankings, strict=True)
        ]
        summary = aggregate(scores)
        timing = latency(timings)
        arms.append(
            {
                "label": config["label"],
                "top_k": config["top_k"],
                "dense": config["dense"],
                "visual": config["visual"],
                "recall_at_10": summary["recall_at_10"],
                "mrr": summary["mrr"],
                "hit_at_10": summary["hit_at_10"],
                "wilson_lower": summary["hit_at_10_wilson_lower"],
                "p50_seconds": timing["p50"],
                "p95_seconds": timing["p95"],
                "median_distinct_sources": statistics.median(distinct),
                **_groups(answerable, scores, rankings, times),
            }
        )
        print(
            f"    recall@10 {summary['recall_at_10']:.3f}, mrr {summary['mrr']:.3f}, "
            f"p50 {timing['p50'] * 1000:.1f}ms",
            flush=True,
        )
    return {
        "commit": git_commit(),
        "schema_version": schema,
        "store": str(scratch / "data" / "ely_eye.sqlite"),
        "source_store": str(home),
        "dense_vectors": vectors,
        "picture_index": picture,
        "encode_rate": rate,
        "probes": len(answerable),
        "arms": arms,
        "machine": machine_facts(),
    }


def _source_ids(database: Any) -> dict[str, str]:
    """Store source id to benchmark source id, the same mapping every other arm uses."""
    from bench.systems import _corpus_ids

    return _corpus_ids(database)


def write_markdown(report: dict[str, Any], path: Path) -> None:
    machine = report["machine"]
    header = [
        "| leg configuration | atoms asked | recall@10 | MRR | hit@10 | 95% lower | p50 ms | p95 ms | distinct sources |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    rows = []
    for arm in report["arms"]:
        rows.append(
            f"| {arm['label']} | {arm['top_k']} | {arm['recall_at_10']:.3f} | {arm['mrr']:.3f} | "
            f"{arm['hit_at_10']:.3f} | {arm['wilson_lower']:.3f} | {arm['p50_seconds'] * 1000:.1f} | "
            f"{arm['p95_seconds'] * 1000:.1f} | {arm['median_distinct_sources']} |"
        )
    modalities = sorted({modality for arm in report["arms"] for modality in arm["by_modality"]})
    modality_rows = [
        "| leg configuration | " + " | ".join(modalities) + " |",
        "| --- |" + " --- |" * len(modalities),
    ]
    for arm in report["arms"]:
        modality_rows.append(
            f"| {arm['label']} | "
            + " | ".join(f"{arm['by_modality'].get(modality, float('nan')):.3f}" for modality in modalities)
            + " |"
        )
    counts = report["arms"][0]["modality_counts"]

    def category_table(title: str, field: str, sizes_field: str) -> list[str]:
        """A table over the question types the sets label; unlabelled sets stay out of it."""
        names = sorted({name for arm in report["arms"] for name in arm[field] if name != "unlabelled"})
        if not names:
            return []
        lines = [
            f"## {title}",
            "",
            "| leg configuration | " + " | ".join(names) + " |",
            "| --- |" + " --- |" * len(names),
        ]
        for arm in report["arms"]:
            values, sizes = arm[field], arm[sizes_field]
            cells = []
            for name in names:
                if name not in values:
                    cells.append("—")
                elif field == "by_category":
                    cells.append(f"{values[name]:.3f}")
                else:
                    cells.append(f"{values[name]:.2f} ({sizes[name]})")
            lines.append(f"| {arm['label']} | " + " | ".join(cells) + " |")
        labelled = report["arms"][0][sizes_field]
        lines += [
            "",
            "_Queries per type: "
            + ", ".join(f"{name} {size}" for name, size in labelled.items() if name != "unlabelled")
            + "._",
        ]
        return lines
    path.write_text(
        "\n".join(
            [
                "# LEGS: what each retrieval leg is worth",
                "",
                f"- commit: `{report['commit']}`, schema v{report['schema_version']}",
                (
                    f"- store: {report['store']} — a copy of {report['source_store']}, which carries "
                    f"{report['dense_vectors']:,} dense vectors built by bench/dense_scale. The build "
                    "sits outside the measured latency, and the frozen baseline itself holds no "
                    "vectors, so a dense arm there would rank an empty index."
                ),
                f"- {report['probes']} answerable queries, each asked as the holder the frozen set assigns it",
                *(
                    []
                    if report.get("picture_index") is None
                    else [
                        (
                            f"- picture index: {report['picture_index']['atoms']:,} atoms at "
                            f"{report['picture_index']['dim']} dimensions, "
                            f"{report['picture_index']['bytes']:,} bytes, read from "
                            f"{report['picture_index']['path']}"
                        ),
                        (
                            f"- encoder speed: {report['encode_rate']['per_second']:.1f} pictures/s "
                            f"measured on {report['encode_rate']['pictures']} pictures, so the "
                            f"{report['picture_index']['atoms']:,} pictures in that index cost about "
                            f"{report['picture_index']['atoms'] / report['encode_rate']['per_second'] / 60:.1f} "
                            "minutes to encode"
                        ),
                    ]
                ),
                (
                    f"- machine: {machine['system']} {machine['release']}, {machine['cpus']} cores, "
                    f"{machine['threads_per_query']} threads per query, load {machine['load_average_1_5_15']}"
                ),
                "",
                "Recall is scored on the first ten **sources** after atoms are collapsed to their source",
                "by first hit, which is how every other arm in this repo is scored.",
                "",
                *header,
                *rows,
                "",
                "## recall@10 by modality",
                "",
                *modality_rows,
                "",
                f"_Query counts per modality: {', '.join(f'{name} {count}' for name, count in counts.items())}._",
                "",
                *category_table("recall@10 by question type", "by_category", "category_counts"),
                "",
                *category_table(
                    "the newest of the gold memories came back first",
                    "newest_gold_first_by_category",
                    "newest_gold_first_counts",
                ),
                "",
                (
                    "recall@10 counts any gold memory, so a knowledge-update question can score 1.000 "
                    "while the ranking still leads with the value the speaker has since replaced. The "
                    "table above asks the sharper question: when the answer lives in several dated "
                    "memories, is the newest one the first one returned? Only questions with at least two "
                    "dated gold memories and at least one returned are counted."
                ),
                "",
                (
                    "The picture leg is not a switch this harness flips per row: the product runs it only "
                    "when the sparse page comes back thin, so these rows measure the product with the leg "
                    "available, not a forced always-on fusion."
                ),
                "",
                (
                    "_Latency is wall time per search on the machine named above with the thread budget "
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
    parser.add_argument("--objects", type=Path, default=DEFAULT_OBJECTS)
    parser.add_argument("--clip-index", type=Path, default=DEFAULT_CLIP_INDEX)
    parser.add_argument("--clip-model", type=Path, default=DEFAULT_CLIP_MODEL)
    parser.add_argument("--embedding-model", type=Path, default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--probes", type=int, default=300)
    parser.add_argument("--out", type=Path, default=Path("bench/reports/LEGS.md"))
    parser.add_argument("--json-out", type=Path, default=Path("bench/reports/leg_check.json"))
    args = parser.parse_args()

    report = measure(
        args.home,
        args.scratch,
        args.objects,
        args.clip_index,
        args.probes,
        {"clip": args.clip_model, "embedding": args.embedding_model},
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(report, args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    if sys.version_info < (3, 11):
        raise SystemExit("bench needs Python 3.11+")
    main()
