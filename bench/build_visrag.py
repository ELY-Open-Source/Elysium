"""Build image-retrieval sets from the six VisRAG-Ret test subsets.

Gold images come from the datasets' qrels (human relevance judgements). Each
subset is treated as one memory holder, which lets the builder also emit
cross-holder queries: the same question asked of a holder that never saw the
image must come back unanswerable.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pyarrow.parquet import ParquetFile

from bench.corpus_sources import SOURCES
from bench.sets_common import (
    DATA_ROOT,
    SETS,
    as_int,
    corpus_path,
    corpus_record,
    load_manifest,
    query_record,
    safe_segment,
    sample_by_holder,
    write_jsonl,
)

EXTRACTED = DATA_ROOT / "visrag"


def table(dataset: str, name: str) -> list[dict[str, Any]]:
    """Read every manifest shard under <name>/ for a dataset and concatenate rows."""
    prefix = f"{name}/"
    shards = sorted(
        row["path"]
        for row in load_manifest()
        if row["dataset"] == dataset
        and row["path"].startswith(prefix)
        and row["path"].endswith(".parquet")
    )
    if not shards:
        raise SystemExit(f"{dataset}: no {name} parquet shards in the frozen manifest")
    rows: list[dict[str, Any]] = []
    for path in shards:
        rows.extend(ParquetFile(corpus_path(dataset, path)).read().to_pylist())
    return rows


def clean(value: Any) -> str:
    """Parquet cells arrive as strings, numbers, or lists; normalise to plain text."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(clean(item) for item in value if item is not None)
    if not isinstance(value, str):
        value = str(value)
    text = value
    return (text or "").strip().strip("'\"")


def is_numerical(value: Any) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def image_name(corpus_id: str, raw: bytes) -> str:
    """Filesystem-safe name for an embedded image; corpus_id already carries an extension."""
    suffix = ".png" if raw[:4] == b"\x89PNG" else ".jpg"
    stem = corpus_id
    for known in (".jpg", ".jpeg", ".png"):
        if stem.lower().endswith(known):
            stem = corpus_id[: -len(known)]
            break
    if len(stem.encode()) > 120 or safe_segment(stem, f"corpus-id {corpus_id!r}") != stem:
        # Any character we would have to rewrite means the id is not filesystem-safe:
        # fall back to a digest so two ids can never land on the same file.
        stem = hashlib.sha256(corpus_id.encode()).hexdigest()[:20]
    return stem + suffix


def extract_images(dataset: str, subset: str) -> dict[str, str]:
    """Write embedded corpus images to disk; return corpus-id -> relative path."""
    target_dir = EXTRACTED / subset
    target_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    for row in table(dataset, "corpus"):
        corpus_id = clean(row["corpus-id"])
        image = row["image"]
        if not isinstance(image, dict) or not image.get("bytes"):
            raise SystemExit(f"{subset}: corpus row {corpus_id} has no embedded bytes")
        raw = image["bytes"]
        target = target_dir / image_name(corpus_id, raw)
        if not target.is_file() or target.stat().st_size == 0:
            target.write_bytes(raw)
        mapping[corpus_id] = target.relative_to(DATA_ROOT).as_posix()
    return mapping


