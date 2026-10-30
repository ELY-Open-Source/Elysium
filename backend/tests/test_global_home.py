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
