"""The container story only holds if a built interface is actually served."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from elysium import api as api_module
from elysium.config import Settings


def _client(settings: Settings, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_module, "get_settings", lambda: settings)
    return TestClient(api_module.create_app())


def test_a_built_interface_is_served_from_the_api_origin(tmp_path: Path, monkeypatch) -> None:
    ui = tmp_path / "dist"
    ui.mkdir()
    (ui / "index.html").write_text("<html><body>elysium</body></html>", encoding="utf-8")
    settings = Settings(home=tmp_path / "home", ui_dir=ui)
    client = _client(settings, monkeypatch)
    answer = client.get("/")
    assert answer.status_code == 200 and "elysium" in answer.text
    assert client.get("/api/status").status_code == 200


def test_a_ui_directory_that_was_never_built_names_the_fix(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(home=tmp_path / "home", ui_dir=tmp_path / "dist")
    monkeypatch.setattr(api_module, "get_settings", lambda: settings)
    with pytest.raises(SystemExit, match="npm run build"):
        api_module.create_app()


def test_no_ui_directory_means_the_api_alone_answers(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(home=tmp_path / "home")
    client = _client(settings, monkeypatch)
    assert client.get("/").status_code == 404
    assert client.get("/api/status").status_code == 200
