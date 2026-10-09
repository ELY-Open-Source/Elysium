"""As-of search: what was true then, not what is true now.

The store keeps two clocks — when a memory was true and when the store learned it — so a
question about last week has to be answerable after the fact. These tests pin that the words
leg and the dense leg read the same window, and that `as_of` moves only the moment being asked
about, never who is allowed to see the answer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import ely_eye.api as api_module
from ely_eye import lifecycle_store
from ely_eye.config import Settings
from ely_eye.db import Database
from ely_eye.memory import MemoryService
from ely_eye.schemas import MemoryOrigin, SearchFilters, TimePrecision

DRAWER = "钥匙放在玄关抽屉里"
CAR = "钥匙现在在车里"
WEEK = timedelta(days=9)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(home=tmp_path, default_holder="wife", auth_token="test-token")


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(api_module, "get_settings", lambda: settings)
    return TestClient(api_module.create_app(), headers={"Authorization": "Bearer test-token"})


def hits(client: TestClient, payload: dict) -> list[str]:
    response = client.post("/api/search", json=payload)
    assert response.status_code == 200, response.text
    return [hit["atom"]["text"] for hit in response.json()["hits"]]


def store_the_pair(client: TestClient) -> tuple[str, datetime]:
    """The drawer memory is nine days old; the car replaces it now."""
    week_ago = datetime.now(UTC) - WEEK
    response = client.post(
        "/api/memory",
        json={"text": DRAWER, "event_time": week_ago.isoformat(), "event_time_precision": "day"},
    )
    assert response.status_code == 200, response.text
    return response.json()["atom_id"], week_ago


def test_a_retired_memory_answers_for_the_time_it_was_true(client: TestClient) -> None:
    atom_id, week_ago = store_the_pair(client)
    superseded = client.post("/api/memory/supersede", json={"atom_id": atom_id, "text": CAR})
    assert superseded.status_code == 200, superseded.text
    assert hits(client, {"query": "钥匙"}) == [CAR], "asked now, the current memory answers"
    asked_then = hits(client, {"query": "钥匙", "filters": {"as_of": (week_ago + timedelta(days=1)).isoformat()}})
    assert asked_then == [DRAWER], "asked about last week, the retired memory answers"


def test_a_memory_that_had_not_happened_yet_does_not_answer(client: TestClient) -> None:
    next_week = datetime.now(UTC) + timedelta(days=7)
    response = client.post(
        "/api/memory",
        json={"text": CAR, "event_time": next_week.isoformat(), "event_time_precision": "day"},
    )
    assert response.status_code == 200, response.text
    assert hits(client, {"query": "钥匙"}) == [CAR]
    assert hits(client, {"query": "钥匙", "filters": {"as_of": datetime.now(UTC).isoformat()}}) == []


def test_an_archived_memory_still_answers_for_the_time_before_it_was_archived(
    client: TestClient, settings: Settings
) -> None:
    recorded = datetime.now(UTC) - timedelta(days=30)
    response = client.post(
        "/api/memory",
        json={"text": DRAWER, "event_time": recorded.isoformat(), "event_time_precision": "day"},
    )
    assert response.status_code == 200, response.text
    archived_at = datetime.now(UTC)
    moved = lifecycle_store.archive_atoms(Database(settings), [response.json()["atom_id"]], archived_at)
    assert moved == 1, "the archive moved nothing, so the test proves nothing"
    assert hits(client, {"query": "钥匙"}) == [], "an archived memory is out of the working set"
    asked_then = hits(client, {"query": "钥匙", "filters": {"as_of": (archived_at - timedelta(hours=1)).isoformat()}})
    assert asked_then == [DRAWER], "archival moves a memory between tiers, it does not make it untrue"


def test_asking_as_of_another_moment_does_not_borrow_another_holders_memory(
    client: TestClient, settings: Settings
) -> None:
    atom_id, week_ago = store_the_pair(client)
    client.post("/api/memory/supersede", json={"atom_id": atom_id, "text": CAR})
    stranger = hits(client, {"query": "钥匙", "filters": {"as_holder": "stranger", "as_of": week_ago.isoformat()}})
    assert stranger == [], "a moment in time does not grant access to somebody else's memory"
    as_wife = hits(client, {"query": "钥匙", "filters": {"as_holder": "wife", "as_of": week_ago.isoformat()}})
    assert as_wife == [DRAWER]


def test_the_dense_leg_reads_the_same_window_as_the_words_leg(settings: Settings) -> None:
    """Both legs answer an as-of question from one rule, or the fusion would mix two moments."""
    service = MemoryService(settings, Database(settings))
    week_ago = datetime.now(UTC) - WEEK
    drawer = service.remember(
        DRAWER, holder_id="wife", origin=MemoryOrigin.self_, event_time=week_ago, event_time_precision=TimePrecision.day
    )
    service.supersede(drawer.atom_id, text=CAR, holder_id="wife")
    from ely_eye.retrieval import RetrievalService

    retrieval = RetrievalService(settings=settings, database=Database(settings))
    now_page = retrieval.search("钥匙", filters=SearchFilters(as_holder="wife"))
    assert [hit.atom.text for hit in now_page.hits] == [CAR]
    then_page = retrieval.search(
        "钥匙", filters=SearchFilters(as_holder="wife", as_of=week_ago + timedelta(days=1))
    )
    assert [hit.atom.text for hit in then_page.hits] == [DRAWER]
