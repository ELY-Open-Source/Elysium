"""Prove the generated sets are schema-clean, solvable, and honest about their gold.

A benchmark is only worth running if its answers are reachable: every answerable
query must name a corpus source that exists, belongs to the holder being asked,
and was observed no later than the moment the question was asked. Unanswerable
queries must say how they were made unanswerable.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any

from bench.sets_common import (
    MODALITIES,
    SETS,
    read_jsonl,
    sha256_file,
    validate_corpus,
    validate_query,
)

MAX_REPORTED = 20


def parse_time(value: str, where: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise SystemExit(f"{where}: unparseable timestamp {value!r}") from error


def check_modality(modality: str, problems: list[str]) -> dict[str, int]:
    corpus = list(read_jsonl(SETS / "corpus" / f"{modality}.jsonl"))
    queries = list(read_jsonl(SETS / f"{modality}.jsonl"))
    sources: dict[str, dict[str, Any]] = {}
    for record in corpus:
        problems.extend(f"{modality} corpus {record.get('source_id')}: {p}" for p in validate_corpus(record))
        source_id = str(record["source_id"])
        if source_id in sources:
            problems.append(f"{modality} corpus: duplicate source_id {source_id}")
        sources[source_id] = record

    query_ids: set[str] = set()
    answerable = 0
    for query in queries:
        where = f"{modality} query {query.get('query_id')}"
        problems.extend(f"{where}: {p}" for p in validate_query(query))
        query_id = str(query["query_id"])
        if query_id in query_ids:
            problems.append(f"{modality}: duplicate query_id {query_id}")
        query_ids.add(query_id)

        if query["unanswerable"]:
            if not query["origin"].get("construction"):
                problems.append(f"{where}: unanswerable query does not say how it was built")
            continue
        answerable += 1
        asked_at = parse_time(query["as_of"], where)
        for gold in query["gold"]:
            source = sources.get(gold["source_id"])
            if source is None:
                problems.append(f"{where}: gold names {gold['source_id']}, absent from the corpus")
                continue
            if source["holder"] != query["scope"]["holder"]:
                problems.append(
                    f"{where}: gold {gold['source_id']} lives with holder {source['holder']}, "
                    f"but the query asks holder {query['scope']['holder']}"
                )
            observed = parse_time(source["observed_at"], f"{where} gold {gold['source_id']}")
            if observed > asked_at:
                problems.append(
                    f"{where}: gold {gold['source_id']} was observed {source['observed_at']}, "
                    f"after the question was asked at {query['as_of']}"
                )
    return {
        "corpus": len(corpus),
        "queries": len(queries),
        "answerable": answerable,
        "unanswerable": len(queries) - answerable,
        "holders": len({record["holder"] for record in corpus}),
    }


def check_manifest(table: dict[str, dict[str, int]], problems: list[str]) -> None:
    """The frozen manifest must still describe the files on disk."""
    path = SETS / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        problems.append(f"{path}: missing; run bench.build_sets")
        return
    except (OSError, json.JSONDecodeError) as error:
        problems.append(f"{path}: unreadable: {error}")
        return
    for modality, row in manifest["modalities"].items():
        for field, location in (("corpus", row["corpus_file"]), ("queries", row["queries_file"])):
            digest = sha256_file(SETS / location)
            if digest != row[f"{field}_sha256"]:
                problems.append(
                    f"{path}: {location} digest {digest[:12]} no longer matches the manifest "
                    f"{row[f'{field}_sha256'][:12]}; the suite was rebuilt without re-freezing"
                )
        if row["corpus_records"] != table[modality]["corpus"]:
            problems.append(
                f"{path}: {modality} manifest says {row['corpus_records']} sources, "
                f"file holds {table[modality]['corpus']}"
            )
        if row["queries"] != table[modality]["queries"]:
            problems.append(
                f"{path}: {modality} manifest says {row['queries']} queries, "
                f"file holds {table[modality]['queries']}"
            )


def main() -> int:
    problems: list[str] = []
    table: dict[str, dict[str, int]] = {}
    for modality in MODALITIES:
        table[modality] = check_modality(modality, problems)

    totals = {key: sum(row[key] for row in table.values()) for key in table[MODALITIES[0]]}
    print(json.dumps({"modalities": table, "totals": totals}, indent=1, sort_keys=True))
    if totals["answerable"] < 300:
        problems.append(f"only {totals['answerable']} answerable queries; the plan demands at least 300")
    check_manifest(table, problems)

    if problems:
        for problem in problems[:MAX_REPORTED]:
            print(f"PROBLEM {problem}", file=sys.stderr)
        print(f"{len(problems)} problem(s) total", file=sys.stderr)
        return 1
    print(f"OK: {totals['corpus']} sources, {totals['answerable']} answerable queries, "
          f"{totals['unanswerable']} unanswerable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
