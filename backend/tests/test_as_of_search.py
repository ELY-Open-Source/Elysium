"""As-of search: what was true then, not what is true now.

The store keeps two clocks — when a memory was true and when the store learned it — so a
question about last week has to be answerable after the fact. These tests pin that the words
leg and the dense leg read the same window, and that `as_of` moves only the moment being asked
about, never who is allowed to see the answer.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import elysium.api as api_module
from elysium import lifecycle_store
from elysium.config import Settings
from elysium.db import Database
from elysium.memory import MemoryService
from elysium.schemas import MemoryOrigin, SearchFilters, TimePrecision

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
    asked_then = hits(
        client, {"query": "钥匙", "filters": {"as_of": (week_ago + timedelta(days=1)).isoformat()}}
    )
    assert asked_then == [DRAWER], "asked about last week, the retired memory answers"


def test_a_memory_that_had_not_happened_yet_does_not_answer(client: TestClient) -> None:
    next_week = datetime.now(UTC) + timedelta(days=7)
    response = client.post(
        "/api/memory",
        json={"text": CAR, "event_time": next_week.isoformat(), "event_time_precision": "day"},
    )
    assert response.status_code == 200, response.text
    assert hits(client, {"query": "钥匙"}) == [CAR]
    assert (
        hits(client, {"query": "钥匙", "filters": {"as_of": datetime.now(UTC).isoformat()}}) == []
    )


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
    moved = lifecycle_store.archive_atoms(
        Database(settings), [response.json()["atom_id"]], archived_at
    )
    assert moved == 1, "the archive moved nothing, so the test proves nothing"
    assert hits(client, {"query": "钥匙"}) == [], "an archived memory is out of the working set"
    asked_then = hits(
        client,
        {"query": "钥匙", "filters": {"as_of": (archived_at - timedelta(hours=1)).isoformat()}},
    )
    assert asked_then == [DRAWER], (
        "archival moves a memory between tiers, it does not make it untrue"
    )


def test_asking_as_of_another_moment_does_not_borrow_another_holders_memory(
    client: TestClient, settings: Settings
) -> None:
    atom_id, week_ago = store_the_pair(client)
    client.post("/api/memory/supersede", json={"atom_id": atom_id, "text": CAR})
    stranger = hits(
        client,
        {"query": "钥匙", "filters": {"as_holder": "stranger", "as_of": week_ago.isoformat()}},
    )
    assert stranger == [], "a moment in time does not grant access to somebody else's memory"
    as_wife = hits(
        client, {"query": "钥匙", "filters": {"as_holder": "wife", "as_of": week_ago.isoformat()}}
    )
    assert as_wife == [DRAWER]


def test_the_dense_leg_reads_the_same_window_as_the_words_leg(
    tmp_path: Path, fake_embeddings: Any
) -> None:
    """Both legs answer an as-of question from one rule, or the fusion would mix two moments.

    The dense leg is enabled here with a stand-in model: with the default off, this test would
    pass while the vector side of `as_of` had no coverage at all.
    """
    from elysium.retrieval import RetrievalService
    from elysium.vector_index import VectorIndex, expected_vectors

    settings = Settings(home=tmp_path, default_holder="wife", dense_embeddings_enabled=True)
    database = Database(settings)
    index = VectorIndex(settings, database, fake_embeddings())
    service = MemoryService(settings, database, vectors=index)
    week_ago = datetime.now(UTC) - WEEK
    drawer = service.remember(
        DRAWER,
        holder_id="wife",
        origin=MemoryOrigin.self_,
        event_time=week_ago,
        event_time_precision=TimePrecision.day,
    )
    service.supersede(drawer.atom_id, text=CAR, holder_id="wife")
    assert expected_vectors(database) == 2, (
        "a retired memory keeps its vector, or no question can reach it"
    )

    query = index.embeddings.embed_query("钥匙")
    now = index.search(query, 10, as_holder="wife")
    assert list(now) == [f"mem-{_sha(CAR, 'wife')}:text"], (
        "asked now, the vector side offers the current memory"
    )
    then = index.search(
        query, 10, as_holder="wife", as_of=(week_ago + timedelta(days=1)).isoformat()
    )
    assert f"mem-{_sha(DRAWER, 'wife')}:text" in then, (
        "the retired memory is still reachable through the vectors"
    )

    # Asked through the retrieval service, so the plumbing that hands `as_of` to the engine is pinned too.
    criteria = SearchFilters(as_holder="wife", as_of=week_ago + timedelta(days=1)).model_dump(
        exclude_none=True
    )
    criteria["cartridge_ids"] = None
    open_now = SearchFilters(as_holder="wife").model_dump(exclude_none=True)
    open_now["cartridge_ids"] = None

    retrieval = RetrievalService(settings, database)
    retrieval.embeddings = fake_embeddings()  # type: ignore[assignment]
    retrieval.vectors = index  # type: ignore[assignment]
    assert f"mem-{_sha(DRAWER, 'wife')}:text" in retrieval._dense_search("钥匙", 10, criteria)
    assert f"mem-{_sha(DRAWER, 'wife')}:text" not in retrieval._dense_search("钥匙", 10, open_now)
    now_page = retrieval.search("钥匙", filters=SearchFilters(as_holder="wife"))
    assert [hit.atom.text for hit in now_page.hits] == [CAR]
    then_page = retrieval.search(
        "钥匙", filters=SearchFilters(as_holder="wife", as_of=week_ago + timedelta(days=1))
    )
    assert [hit.atom.text for hit in then_page.hits] == [DRAWER]


def test_a_memory_retired_at_a_future_date_still_answers_now(
    client: TestClient, settings: Settings
) -> None:
    """A change booked for next year has not happened, so the old fact is still the current one."""
    recorded = datetime.now(UTC) - timedelta(days=3)
    stored = client.post(
        "/api/memory",
        json={"text": DRAWER, "event_time": recorded.isoformat(), "event_time_precision": "day"},
    )
    assert stored.status_code == 200, stored.text
    atom_id = stored.json()["atom_id"]
    future = datetime.now(UTC) + timedelta(days=365)
    booked = client.post(
        "/api/memory/supersede",
        json={
            "atom_id": atom_id,
            "text": CAR,
            "event_time": future.isoformat(),
            "event_time_precision": "day",
        },
    )
    assert booked.status_code == 200, booked.text
    assert hits(client, {"query": "钥匙"}) == [DRAWER], (
        "a retirement dated next year has not taken effect"
    )
    listed = client.get("/api/atoms", params={"source_id": f"mem-{_sha(DRAWER, 'wife')}"})
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1, "the listing and the search read the same moment"
    later = hits(
        client, {"query": "钥匙", "filters": {"as_of": (future + timedelta(days=1)).isoformat()}}
    )
    assert later == [CAR], "asked about the future, the booked change has taken effect"


def _sha(statement: str, holder: str) -> str:
    return hashlib.sha256(f"{holder}\n{statement}".encode()).hexdigest()[:16]
