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
    category: str | None = None



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
                    category=(record.get("origin") or {}).get("category"),
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



def source_times(modalities: Sequence[str] = MODALITIES) -> dict[str, str]:
    """source_id -> when that source says it happened, from the corpus side of the suite."""
    times: dict[str, str] = {}
    for modality in modalities:
        path = SETS / "corpus" / f"{modality}.jsonl"
        if not path.is_file():
            raise SystemExit(f"{path}: missing corpus index, run python -m bench.build_sets first")
        for record in read_jsonl(path):
            observed = record.get("observed_at")
            if observed:
                times[record["source_id"]] = str(observed)
    return times



SCALE_PROBES = 40


def _shares(pools: dict[str, list[Query]], count: int) -> dict[str, int]:
    """How many probes each modality gets: its share of the suite, never zero when there is room."""
    names = sorted(pools)
    total = sum(len(pools[name]) for name in names)
    exact = {name: count * len(pools[name]) / total for name in names}
    share = {name: int(exact[name]) for name in names}
    short = count - sum(share.values())
    for name in sorted(names, key=lambda name: (-(exact[name] - int(exact[name])), name))[:short]:
        share[name] += 1
    if count >= len(names):
        for name in names:
            while share[name] == 0:
                donor = max((other for other in names if share[other] > 1), key=lambda other: share[other])
                share[donor] -= 1
                share[name] += 1
    return {name: min(share[name], len(pools[name])) for name in names}


def scale_probes(queries: Sequence[Query], count: int = SCALE_PROBES) -> list[Query]:
    """Queries to time at every corpus size.

    Latency does not need gold hits, and a truncated corpus keeps almost none of them,
    so selecting probes by gold would silently drop the small sizes entirely. The budget is then
    split across modalities by suite weight: one stride over file order truncated the tail and
    timed 300 probes that held no conversation query at all.
    """
    if count <= 0:
        raise SystemExit("the scale curve needs at least one probe query")
    pools: dict[str, list[Query]] = {}
    for query in queries:
        if query.answerable:
            pools.setdefault(query.modality, []).append(query)
    if not pools:
        raise SystemExit("the scale curve needs answerable queries")
    shares = _shares(pools, count)
    chosen: list[Query] = []
    for modality in sorted(pools):
        if shares[modality] == 0:
            continue
        pool = pools[modality]
        stride = max(1, len(pool) // shares[modality])
        chosen.extend(pool[::stride][: shares[modality]])
    return chosen
