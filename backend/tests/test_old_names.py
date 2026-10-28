"""The project was renamed from Ely-Eye to Elysium; every old name must stop the process.

A variable under the old prefix is otherwise ignored, so ELY_EYE_AUTH_TOKEN would start a server
with no token; an old home or database would be passed over and a fresh, empty store created
beside it, which is how the rename's own checkout first lost track of its data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from elysium.config import Settings, refuse_old_names


def test_an_old_variable_names_its_new_spelling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELY_EYE_AUTH_TOKEN", "secret")

    with pytest.raises(SystemExit, match="ELY_EYE_AUTH_TOKEN is set, but .* reads ELYSIUM_AUTH_TOKEN"):
        Settings(home=tmp_path)


def test_an_old_variable_in_the_dotenv_file_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ELY_EYE_HOME=/data\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="ELY_EYE_HOME is set"):
        Settings(home=tmp_path / "home")


def test_the_old_default_home_is_not_passed_over(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ely_eye" / "data").mkdir(parents=True)

    with pytest.raises(SystemExit, match=r"\.ely_eye is the data home from before the rename"):
        Settings()


def test_an_old_database_is_not_replaced_by_an_empty_one(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "ely_eye.sqlite").write_bytes(b"store")

    with pytest.raises(SystemExit, match=r"ely_eye\.sqlite is a store from before the rename; move it to"):
        Settings(home=tmp_path)


def test_a_moved_store_opens_and_a_new_home_is_untouched(tmp_path: Path) -> None:
    moved = tmp_path / "moved"
    (moved / "data").mkdir(parents=True)
    (moved / "data" / "elysium.sqlite").write_bytes(b"store")

    refuse_old_names(Settings(home=moved), {}, tmp_path)
    refuse_old_names(Settings(home=tmp_path / "fresh"), {"ELYSIUM_HOME": "x"}, tmp_path)
