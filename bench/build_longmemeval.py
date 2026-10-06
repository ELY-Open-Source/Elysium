"""Build long-term-conversation sets from LongMemEval-S (xiaowu0162/longmemeval-cleaned).

Each item is one person's memory: ~53 chat sessions spread over weeks, with
human-written questions, the sessions that contain the evidence, and real
timestamps on every session. Where LongMemEval marks individual turns
has_answer=true the gold is turn-level; otherwise the gold is the whole
session, which is what a human actually annotated.
"""

from __future__ import annotations

import json
import re
from typing import Any

from bench.corpus_sources import source_for
from bench.sets_common import (
    DATA_ROOT,
    SETS,
    corpus_path,
    corpus_record,
    parse_json_array,
    query_record,
    safe_id,
    write_jsonl,
)

DATASET = "xiaowu0162/longmemeval-cleaned"
SOURCE = source_for(DATASET)
REVISION = str(SOURCE["revision"])
SOURCE_FILE = "longmemeval_s_cleaned.json"
SESSIONS = DATA_ROOT / "longmemeval"
SCENARIO = "assistant-memory"
PER_TYPE = 25
STAMP = re.compile(
    r"^(\d{4})[-/](\d{2})[-/](\d{2}) \([A-Za-z]{3}\) (\d{2}:\d{2})(?::(\d{2}))?$"
)


def parse_stamp(raw: str, where: str) -> str:
    """LongMemEval stamps are YYYY/MM/DD (Www) HH:MM; emit ISO-8601 UTC."""
    match = STAMP.match(raw.strip())
    if not match:
        raise SystemExit(f"{where}: unrecognised timestamp {raw!r}")
    year, month, day, clock, seconds = match.groups()
    return f"{year}-{month}-{day}T{clock}:{seconds or '00'}+00:00"


def load_items() -> list[dict[str, Any]]:
    path = corpus_path(DATASET, SOURCE_FILE)
    rows = parse_json_array(path.read_text(encoding="utf-8"), str(path))
    items = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SystemExit(f"{path}:{index}: expected a json object")
        items.append(row)
    if not items:
        raise SystemExit(f"{path}: no items")
    return items


