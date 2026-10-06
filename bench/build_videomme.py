"""Build video-QA sets from Video-MME (lmms-eval/Video-MME).

Gold is the whole video: Video-MME annotators marked the correct option, not a
timestamp, so a timestamped gold region would be our own extraction rather than
a human judgement. Only videos whose file is actually on disk become queries,
and each domain is one memory holder so a question can also be asked of a
domain that never saw the clip.
"""

from __future__ import annotations

import json
import zipfile
from typing import Any

from pyarrow.parquet import ParquetFile

from bench.corpus_sources import source_for
from bench.sets_common import (
    DATA_ROOT,
    SETS,
    corpus_path,
    corpus_record,
    parse_json_array,
    query_record,
    safe_id,
    sample_by_holder,
    write_jsonl,
)

DATASET = "lmms-eval/Video-MME"
SOURCE = source_for(DATASET)
REVISION = str(SOURCE["revision"])
SNAPSHOT_AT = str(SOURCE["snapshot_at"])
PARQUET = "videomme/test-00000-of-00001.parquet"
CHUNKS = ("videos_chunked_01.zip", "videos_chunked_02.zip", "videos_chunked_03.zip")
CLIPS = DATA_ROOT / "videomme"
SCENARIO = "video-qa"


def extract_clips() -> dict[str, str]:
    """Unpack the chunk archives; videoID -> path relative to DATA_ROOT."""
    CLIPS.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    for chunk in CHUNKS:
        archive = corpus_path(DATASET, chunk)
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                if not info.filename.endswith(".mp4"):
                    continue
                name = info.filename.rsplit("/", 1)[-1]
                video_id = safe_id(name.removesuffix(".mp4"), f"{chunk} entry")
                target = CLIPS / f"{video_id}.mp4"
                if not target.is_file() or target.stat().st_size == 0:
                    with bundle.open(info) as source, target.open("wb") as sink:
                        while True:
                            block = source.read(1 << 22)
                            if not block:
                                break
                            sink.write(block)
                mapping[video_id] = target.relative_to(DATA_ROOT).as_posix()
    if not mapping:
        raise SystemExit("no mp4 entries found in the Video-MME archives")
    return mapping


def options_text(raw: Any, where: str) -> list[str]:
    options = raw if isinstance(raw, list) else parse_json_array(str(raw), where)
    return [str(option).strip() for option in options]


def domains_of(rows: list[dict[str, Any]]) -> dict[str, str]:
    """videoID -> domain, taken from the annotation table, never guessed."""
    domains: dict[str, str] = {}
    for row in rows:
        video_id = str(row["videoID"])
        domain = safe_id(
            str(row["domain"]).replace(" & ", "-").replace(" ", "-"), "domain"
        )
        known = domains.get(video_id)
        if known is not None and known != domain:
            raise SystemExit(f"video {video_id} is annotated in two domains: {known}, {domain}")
        domains[video_id] = domain
    return domains


def build() -> tuple[list, list, dict]:
    clips = extract_clips()
    rows = ParquetFile(corpus_path(DATASET, PARQUET)).read().to_pylist()
    domains = domains_of(rows)
    held = sorted(set(domains) & set(clips))
    if not held:
        raise SystemExit("no Video-MME annotation row matches a clip on disk")

    corpus = [
        corpus_record(
            source_id=f"videomme:{video_id}",
            modality="video",
            path=clips[video_id],
            title=video_id,
            observed_at=SNAPSHOT_AT,
            holder=domains[video_id],
            scenario=SCENARIO,
            root="derived",
        )
        for video_id in held
    ]

    queries: list[dict[str, Any]] = []
    for row in rows:
        video_id = str(row["videoID"])
        if video_id not in clips:
            continue
        where = f"{row['question_id']}"
        options = options_text(row["options"], where)
        question = str(row["question"]).strip()
        answer = str(row["answer"]).strip()
        if not question or not answer or not options:
            raise SystemExit(f"{where}: missing question, answer, or options")
        queries.append(
            query_record(
                query_id=f"videomme:{row['question_id']}",
                modality="video",
                question=f"{question}\n" + "\n".join(options),
                answer=answer,
                answer_format="mcq",
                gold=[{"source_id": f"videomme:{video_id}", "region": {}}],
                holder=domains[video_id],
                scenario=SCENARIO,
                as_of=SNAPSHOT_AT,
                origin={
                    "dataset": DATASET,
                    "revision": REVISION,
                    "item": f"question_id:{row['question_id']}",
                    "category": f"{row['domain']}/{row['task_type']}/{row['duration']}",
                },
            )
        )

    holders = sorted({record["holder"] for record in corpus})
    picked = sample_by_holder(queries)
    extras = []
    for query in picked:
        own = query["scope"]["holder"]
        other = holders[(holders.index(own) + 1) % len(holders)]
        extras.append(
            query_record(
                query_id=f"{query['query_id']}@{other}",
                modality="video",
                question=query["question"],
                answer=None,
                answer_format="mcq",
                gold=[],
                holder=other,
                scenario=SCENARIO,
                as_of=SNAPSHOT_AT,
                origin=query["origin"] | {"construction": "cross-holder"},
            )
        )

    report = {
        "datasets": [DATASET],
        "revision": REVISION,
        "annotated_videos": len({str(row["videoID"]) for row in rows}),
        "videos_on_disk": len(held),
        "questions_for_held_videos": len(queries),
        "holders": holders,
        "queries": len(picked) + len(extras),
        "queries_answerable": len(picked),
        "queries_cross_holder_unanswerable": len(extras),
        "by_duration": _counts(picked, "duration"),
    }
    return corpus, picked + extras, report


def _counts(queries: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for query in queries:
        parts = str(query["origin"]["category"]).split("/")
        key = parts[-1] if field == "duration" else parts[0]
        counts[key] = counts.get(key, 0) + 1
    return counts


def main() -> None:
    corpus, queries, report = build()
    corpus_count, corpus_sha = write_jsonl(SETS / "corpus" / "video.jsonl", corpus)
    _query_count, query_sha = write_jsonl(SETS / "video.jsonl", queries)
    report |= {"corpus_records": corpus_count, "corpus_sha256": corpus_sha, "queries_sha256": query_sha}
    (SETS / "reports").mkdir(parents=True, exist_ok=True)
    (SETS / "reports" / "video.json").write_text(
        json.dumps(report, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(report, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
