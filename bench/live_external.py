"""Real Mem0 on the shared pool, with the local 9B as its LLM.

Runs in `.venv-external` (mem0ai, fastembed, spaCy; Qdrant in Docker); it never imports elysium. Every
item of `pool.json` goes in through Mem0's own `add()`, without and with LLM inference. Items of one
source go in one after another; sources run side by side, since one PDF holder alone holds 835 items.
Token cost is read from vLLM's counters around each phase, so nothing else may use that server while
this runs. Each arm writes the source ids it ranked per question to `external_mem0.json`.

Run: MEM0_TELEMETRY=False .venv-external/bin/python -m bench.live_external --pool bench/runs/live/pool.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from bench.query_set import load_queries
from bench.vllm_counters import counters, spent

EMBEDDER = Path("bench/models/paraphrase-multilingual-MiniLM-L12-v2").resolve()
MODEL = "Qwen/Qwen3.5-9B"
LIMIT = 24
AT_ONCE = 32


def require_quiet_telemetry() -> None:
    """Mem0 phones home by default; a benchmark of private memories must not."""
    if os.environ.get("MEM0_TELEMETRY", "").lower() != "false":
        raise SystemExit("set MEM0_TELEMETRY=False before running")


def by_source(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[item["source_id"]].append(item)
    return grouped


def ranked_sources(source_ids: Iterable[str | None]) -> list[str]:
    out: list[str] = []
    for source in source_ids:
        if source and source not in out:
            out.append(source)
    return out


def mem0_memory(home: Path, rerank_url: str | None) -> Any:
    """A Qdrant server, as Mem0 is deployed: its local mode breaks under threads. Each run starts empty."""
    from mem0 import Memory
    from qdrant_client import QdrantClient

    QdrantClient(host="127.0.0.1", port=6333).delete_collection(home.name)
    home.mkdir(parents=True, exist_ok=True)
    (home / "history.db").unlink(missing_ok=True)

    llm = {"model": MODEL, "openai_base_url": URL, "api_key": "local", "temperature": 0.0}
    config: dict[str, Any] = {
        "llm": {"provider": "openai", "config": llm},
        "embedder": {"provider": "huggingface", "config": {"model": str(EMBEDDER), "embedding_dims": 384}},
        "vector_store": {"provider": "qdrant", "config": {"host": "127.0.0.1", "port": 6333, "collection_name": home.name, "embedding_model_dims": 384}},
        "history_db_path": str(home / "history.db"),
    }
    if rerank_url is not None:
        config["reranker"] = {"provider": "llm_reranker", "config": {"model": MODEL, "api_key": "local", "llm": {"provider": "openai", "config": llm}}}
    return Memory.from_config(config)


def mem0_write(memory: Any, items: list[dict[str, Any]], infer: bool) -> dict[str, Any]:
    failed: list[str] = []

    def source_items(group: list[dict[str, Any]]) -> int:
        for item in group:
            try:
                memory.add([{"role": "user", "content": item["text"]}], user_id=item["holder"], metadata={"source_id": item["source_id"]}, infer=infer)
            except Exception as error:  # noqa: BLE001  # a write the library cannot make is a measured outcome
                failed.append(f"{item['item_id']}: {error}"[:300])
        return len(group)

    phase = timed_phase(lambda: sum(ThreadPoolExecutor(AT_ONCE).map(source_items, by_source(items).values())))
    return {**phase, "failed": failed}


def mem0_rank(memory: Any, probes: list[Any], rerank: bool) -> dict[str, Any]:
    def ask(query: Any) -> tuple[str, list[str], float]:
        began = time.perf_counter()
        found = memory.search(query.text, top_k=LIMIT, filters={"user_id": query.holder}, threshold=0.0, rerank=rerank)["results"]
        return query.query_id, ranked_sources(hit.get("metadata", {}).get("source_id") for hit in found), time.perf_counter() - began

    return timed_phase(lambda: [ask(query) for query in probes])


def timed_phase(work: Callable[[], Any]) -> dict[str, Any]:
    before = counters(URL)
    began = time.perf_counter()
    result = work()
    return {"result": result, "seconds": time.perf_counter() - began, "tokens": spent(before, counters(URL))}


def arm(name: str, write: dict[str, Any] | None, ranked: dict[str, Any], items: int) -> dict[str, Any]:
    return {
        "arm": name,
        "items_written": items,
        "write": None if write is None else {"seconds": write["seconds"], "tokens": write["tokens"], "failed": write["failed"]},
        "query": {"seconds": ranked["seconds"], "tokens": ranked["tokens"]},
        "rankings": {query_id: sources for query_id, sources, _ in ranked["result"]},
        "latency": [seconds for _, _, seconds in ranked["result"]],
    }


def main(argv: list[str] | None = None) -> int:
    global URL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--vllm", default="http://127.0.0.1:8001/v1")
    arguments = parser.parse_args(argv)
    require_quiet_telemetry()
    URL = arguments.vllm
    pool = json.loads(arguments.pool.read_text(encoding="utf-8"))
    wanted = set(pool["probes"])
    probes = [query for query in load_queries() if query.query_id in wanted]
    items = pool["items"]
    work = arguments.pool.parent
    out = work / "external_mem0.json"
    arms: list[dict[str, Any]] = []

    def save(**progress: Any) -> None:
        # Written after every phase, so a failure later keeps what was already measured.
        out.write_text(json.dumps({"vllm": URL, "limit": LIMIT, "arms": arms, **progress}, indent=2), encoding="utf-8")

    raw = mem0_memory(work / "mem0_raw", None)
    written = mem0_write(raw, items, infer=False)
    arms.append(arm("mem0 raw", written, mem0_rank(raw, probes, rerank=False), written["result"]))
    save()
    inferred = mem0_memory(work / "mem0", URL)
    written = mem0_write(inferred, items, infer=True)
    save(inferred_write={key: written[key] for key in ("seconds", "tokens", "failed")})
    arms.append(arm("mem0", written, mem0_rank(inferred, probes, rerank=False), written["result"]))
    save()
    arms.append(arm("mem0 + LLM rerank", written, mem0_rank(inferred, probes, rerank=True), written["result"]))
    save()
    print("mem0 done", flush=True)
    return 0


URL = ""

if __name__ == "__main__":
    sys.exit(main())
