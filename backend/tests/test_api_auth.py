"""The write gate: a query is free, a change needs the token the server was started with."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import elysium.api as api_module
from elysium.config import Settings

KEYS = "我们的钥匙放在玄关抽屉里"
TOKEN = "a-token-worth-having"
BROWSER = "http://localhost:5173"


def _client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    **overrides: Any,
) -> TestClient:
    settings = Settings(home=tmp_path, default_holder="wife", **overrides)
    monkeypatch.setattr(api_module, "get_settings", lambda: settings)
    return TestClient(api_module.create_app())


def test_a_write_against_a_server_with_no_token_is_refused_and_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = _client(tmp_path, monkeypatch).post("/api/memory", json={"text": KEYS})
    assert response.status_code == 403
    assert "ELYSIUM_AUTH_TOKEN" in response.json()["detail"], "the refusal must name the fix"


def test_a_write_with_the_wrong_token_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch, auth_token=TOKEN)
    refused = client.post("/api/memory", json={"text": KEYS}, headers={"Authorization": "Bearer nope"})
    assert refused.status_code == 401
    assert "Bearer" in refused.json()["detail"]
    assert client.post("/api/memory", json={"text": KEYS}).status_code == 401, "a missing header is refused too"


def test_the_right_token_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch, auth_token=TOKEN)
    answer = client.post(
        "/api/memory", json={"text": KEYS, "scenario": "home"}, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert answer.status_code == 200
    assert answer.json()["holder_id"] == "wife", "the token authenticates; the server still picks the holder"


def test_a_query_needs_no_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch, auth_token=TOKEN)
    assert client.get("/api/status").status_code == 200
    assert client.post("/api/search", json={"query": "钥匙"}).status_code == 200


def test_a_browser_from_an_unlisted_origin_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch, auth_token=TOKEN)
    forged = client.post(
        "/api/memory",
        json={"text": KEYS},
        headers={"Authorization": f"Bearer {TOKEN}", "Origin": "http://evil.example"},
    )
    assert forged.status_code == 403
    assert "may not write" in forged.json()["detail"]


def test_an_allowed_origin_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch, auth_token=TOKEN)
    answer = client.post(
        "/api/memory", json={"text": KEYS}, headers={"Authorization": f"Bearer {TOKEN}", "Origin": BROWSER}
    )
    assert answer.status_code == 200


def test_the_cartridge_routes_need_the_token_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch, auth_token=TOKEN)
    assert client.post("/api/cartridges/anything/mount").status_code == 401
    assert client.get("/api/mounts").status_code == 200


def test_the_holder_registry_needs_the_token_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch, auth_token=TOKEN)
    body = {"name": "小美", "knows_about": ["家里的钥匙"]}
    assert client.post("/api/holders/wife", json=body).status_code == 401
    assert client.delete("/api/holders/wife").status_code == 401
    assert client.get("/api/holders").status_code == 200
    written = client.post("/api/holders/wife", json=body, headers={"Authorization": f"Bearer {TOKEN}"})
    assert written.status_code == 200 and written.json()["name"] == "小美"
