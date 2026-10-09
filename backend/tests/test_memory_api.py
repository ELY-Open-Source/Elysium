"""The HTTP face stamps provenance itself: a client cannot say who owns a memory."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import ely_eye.api as api_module
from ely_eye.config import Settings

KEYS = "我们的钥匙放在玄关抽屉里"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_token: str) -> TestClient:
    settings = Settings(home=tmp_path, default_holder="wife", auth_token=write_token)
    monkeypatch.setattr(api_module, "get_settings", lambda: settings)
    return TestClient(api_module.create_app(), headers={"Authorization": f"Bearer {write_token}"})


def test_post_memory_stamps_the_holder_the_server_knows(client: TestClient) -> None:
    response = client.post("/api/memory", json={"text": KEYS, "scenario": "home"})
    assert response.status_code == 200
    atom = response.json()
    assert atom["holder_id"] == "wife"
    assert atom["origin"] == "self"
    assert atom["scenario"] == "home"
    assert atom["ingested_at"], "ingestion time is stamped, never supplied"


def test_a_client_cannot_claim_another_holder(client: TestClient) -> None:
    response = client.post(
        "/api/memory",
        json={"text": KEYS, "holder_id": "attacker", "origin": "third_party", "ingested_at": "2020-01-01T00:00:00+00:00"},
    )
    assert response.status_code == 200
    atom = response.json()
    assert atom["holder_id"] == "wife", "the request body has no holder field to forge"
    assert atom["origin"] == "self"


def test_an_empty_memory_is_rejected_with_its_reason(client: TestClient) -> None:
    response = client.post("/api/memory", json={"text": "   "})
    assert response.status_code == 422
    assert "needs text" in response.json()["detail"]


def test_supersede_then_forget_reports_what_it_removed(client: TestClient) -> None:
    old = client.post("/api/memory", json={"text": KEYS, "scenario": "home"}).json()
    new = client.post(
        "/api/memory/supersede",
        json={"atom_id": old["atom_id"], "text": "钥匙现在在书房第二个抽屉", "scenario": "home"},
    ).json()
    assert new["supersedes"] == [old["atom_id"]]

    forgotten = client.post("/api/memory/forget", json={"atom_id": old["atom_id"], "reason": "moved"})
    assert forgotten.status_code == 200
    report = forgotten.json()
    assert report["atoms_deleted"] == 1
    assert report["atom_ids"] == [old["atom_id"]]
    assert report["reason"] == "moved"


def test_a_forget_that_names_nothing_is_rejected(client: TestClient) -> None:
    response = client.post("/api/memory/forget", json={"reason": "vague"})
    assert response.status_code == 422
    assert "exactly one" in response.json()["detail"]
