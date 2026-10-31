"""One person, one store: memory lives in ~/.elysian unless ELYSIAN_HOME names another home.

A store left in a project directory from the per-project layout must stop the process, or the
first run there would open an empty global store and the project's memories would look lost.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from elysian.config import Settings


@pytest.fixture()
def user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    monkeypatch.delenv("ELYSIAN_HOME", raising=False)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    return tmp_path


def test_the_default_home_is_in_the_users_home_whatever_the_directory(user: Path) -> None:
    assert Settings().home == user / "user" / ".elysian"


def test_a_project_store_is_not_passed_over_for_the_global_one(user: Path) -> None:
    (user / "project" / ".elysian" / "data").mkdir(parents=True)

    with pytest.raises(SystemExit, match=r"project/\.elysian holds a project store, .* set ELYSIAN_HOME="):
        Settings()


def test_naming_the_project_store_opens_it(user: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = user / "project" / ".elysian"
    (store / "data").mkdir(parents=True)
    monkeypatch.setenv("ELYSIAN_HOME", str(store))

    assert Settings().home == store
    assert Settings(home=user / "elsewhere").home == user / "elsewhere"


def test_an_empty_elysian_home_means_unset_as_in_the_mcp_server(user: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELYSIAN_HOME", "")

    assert Settings().home == user / "user" / ".elysian"


def test_a_home_in_the_dotenv_file_is_refused(user: Path) -> None:
    (user / "project" / ".env").write_text("ELYSIAN_HOME=relative\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="sets ELYSIAN_HOME, which the MCP server does not read"):
        Settings()


def test_a_lower_case_home_in_the_dotenv_file_is_refused(user: Path) -> None:
    (user / "project" / ".env").write_text("elysian_home=relative\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="sets ELYSIAN_HOME, which the MCP server does not read"):
        Settings()


@pytest.mark.parametrize("name", ["elysian_home", "Elysian_Auth_Token"])
def test_a_variable_the_mcp_server_would_not_read_is_refused(user: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, str(user / "elsewhere"))

    with pytest.raises(SystemExit, match=f"{name} is read here but the MCP server reads only {name.upper()}"):
        Settings()


def test_a_relative_home_is_held_absolute_so_every_face_reports_one_path(user: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELYSIAN_HOME", "relative")

    assert Settings().home == user / "project" / "relative"
    assert Settings(home=Path("other")).home == user / "project" / "other"
