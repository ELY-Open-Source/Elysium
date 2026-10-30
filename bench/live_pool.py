"""The pool the three live systems share: test questions per modality, each holder's gold plus distractors.

Real Mem0 writes through an LLM, and one PDF or video holder carries 10,000+ atoms, so no holder
can be given to it whole. Per modality this draws holders, then test questions inside them,
seeded; each drawn holder keeps the gold of its drawn questions plus seeded distractors from its own
sources, up to SPEC's pool size. The Elysium store is a copy of the undescribed speech store cut down
to the pool and described by the product, so every system reads the same words, and the token cost of
those descriptions is Elysium's ingest cost. Chance is a random ranking of each holder's pool.
"""

from __future__ import annotations

import json
import random
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from bench.counterpart import load_source_index
from bench.describe_check import DEFAULT_OBJECTS, describe_copy, link_objects
from bench.ingest_baseline import source_map
from bench.query_set import Query, load_queries
from bench.scratch import copy_store
from bench.stamp_holders import stamp
from bench.vllm_counters import counters, spent

UNDESCRIBED = Path("bench/runs/video_audio_speech")
SEED = 0
CHUNK_CHARS = 8000
# modality: (holders drawn, questions drawn, sources per holder's pool)
SPEC = {
    "code": (20, 20, 30),
    "conversation": (10, 10, 20),
    "image": (2, 20, 60),
    "pdf": (2, 20, 12),
    "ui_screenshot": (2, 20, 60),
    "video": (2, 20, 12),
}


def draw(queries: list[Query], index: dict[str, Any]) -> tuple[list[Query], dict[str, list[str]]]:
    """Seeded holders, then seeded questions inside them, then each holder's gold plus distractors."""
    rng = random.Random(SEED)
    by_holder: dict[str, list[str]] = defaultdict(list)
    for meta in index.values():
        by_holder[meta.holder].append(meta.source_id)
    probes: list[Query] = []
    pools: dict[str, list[str]] = {}
    for modality, (holders, asked, size) in SPEC.items():
        tested = [query for query in queries if query.gold and query.split == "test" and query.modality == modality]
        names = sorted({str(query.holder) for query in tested})
        rng.shuffle(names)
        chosen = [query for query in tested if query.holder in set(names[:holders])]
        drawn = rng.sample(chosen, min(asked, len(chosen)))
        probes += drawn
        for holder in sorted({str(query.holder) for query in drawn}):
            gold = sorted({source for query in drawn if query.holder == holder for source in query.gold})
            rest = sorted(set(by_holder[holder]) - set(gold))
            rng.shuffle(rest)
            pools[holder] = gold + rest[: max(0, size - len(gold))]
    return probes, pools


def chance(probes: list[Query], pools: dict[str, list[str]]) -> float:
    """Expected recall@10 of a random ranking of the asker's pool."""
    return sum(min(10, len(pools[str(query.holder)])) / len(pools[str(query.holder)]) for query in probes) / len(probes)


def build_store(scratch: Path, pools: dict[str, list[str]], vllm: str, workers: int) -> dict[str, Any]:
    """The undescribed store cut to the pool through the product's own delete, stamped, then described."""
    from elysium.config import Settings
    from elysium.db import Database

    home, _ = copy_store(UNDESCRIBED, scratch)
    # Linked before the store is opened, which would make an objects directory of its own.
    link_objects(home, DEFAULT_OBJECTS)
    keep = {path for path, source in source_map().items() if source in {s for pool in pools.values() for s in pool}}
    database = Database(Settings(home=home))
    with database.connect() as connection:
        rows = connection.execute("SELECT a.atom_id, s.path FROM atoms a JOIN sources s ON s.source_id = a.source_id").fetchall()
    database.delete_atoms([str(atom_id) for atom_id, path in rows if str(path) not in keep])
    stamped = stamp(home / "data" / "elysium.sqlite")
    before = counters(vllm)
    described = describe_copy(home, workers)
    return {"home": str(home), "stamped": stamped, "described": described, "tokens": spent(before, counters(vllm))}


def items(home: Path, pools: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Each pool source's atoms in order, joined and cut at CHUNK_CHARS: what Mem0 is given."""
    corpus_id = source_map()
    index = load_source_index()
    with sqlite3.connect(f"file:{home / 'data' / 'elysium.sqlite'}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT s.path, a.text FROM atoms a JOIN sources s ON s.source_id = a.source_id ORDER BY s.path, a.rowid"
        ).fetchall()
    texts: dict[str, list[str]] = defaultdict(list)
    for path, text in rows:
        if text:
            texts[corpus_id[str(path)]].append(str(text))
    out: list[dict[str, Any]] = []
    for holder, sources in pools.items():
        for source in sources:
            whole = "\n".join(texts.get(source, []))
            for number, start in enumerate(range(0, len(whole), CHUNK_CHARS)):
                meta = index[source]
                out.append({
                    "item_id": f"{source}#{number}",
                    "source_id": source,
                    "holder": holder,
                    "modality": meta.modality,
                    "observed_at": meta.observed_at,
                    "text": whole[start : start + CHUNK_CHARS],
                })
    return out


def build(scratch: Path, vllm: str, workers: int) -> dict[str, Any]:
    """Draw the pool, build and describe Elysium's store, and write what the other two are given."""
    probes, pools = draw(load_queries(), load_source_index())
    store = build_store(scratch / "elysium", pools, vllm, workers)
    given = items(Path(store["home"]), pools)
    empty = sorted({s for pool in pools.values() for s in pool} - {item["source_id"] for item in given})
    pool = {
        "seed": SEED,
        "spec": SPEC,
        "chunk_chars": CHUNK_CHARS,
        "probes": [query.query_id for query in probes],
        "pools": pools,
        "sources_without_text": empty,
        "chance_recall_at_10": chance(probes, pools),
        "elysium_store": store,
        "items": given,
    }
    (scratch / "pool.json").write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    return pool