def sample_by_type(items: list[dict[str, Any]], per_type: int = PER_TYPE) -> list[dict[str, Any]]:
    """Deterministic stratified pick across question_type so every category is measured."""
    by_type: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_type.setdefault(str(item["question_type"]), []).append(item)
    picked: list[dict[str, Any]] = []
    for category in sorted(by_type):
        rows = sorted(by_type[category], key=lambda row: str(row["question_id"]))
        step = max(1, len(rows) // per_type)
        picked.extend(rows[index] for index in range(0, len(rows), step)[:per_type])
    return picked


def materialize(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Write one JSONL file per session; return the corpus records for them."""
    question_id = safe_id(str(item["question_id"]), "longmemeval item")
    ids = item["haystack_session_ids"]
    dates = item["haystack_dates"]
    sessions = item["haystack_sessions"]
    if not (len(ids) == len(dates) == len(sessions)):
        raise SystemExit(f"{question_id}: session ids, dates and sessions disagree")
    records = []
    for raw_session_id, raw_date, turns in zip(ids, dates, sessions, strict=True):
        session_id = safe_id(str(raw_session_id), f"{question_id} session id")
        where = f"{question_id}/{session_id}"
        if not isinstance(turns, list) or not turns:
            raise SystemExit(f"{where}: expected a non-empty list of turns")
        target = SESSIONS / question_id / f"{session_id}.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for index, turn in enumerate(turns):
            if not isinstance(turn, dict) or "role" not in turn or "content" not in turn:
                raise SystemExit(f"{where}: turn {index} needs role and content")
            lines.append(json.dumps(turn, ensure_ascii=False, sort_keys=True))
        if not target.is_file():
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        records.append(
            corpus_record(
                source_id=f"lme:{question_id}:{session_id}",
                modality="conversation",
                path=target.relative_to(DATA_ROOT).as_posix(),
                title=f"{question_id} session {session_id}",
                observed_at=parse_stamp(str(raw_date), where),
                holder=question_id,
                scenario=SCENARIO,
                root="derived",
                extra={"turns": len(turns)},
            )
        )
    return records


def gold_regions(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn-level gold where LongMemEval labelled it, otherwise the whole session."""
    gold: list[dict[str, Any]] = []
    sessions = dict(zip(item["haystack_session_ids"], item["haystack_sessions"], strict=True))
    for session_id in item["answer_session_ids"]:
        turns = sessions.get(session_id)
        if turns is None:
            raise SystemExit(f"{item['question_id']}: answer session {session_id} not in haystack")
        marked = [
            index
            for index, turn in enumerate(turns)
            if isinstance(turn, dict) and turn.get("has_answer")
        ]
        if marked:
            gold.extend(
                {"source_id": f"lme:{item['question_id']}:{session_id}", "region": {"turn": index}}
                for index in marked
            )
        else:
            gold.append({"source_id": f"lme:{item['question_id']}:{session_id}", "region": {}})
    return gold


def as_of_for(
    item: dict[str, Any],
    item_corpus: list[dict[str, Any]],
    gold: list[dict[str, Any]],
    question_id: str,
) -> tuple[str, str, str]:
    """Return (question_date, as_of, basis) for one LongMemEval item.

    Some items timestamp their answer sessions after their own question_date, which
    would make the gold unreachable for a time-aware system, so as_of is the later of
    question_date and the newest gold session; every stamp is YYYY-MM-DDTHH:MM:SS+00:00,
    where lexicographic order matches chronological order.
    """
    asked_at = parse_stamp(str(item["question_date"]), question_id)
    gold_ids = {entry["source_id"] for entry in gold}
    newest = max(
        (record["observed_at"] for record in item_corpus if record["source_id"] in gold_ids),
        default=asked_at,
    )
    if newest > asked_at:
        return asked_at, newest, "newest_answer_session"
    return asked_at, asked_at, "question_date"


def unique_sessions(item: dict[str, Any]) -> bool:
    """Some LongMemEval items repeat a session id; two sources cannot share one identity."""
    ids = item["haystack_session_ids"]
    return len(set(ids)) == len(ids)


def build() -> tuple[list, list, dict]:
    all_items = load_items()
    usable = [item for item in all_items if unique_sessions(item)]
    items = sample_by_type(usable)
    corpus: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    turn_level = 0
    shifted_as_of = 0
    for item in items:
        question_id = str(item["question_id"])
        answer = str(item["answer"]).strip()
        if not answer:
            raise SystemExit(f"{question_id}: empty gold answer")
        item_corpus = materialize(item)
        corpus.extend(item_corpus)
        gold = gold_regions(item)
        if all(entry["region"] for entry in gold):
            turn_level += 1
        asked_at, as_of, basis = as_of_for(item, item_corpus, gold, question_id)
        if basis != "question_date":
            shifted_as_of += 1
        queries.append(
            query_record(
                query_id=f"lme:{question_id}",
                modality="conversation",
                question=str(item["question"]).strip(),
                answer=answer,
                answer_format="str",
                gold=gold,
                holder=question_id,
                scenario=SCENARIO,
                as_of=as_of,
                origin={
                    "dataset": DATASET,
                    "revision": REVISION,
                    "item": f"question_id:{question_id}",
                    "category": str(item["question_type"]),
                    "as_of_basis": basis,
                    "question_date": asked_at,
                },
            )
        )

    holders = sorted({query["scope"]["holder"] for query in queries})
    extras = []
    for index, query in enumerate(queries):
        other = holders[(index + 1) % len(holders)]
        extras.append(
            query_record(
                query_id=f"{query['query_id']}@{other}",
                modality="conversation",
                question=query["question"],
                answer=None,
                answer_format="none",
                gold=[],
                holder=other,
                scenario=SCENARIO,
                as_of=query["as_of"],
                origin=query["origin"] | {"construction": "cross-holder"},
            )
        )

    report = {
        "datasets": [DATASET],
        "revision": REVISION,
        "items_total": len(all_items),
        "items_dropped_duplicate_sessions": len(all_items) - len(usable),
        "items_sampled": len(items),
        "sessions": len(corpus),
        "holders": holders,
        "queries": len(queries) + len(extras),
        "queries_answerable": len(queries),
        "queries_cross_holder_unanswerable": len(extras),
        "queries_with_turn_level_gold": turn_level,
        "as_of_pushed_to_newest_answer_session": shifted_as_of,
        "by_category": _counts(queries),
    }
    return corpus, queries + extras, report


def _counts(queries: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for query in queries:
        category = str(query["origin"]["category"])
        counts[category] = counts.get(category, 0) + 1
    return counts


def main() -> None:
    corpus, queries, report = build()
    corpus_count, corpus_sha = write_jsonl(SETS / "corpus" / "conversation.jsonl", corpus)
    query_count, query_sha = write_jsonl(SETS / "conversation.jsonl", queries)
    report |= {"corpus_records": corpus_count, "corpus_sha256": corpus_sha, "queries_sha256": query_sha}
    (SETS / "reports").mkdir(parents=True, exist_ok=True)
    (SETS / "reports" / "conversation.json").write_text(
        json.dumps(report, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(report, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
