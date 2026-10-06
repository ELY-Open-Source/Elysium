"""Build the long-document QA set from MMLongBench-Doc (yubo2333/MMLongBench-Doc).

Gold pages are the dataset's human evidence_pages annotations. A document only
enters the corpus when every page its annotations reference exists in the file
Hugging Face actually served: upstream LFS storage returns the wrong blob for a
handful of documents, and that must not silently become a benchmark failure.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pyarrow.parquet import ParquetFile
from pypdf import PdfReader

from bench.corpus_sources import source_for
from bench.sets_common import (
    CORPUS,
    SETS,
    as_int,
    corpus_path,
    corpus_record,
    parse_json_object,
    query_record,
    safe_segment,
    write_jsonl,
)

DATASET = "yubo2333/MMLongBench-Doc"
SOURCE = source_for(DATASET)
REVISION = str(SOURCE["revision"])
SNAPSHOT_AT = str(SOURCE["snapshot_at"])
PARQUET = "data/train-00000-of-00001.parquet"
PAGE_MENTION = re.compile(r"pages?\s+(\d{1,4})(?:\s*(?:-|to|–)\s*(\d{1,4}))?", re.IGNORECASE)
CACHE = SETS / "_cache" / "mmlongbench_pages.json"


def pdf_pages(doc_id: str) -> int | None:
    """Page count of the served file, or None when the file is not parseable."""
    path = CORPUS / DATASET / "documents" / doc_id
    if not path.is_file():
        return None
    try:
        return len(PdfReader(path).pages)
    except Exception as exc:
        print(f"  unreadable pdf {doc_id}: {type(exc).__name__}: {exc}")
        return None


def page_counts(doc_ids: list[str]) -> dict[str, int | None]:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cached: dict[str, int | None] = {}
    if CACHE.is_file():
        cached = parse_json_object(CACHE.read_text(), str(CACHE))
    todo = [doc_id for doc_id in doc_ids if doc_id not in cached]
    if todo:
        print(f"  counting pages for {len(todo)} pdfs")
        for doc_id in todo:
            cached[doc_id] = pdf_pages(doc_id)
        CACHE.write_text(json.dumps(cached, indent=1, sort_keys=True) + "\n")
    return cached


def parse_pages(raw: str) -> list[int]:
    stripped = (raw or "").strip("[] ")
    if not stripped:
        return []
    return [as_int(part, f"evidence_pages {raw!r}") for part in stripped.split(",") if part.strip()]


def mentioned_pages(question: str) -> list[int]:
    pages: list[int] = []
    for first, second in PAGE_MENTION.findall(question):
        where = f"page mention in {question[:60]!r}"
        start = as_int(first, where)
        end = as_int(second, where) if second else start
        pages.extend(range(start, min(end, start + 400) + 1))
    return pages


def rows() -> list[dict[str, Any]]:
    table = ParquetFile(corpus_path(DATASET, PARQUET)).read()
    return table.to_pylist()


def doc_types(records: list[dict[str, Any]]) -> dict[str, str]:
    """doc_id -> holder. doc_type is the dataset's own human label for the document kind."""
    types: dict[str, str] = {}
    for row in records:
        slug = safe_segment(str(row["doc_type"]), "doc_type")
        known = types.get(str(row["doc_id"]))
        if known is not None and known != slug:
            raise SystemExit(
                f"doc {row['doc_id']} is annotated with two doc_types: {known}, {slug}"
            )
        types[str(row["doc_id"])] = slug
    return types


def build() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    records = rows()
    holders = doc_types(records)
    doc_ids = sorted({row["doc_id"] for row in records})
    counts = page_counts(doc_ids)

    needed: dict[str, int] = {}
    for row in records:
        referenced = set(parse_pages(row["evidence_pages"])) | set(mentioned_pages(row["question"]))
        if referenced:
            needed[row["doc_id"]] = max(needed.get(row["doc_id"], 0), max(referenced))

    usable = {
        doc_id
        for doc_id, top in needed.items()
        if (pages := counts.get(doc_id)) is not None and top <= pages
    }
    for doc_id, top in needed.items():
        if doc_id not in usable:
            print(f"  drop {doc_id}: annotations need page {top}, file has {counts.get(doc_id)}")

    corpus = [
        corpus_record(
            source_id=f"mmlongbench:{doc_id}",
            modality="pdf",
            path=f"{DATASET}/documents/{doc_id}",
            title=doc_id,
            observed_at=SNAPSHOT_AT,
            holder=holders[doc_id],
            scenario="document-qa",
            extra={"pages": counts.get(doc_id), "doc_type": holders[doc_id]},
        )
        for doc_id in sorted(usable)
    ]

    queries: list[dict[str, Any]] = []
    seen: set[str] = set()
    no_gold_pages = 0
    for index, row in enumerate(records):
        doc_id = row["doc_id"]
        if doc_id not in usable:
            continue
        question = (row["question"] or "").strip()
        if not question or question in seen:
            continue
        seen.add(question)
        answer = (row["answer"] or "").strip()
        unanswerable = answer in ("", "Not answerable")
        gold = [
            {"source_id": f"mmlongbench:{doc_id}", "region": {"page": page}}
            for page in parse_pages(row["evidence_pages"])
            if page <= (counts.get(doc_id) or 0)
        ]
        if unanswerable:
            gold = []
        elif not gold:
            no_gold_pages += 1
            continue
        queries.append(
            query_record(
                query_id=f"mmlongbench:{index}",
                modality="pdf",
                question=question,
                answer=None if unanswerable else answer,
                answer_format="none" if unanswerable else (row["answer_format"] or "str").lower(),
                gold=[] if unanswerable else gold,
                holder=holders[doc_id],
                scenario="document-qa",
                as_of=SNAPSHOT_AT,
                origin={
                    "dataset": DATASET,
                    "revision": REVISION,
                    "item": f"row:{index}",
                    "license": "not-stated-in-card",
                    **({"construction": "native unanswerable"} if unanswerable else {}),
                },
            )
        )

    report = {
        "datasets": [DATASET],
        "revision": REVISION,
        "annotation_rows": len(records),
        "documents_annotated": len(needed),
        "documents_usable": len(usable),
        "documents_dropped": sorted(set(needed) - usable),
        "queries": len(queries),
        "holders": sorted({record["holder"] for record in corpus}),
        "queries_dropped_no_evidence_page": no_gold_pages,
        "unanswerable": sum(1 for query in queries if query["unanswerable"]),
    }
    return corpus, queries, report


def main() -> None:
    corpus, queries, report = build()
    corpus_count, corpus_sha = write_jsonl(SETS / "corpus" / "pdf.jsonl", corpus)
    query_count, query_sha = write_jsonl(SETS / "pdf.jsonl", queries)
    report |= {"corpus_records": corpus_count, "corpus_sha256": corpus_sha, "queries_sha256": query_sha}
    (SETS / "reports" / "pdf.json").parent.mkdir(parents=True, exist_ok=True)
    (SETS / "reports" / "pdf.json").write_text(json.dumps(report, indent=1, sort_keys=True))
    print(json.dumps(report, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
