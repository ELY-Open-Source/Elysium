"""The project was renamed from Ely-Eye to Elysium, then Elysian; every old name must stop the process.

A variable under the old prefix is otherwise ignored, so ELY_EYE_AUTH_TOKEN would start a server
with no token; an old home or database would be passed over and a fresh, empty store created
beside it, which is how the rename's own checkout first lost track of its data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from elysian.config import Settings, refuse_old_names


def test_an_old_variable_names_its_new_spelling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELY_EYE_AUTH_TOKEN", "secret")

    with pytest.raises(SystemExit, match="ELY_EYE_AUTH_TOKEN is set, but .* reads ELYSIAN_AUTH_TOKEN"):
        Settings(home=tmp_path)


def test_an_old_variable_in_the_dotenv_file_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ELY_EYE_HOME=/data\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="ELY_EYE_HOME is set"):
        Settings(home=tmp_path / "home")


def test_an_exported_old_variable_in_the_dotenv_file_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """dotenv reads `export NAME=value`; a guard that only matched the bare form let the old token slip past."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("export ELY_EYE_AUTH_TOKEN=x\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="ELY_EYE_AUTH_TOKEN is set"):
        Settings(home=tmp_path / "home")


def test_a_relative_home_beside_the_old_one_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A relative ELYSIAN_HOME must not slip past the absolute comparison."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ely_eye" / "data").mkdir(parents=True)

    with pytest.raises(SystemExit, match=r"\.ely_eye is the data home from before the rename"):
        Settings(home=Path(".elysian"))


def test_the_old_default_home_is_not_passed_over(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ely_eye" / "data").mkdir(parents=True)

    with pytest.raises(SystemExit, match=r"\.ely_eye is the data home from before the rename"):
        Settings()


def test_an_old_database_is_not_replaced_by_an_empty_one(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "ely_eye.sqlite").write_bytes(b"store")

    with pytest.raises(SystemExit, match=r"ely_eye\.sqlite is a store from before the rename; move it to"):
        Settings(home=tmp_path)


@pytest.mark.parametrize("old", ["ELY_EYE_AUTH_TOKEN", "ELYSIUM_AUTH_TOKEN"])
def test_each_old_prefix_names_its_new_spelling(tmp_path: Path, old: str) -> None:
    with pytest.raises(SystemExit, match=f"{old} is set, but .* reads ELYSIAN_AUTH_TOKEN"):
        refuse_old_names(Settings(home=tmp_path / "fresh"), {old: "secret"}, tmp_path)


def test_the_elysium_home_is_not_passed_over(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".elysium" / "data").mkdir(parents=True)

    with pytest.raises(SystemExit, match=r"\.elysium is the data home from before the rename"):
        Settings()


def test_a_new_home_without_a_store_does_not_hide_the_old_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An installer makes .elysian/bin first; the old store must still stop the process."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".elysian" / "bin").mkdir(parents=True)
    (tmp_path / ".elysium" / "data").mkdir(parents=True)
    (tmp_path / ".elysium" / "data" / "elysium.sqlite").write_bytes(b"store")

    with pytest.raises(SystemExit, match=r"\.elysium is the data home from before the rename"):
        Settings(home=Path(".elysian"))


def test_an_elysium_database_is_not_replaced_by_an_empty_one(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "elysium.sqlite").write_bytes(b"store")

    with pytest.raises(SystemExit, match=r"elysium\.sqlite is a store from before the rename; move it to"):
        Settings(home=tmp_path)


def test_a_moved_store_opens_and_a_new_home_is_untouched(tmp_path: Path) -> None:
    moved = tmp_path / "moved"
    (moved / "data").mkdir(parents=True)
    (moved / "data" / "elysian.sqlite").write_bytes(b"store")

    refuse_old_names(Settings(home=moved), {}, tmp_path)
    refuse_old_names(Settings(home=tmp_path / "fresh"), {"ELYSIAN_HOME": "x"}, tmp_path)
