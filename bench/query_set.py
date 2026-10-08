"""The frozen query set: what is asked, who asks it, and which probes to time."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from bench.sets_common import MODALITIES, SETS, read_jsonl


@dataclass(frozen=True)
class Query:
    query_id: str
    text: str
    modality: str
    gold: frozenset[str]
    holder: str | None
    answerable: bool
    as_of: str | None



def load_queries(modalities: Sequence[str] = MODALITIES) -> list[Query]:
    """Every query the suite froze, in file order."""
    queries: list[Query] = []
    for modality in modalities:
        path = SETS / f"{modality}.jsonl"
        if not path.is_file():
            raise SystemExit(f"{path}: missing set, run python -m bench.build_sets first")
        for record in read_jsonl(path):
            gold = frozenset(hit["source_id"] for hit in record["gold"])
            answerable = not bool(record["unanswerable"])
            if answerable != bool(gold):
                raise SystemExit(
                    f"{path}: {record['query_id']} carries {len(gold)} gold hits but "
                    f"unanswerable={record['unanswerable']}"
                )
            queries.append(
                Query(
                    query_id=record["query_id"],
                    text=record["question"],
                    modality=modality,
                    gold=gold,
                    holder=record["scope"]["holder"],
                    answerable=answerable,
                    as_of=record.get("as_of"),
                )
            )
    if not queries:
        raise SystemExit("no queries loaded")
    return queries



def holder_index(modalities: Sequence[str] = MODALITIES) -> dict[str, str]:
    """source_id -> holder, from the corpus side of the suite."""
    holders: dict[str, str] = {}
    for modality in modalities:
        path = SETS / "corpus" / f"{modality}.jsonl"
        if not path.is_file():
            raise SystemExit(f"{path}: missing corpus index, run python -m bench.build_sets first")
        for record in read_jsonl(path):
            holders[record["source_id"]] = record["holder"]
    return holders



SCALE_PROBES = 40


def scale_probes(queries: Sequence[Query], count: int = SCALE_PROBES) -> list[Query]:
    """Queries to time at every corpus size.

    Latency does not need gold hits, and a truncated corpus keeps almost none of them,
    so selecting probes by gold would silently drop the small sizes entirely.
    """
    if count <= 0:
        raise SystemExit("the scale curve needs at least one probe query")
    answerable = [query for query in queries if query.answerable]
    if not answerable:
        raise SystemExit("the scale curve needs answerable queries")
    stride = max(1, len(answerable) // count)
    return answerable[::stride][:count]
