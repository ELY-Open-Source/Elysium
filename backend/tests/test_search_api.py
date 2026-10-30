"""Search over HTTP: the answers a caller can act on, and the reasons it gets none."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import elysian.api as api_module
from elysian.config import Settings
from elysian.db import Database
from elysian.memory import MemoryService
from elysian.schemas import MemoryOrigin

KEYS = "我们的钥匙放在玄关抽屉里"
PASSPORT = "护照在书房第二个抽屉里"
WALLET = "钱包在玄关的挂钩上"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_token: str) -> TestClient:
    settings = Settings(home=tmp_path, default_holder="wife", auth_token=write_token)
    monkeypatch.setattr(api_module, "get_settings", lambda: settings)
    return TestClient(api_module.create_app(), headers={"Authorization": f"Bearer {write_token}"})


def search(client: TestClient, payload: dict) -> dict:
    response = client.post("/api/search", json=payload)
    assert response.status_code in (200, 422), response.text
    return response.json()


def test_a_chinese_question_finds_the_memory_it_was_written_in(client: TestClient) -> None:
    client.post("/api/memory", json={"text": KEYS, "scenario": "home"})
    answer = search(client, {"query": "钥匙"})
    assert answer["status"] == "hits"
    assert [hit["atom"]["text"] for hit in answer["hits"]] == [KEYS]


def test_an_empty_corpus_answers_no_match_rather_than_an_empty_array(client: TestClient) -> None:
    answer = search(client, {"query": "钥匙"})
    assert answer["hits"] == []
    assert answer["status"] == "no_match", "an empty answer must say the corpus has nothing"


def test_a_query_with_nothing_searchable_is_refused_with_the_reason(client: TestClient) -> None:
    response = client.post("/api/search", json={"query": "???"})
    assert response.status_code == 422
    assert "needs at least one searchable word" in response.json()["detail"]


def test_the_scenario_filter_hides_memories_from_other_scenarios(client: TestClient) -> None:
    client.post("/api/memory", json={"text": KEYS, "scenario": "home"})
    assert search(client, {"query": "钥匙", "filters": {"scenario": "home"}})["status"] == "hits"
    assert search(client, {"query": "钥匙", "filters": {"scenario": "travel"}})["status"] == "no_match"


def test_a_superseded_memory_stops_answering(client: TestClient) -> None:
    old = client.post("/api/memory", json={"text": KEYS}).json()
    client.post("/api/memory/supersede", json={"atom_id": old["atom_id"], "text": PASSPORT})
    answer = search(client, {"query": "抽屉"})
    assert [hit["atom"]["text"] for hit in answer["hits"]] == [PASSPORT]


def test_paging_walks_every_hit_without_skipping_one(client: TestClient) -> None:
    for text in (KEYS, PASSPORT, WALLET, "备用钥匙在车里", "工具箱在阳台的抽屉里"):
        client.post("/api/memory", json={"text": text})
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        payload: dict = {"query": "钥匙", "top_k": 2}
        if cursor:
            payload["cursor"] = cursor
        answer = search(client, payload)
        seen.extend(hit["atom"]["atom_id"] for hit in answer["hits"])
        cursor = answer["next_cursor"]
        if not cursor:
            break
    assert cursor is None, "the page loop never reached the end"
    assert len(seen) == len(set(seen)), "a page repeated a memory"
    assert len(seen) == 2, "only two memories mention 钥匙"


def test_the_holder_filter_answers_only_that_holders_memory(
    client: TestClient, tmp_path: Path
) -> None:
    client.post("/api/memory", json={"text": KEYS})
    husband = MemoryService(Settings(home=tmp_path, default_holder="husband"), Database(Settings(home=tmp_path)))
    husband.remember("我的钥匙在办公室", holder_id="husband", origin=MemoryOrigin.self_)
    answer = search(client, {"query": "钥匙", "filters": {"holder": "husband"}})
    assert [hit["atom"]["text"] for hit in answer["hits"]] == ["我的钥匙在办公室"]


def test_the_cli_answers_in_json_a_machine_can_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The three faces rank alike: the CLI reports the same hit the HTTP face returns."""
    import json

    from typer.testing import CliRunner

    import elysian.cli as cli_module
    from elysian.cli import app

    settings = Settings(home=tmp_path, default_holder="wife")
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    runner = CliRunner()
    MemoryService(settings, Database(settings)).remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_, scenario="home")

    answer = json.loads(runner.invoke(app, ["search", "钥匙", "--scenario", "home"]).stdout)
    assert answer["status"] == "hits"
    assert [hit["atom"]["text"] for hit in answer["hits"]] == [KEYS]

    empty = json.loads(runner.invoke(app, ["search", "钥匙", "--scenario", "travel"]).stdout)
    assert empty["status"] == "no_match"

    stranger = json.loads(runner.invoke(app, ["search", "钥匙", "--as-holder", "stranger"]).stdout)
    assert stranger["status"] == "no_match", "--as-holder must show what a stranger would see"
    owner = json.loads(runner.invoke(app, ["search", "钥匙", "--as-holder", "wife"]).stdout)
    assert [hit["atom"]["text"] for hit in owner["hits"]] == [KEYS]