def build_subset(dataset: str, revision: str, snapshot_at: str, subset: str) -> tuple[list, list, dict]:
    queries = table(dataset, "queries")
    qrels = table(dataset, "qrels")
    mapping = extract_images(dataset, subset)

    gold_by_query: dict[str, list[str]] = {}
    for row in qrels:
        if as_int(row["score"], f"{subset} qrels row") < 1:
            continue
        gold_by_query.setdefault(clean(row["query-id"]), []).append(clean(row["corpus-id"]))

    corpus = [
        corpus_record(
            source_id=f"visrag:{subset}:{corpus_id}",
            modality="image",
            path=relative,
            title=corpus_id,
            observed_at=snapshot_at,
            holder=subset,
            scenario="image-qa",
            root="derived",
        )
        for corpus_id, relative in sorted(mapping.items())
    ]

    records: list[dict[str, Any]] = []
    missing_images = 0
    for index, row in enumerate(queries):
        query_id = clean(row["query-id"])
        question = clean(row["query"])
        answer = clean(row["answer"])
        gold_ids = sorted(set(gold_by_query.get(query_id, [])))
        if not question or not gold_ids:
            continue
        unknown = [corpus_id for corpus_id in gold_ids if corpus_id not in mapping]
        if unknown:
            missing_images += 1
            continue
        records.append(
            query_record(
                query_id=f"visrag:{subset}:{index}",
                modality="image",
                question=question,
                answer=answer or None,
                answer_format=(
                    "none" if not answer else ("int" if is_numerical(row["is_numerical"]) else "str")
                ),
                gold=[
                    {"source_id": f"visrag:{subset}:{corpus_id}", "region": {}}
                    for corpus_id in gold_ids
                ],
                holder=subset,
                scenario="image-qa",
                as_of=snapshot_at,
                origin={"dataset": dataset, "revision": revision, "item": f"query:{index}"},
            )
        )

    report = {
        "dataset": dataset,
        "revision": revision,
        "queries_annotated": len(queries),
        "queries_usable": len(records),
        "corpus_images": len(mapping),
        "queries_dropped_missing_gold_image": missing_images,
    }
    return corpus, records, report


def cross_holder(queries: list[dict[str, Any]], holders: list[str]) -> list[dict[str, Any]]:
    """Ask each subset's questions of a holder that never saw its images."""
    extras: list[dict[str, Any]] = []
    for query in queries:
        own = query["scope"]["holder"]
        other = holders[(holders.index(own) + 1) % len(holders)]
        extras.append(
            query_record(
                query_id=f"{query['query_id']}@{other}",
                modality="image",
                question=query["question"],
                answer=None,
                answer_format="none",
                gold=[],
                holder=other,
                scenario="image-qa",
                as_of=query["as_of"],
                origin=query["origin"] | {"construction": "cross-holder"},
            )
        )
    return extras


def build() -> tuple[list, list, dict]:
    corpus: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    reports: dict[str, Any] = {}
    for source in SOURCES:
        dataset = source["dataset"]
        if not dataset.startswith("openbmb/VisRAG-Ret-Test-"):
            continue
        subset = dataset.split("/", 1)[1].removeprefix("VisRAG-Ret-Test-").lower()
        subset_corpus, subset_queries, report = build_subset(
            dataset, source["revision"], str(source["snapshot_at"]), subset
        )
        corpus.extend(subset_corpus)
        queries.extend(subset_queries)
        reports[subset] = report
    holders = sorted({record["holder"] for record in corpus})
    picked = sample_by_holder(queries)
    extras = cross_holder(picked, holders)
    report = {
        "datasets": sorted(
            {
                str(source["dataset"])
                for source in SOURCES
                if str(source["dataset"]).startswith("openbmb/VisRAG-Ret-Test-")
            }
        ),
        "subsets": reports,
        "holders": holders,
        "queries": len(picked) + len(extras),
        "queries_answerable": len(picked),
        "queries_cross_holder_unanswerable": len(extras),
    }
    return corpus, picked + extras, report


def main() -> None:
    corpus, queries, report = build()
    corpus_count, corpus_sha = write_jsonl(SETS / "corpus" / "image.jsonl", corpus)
    _query_count, query_sha = write_jsonl(SETS / "image.jsonl", queries)
    report |= {"corpus_records": corpus_count, "corpus_sha256": corpus_sha, "queries_sha256": query_sha}
    (SETS / "reports" / "image.json").parent.mkdir(parents=True, exist_ok=True)
    (SETS / "reports" / "image.json").write_text(json.dumps(report, indent=1, sort_keys=True))
    print(json.dumps({k: v for k, v in report.items() if k != "subsets"}, indent=1, sort_keys=True))
    for subset, detail in sorted(report["subsets"].items()):
        print(f"  {subset}: {detail['queries_usable']}/{detail['queries_annotated']} queries, "
              f"{detail['corpus_images']} images")


if __name__ == "__main__":
    main()
