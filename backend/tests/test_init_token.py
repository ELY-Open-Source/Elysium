"""`elysian init` makes the store and an operator token the API and the MCP server both read.

A one-command install cannot ask anyone to export ELYSIAN_AUTH_TOKEN, and a server with no
token refuses every write; the token lives in the home, readable by its owner only.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from elysian import cli as cli_module
from elysian.cli import app
from elysian.config import Settings

runner = CliRunner()


def test_init_writes_one_private_token_and_never_prints_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELYSIAN_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(cli_module, "get_settings", lambda: Settings(home=tmp_path))

    first = runner.invoke(app, ["init"])
    token = (tmp_path / "auth_token").read_text(encoding="utf-8").strip()
    second = runner.invoke(app, ["init"])

    assert first.exit_code == 0, first.output
    assert json.loads(first.output)["token_created"] is True
    assert json.loads(second.output)["token_created"] is False
    assert (tmp_path / "data" / "elysian.sqlite").is_file()
    assert stat.S_IMODE((tmp_path / "auth_token").stat().st_mode) == 0o600
    assert len(token) >= 40
    assert token not in first.output + second.output
    assert (tmp_path / "auth_token").read_text(encoding="utf-8").strip() == token


def test_the_token_file_is_the_operator_token_unless_the_environment_names_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ELYSIAN_AUTH_TOKEN", raising=False)
    (tmp_path / "auth_token").write_text("from-file\n", encoding="utf-8")
    assert Settings(home=tmp_path).auth_token == "from-file"

    monkeypatch.setenv("ELYSIAN_AUTH_TOKEN", "from-env")
    assert Settings(home=tmp_path).auth_token == "from-env"


def test_an_empty_token_file_stops_the_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELYSIAN_AUTH_TOKEN", raising=False)
    (tmp_path / "auth_token").write_text("\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="auth_token is empty; delete it and run `elysian init`"):
        Settings(home=tmp_path)
