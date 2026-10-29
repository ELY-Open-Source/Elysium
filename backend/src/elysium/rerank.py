"""A served model reads each hit on the page and says whether it is the memory the query asks for.

Word search puts the right memory on the page but not always first. On the frozen dev split the
served 9B, asked yes or no per atom, lifted recall@10 from 0.901 to 0.916 over a 40-atom window
(`bench/reports/RANK.md`) and to 0.913 over the 24-atom page alone. It reorders only the page it is
handed, so a cursor still walks every memory exactly once. The model is served, not loaded here.
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor

import httpx

from .config import Settings
from .schemas import RetrievalHit

SYSTEM = (
    'Judge whether the Document meets the requirements based on the Query and the Instruct provided. '
    'Note that the answer can only be "yes" or "no".'
)
INSTRUCT = "Given a search query, judge whether this stored memory is the one the query is looking for"
# The measured runs read this much of each memory.
DOCUMENT_CHARS = 2000
WORKERS = 64
STALL_SECONDS = 300.0


def reorder(settings: Settings, query: str, hits: list[RetrievalHit]) -> list[RetrievalHit]:
    """The page sorted by the model's P(yes); ties keep the word ranking's order."""
    if settings.rerank_base_url is None or not hits:
        return hits
    url = settings.rerank_base_url
    with httpx.Client(timeout=STALL_SECONDS) as client, ThreadPoolExecutor(WORKERS) as pool:
        verdicts = list(pool.map(lambda hit: judge(client, url, settings.model_id, query, hit.atom.text or ""), hits))
    order = sorted(range(len(hits)), key=lambda position: (-verdicts[position], position))
    return [hits[position] for position in order]


def judge(client: httpx.Client, url: str, model: str, query: str, text: str) -> float:
    """P(yes) over yes+no for one memory, every spelling of each summed; a reply with neither is an error."""
    body = {
        "model": model,
        "max_tokens": 1,
        "temperature": 0,
        "logprobs": True,
        "top_logprobs": 10,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"<Instruct>: {INSTRUCT}\n<Query>: {query}\n<Document>: {text[:DOCUMENT_CHARS]}"},
        ],
    }
    try:
        response = client.post(f"{url}/chat/completions", json=body)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise RuntimeError(f"the rerank model at {url} failed: {error}") from error
    top = response.json()["choices"][0]["logprobs"]["content"][0]["top_logprobs"]
    # "yes", " yes" and "Yes" are separate tokens for one answer; their chances add, none overwrites another.
    odds: dict[str, float] = {}
    for entry in top:
        word = entry["token"].strip().lower()
        odds[word] = odds.get(word, 0.0) + math.exp(entry["logprob"])
    yes, no = odds.get("yes", 0.0), odds.get("no", 0.0)
    if yes + no == 0.0:
        raise RuntimeError(f"the rerank model answered neither yes nor no for {query!r}: {[entry['token'] for entry in top]}")
    return yes / (yes + no)
