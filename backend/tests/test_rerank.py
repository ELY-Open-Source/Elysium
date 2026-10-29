"""The served judge reorders the page it is handed; its score is P(yes) against P(no), never a guess."""

from __future__ import annotations

import json
import math
from pathlib import Path

import httpx
import pytest

from elysium import rerank
from elysium.config import Settings
from elysium.db import Database
from elysium.memory import MemoryService
from elysium.retrieval import RetrievalService
from elysium.schemas import MemoryOrigin, SearchFilters

URL = "http://judge/v1"


def _reply(tokens: dict[str, float]) -> dict[str, object]:
    top = [{"token": token, "logprob": math.log(chance)} for token, chance in tokens.items()]
    return {"choices": [{"logprobs": {"content": [{"top_logprobs": top}]}}]}


def _client(tokens: dict[str, float]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=_reply(tokens))))


def test_the_score_is_yes_against_no() -> None:
    assert rerank.judge(_client({"no": 0.6, "yes": 0.2, "The": 0.1}), URL, "m", "q", "doc") == pytest.approx(0.25)


def test_a_reply_with_neither_answer_is_an_error() -> None:
    with pytest.raises(RuntimeError, match="neither yes nor no"):
        rerank.judge(_client({"The": 0.9}), URL, "m", "q", "doc")


def test_every_spelling_of_an_answer_adds_to_it() -> None:
    """A later, rarer spelling once overwrote the common one and sent a gold atom from rank 1 to 33."""
    score = rerank.judge(_client({"yes": 0.5, "no": 0.3, "Yes": 0.1, " yes": 0.05, "No": 0.05}), URL, "m", "q", "doc")

    assert score == pytest.approx(0.65)


def _served(monkeypatch: pytest.MonkeyPatch, handler: httpx.MockTransport) -> None:
    real = httpx.Client
    monkeypatch.setattr(rerank.httpx, "Client", lambda **options: real(transport=handler, **options))


def _likes(word: str) -> httpx.MockTransport:
    """A judge that says yes to any memory holding `word`."""

    def answer(request: httpx.Request) -> httpx.Response:
        document = json.loads(request.content)["messages"][1]["content"].split("<Document>: ", 1)[1]
        yes = 0.9 if word in document else 0.1
        return httpx.Response(200, json=_reply({"yes": yes, "no": 1.0 - yes}))

    return httpx.MockTransport(answer)


def _service(tmp_path: Path) -> RetrievalService:
    settings = Settings(home=tmp_path, rerank_base_url=URL)
    database = Database(settings)
    memory = MemoryService(settings, database)
    for name in ("north", "south", "east", "west", "centre"):
        memory.remember(f"the lighthouse keeper logs the {name} lamp", holder_id="keeper", origin=MemoryOrigin.self_)
    return RetrievalService(settings=settings, database=database)


def test_the_judged_memory_leads_the_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path)
    _served(monkeypatch, _likes("west"))

    hits = service.search("lighthouse lamp", top_k=5, filters=SearchFilters(as_holder="keeper")).hits

    assert "west" in (hits[0].atom.text or ""), "the memory the judge said yes to must come first"


def test_pages_still_hold_every_memory_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path)
    _served(monkeypatch, _likes("centre"))
    seen: list[str] = []
    cursor = None
    for _ in range(3):
        page = service.search("lighthouse lamp", top_k=2, filters=SearchFilters(as_holder="keeper"), cursor=cursor)
        seen += [hit.atom.atom_id for hit in page.hits]
        cursor = page.next_cursor

    assert len(seen) == len(set(seen)) == 5, "reordering a page must not move a memory onto another page"


def test_a_failed_judge_fails_the_search(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path)
    _served(monkeypatch, httpx.MockTransport(lambda request: httpx.Response(503)))

    with pytest.raises(RuntimeError, match="rerank model at http://judge/v1 failed"):
        service.search("lighthouse lamp", top_k=5, filters=SearchFilters(as_holder="keeper"))
