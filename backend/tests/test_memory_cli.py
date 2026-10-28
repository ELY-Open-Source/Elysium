"""The CLI face of the write path: a person at a terminal can hand a memory to
a named holder, replace it, and take it back, and every answer is JSON."""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from elysium import cli as cli_module
from elysium.cli import app
from elysium.config import Settings
from elysium.db import Database

runner = CliRunner()


@pytest.fixture()
def db(tmp_path, monkeypatch) -> Database:
    settings = Settings(home=tmp_path, default_holder="husband")
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    return Database(settings)


def run(*args: str) -> Any:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_remember_stamps_the_default_holder_when_none_is_given(db: Database) -> None:
    atom = run("remember", "钥匙在玄关抽屉")
    assert atom["holder_id"] == "husband"
    assert atom["origin"] == "self"
    assert atom["source"] == "memory://husband/general"
    assert db.atom_count() == 1


def test_remember_carries_the_holder_scenario_and_event_time(db: Database) -> None:
    atom = run(
        "remember",
        "结婚纪念日是五月一日",
        "--holder",
        "wife",
        "--scenario",
        "home",
        "--event-time",
        "2026-05-01T00:00:00+08:00",
        "--precision",
        "day",
    )
    assert atom["holder_id"] == "wife"
    assert atom["scenario"] == "home"
    assert atom["event_time"].startswith("2026-05-01T00:00:00+08:00")
    assert atom["event_time_precision"] == "day"


def test_remember_refuses_an_event_time_without_an_offset(db: Database) -> None:
    result = runner.invoke(
        app,
        ["remember", "昨天下的雨", "--event-time", "2026-05-01T12:00:00", "--precision", "day"],
    )
    assert result.exit_code != 0
    assert "memory timestamps need an explicit offset" in str(result.exception)


def test_remember_refuses_a_malformed_timestamp(db: Database) -> None:
    result = runner.invoke(app, ["remember", "昨天下的雨", "--event-time", "yesterday"])
    assert result.exit_code != 0
    assert "--event-time 'yesterday' is not an ISO timestamp" in str(result.exception)


def test_supersede_links_the_replacement_and_closes_the_original(db: Database) -> None:
    old = run("remember", "钥匙在玄关抽屉", "--holder", "wife")
    new = run("supersede", old["atom_id"], "钥匙在客厅茶几", "--holder", "wife")
    assert new["supersedes"] == [old["atom_id"]]
    assert new["valid_from"] is not None
    stored = db.get_atoms([old["atom_id"]])[0]
    assert stored.valid_to is not None
    assert db.atom_count() == 2


def test_supersede_names_the_missing_atom(db: Database) -> None:
    result = runner.invoke(app, ["supersede", "nope:text", "新的说法"])
    assert result.exit_code != 0
    assert "cannot supersede nope:text" in str(result.exception)


def test_forget_reports_what_it_removed(db: Database) -> None:
    atom = run("remember", "钥匙在玄关抽屉", "--holder", "wife")
    report = run("forget", "--source-id", atom["source_id"], "--reason", "moved house")
    assert report["atoms_deleted"] == 1
    assert report["reason"] == "moved house"
    assert db.atom_count() == 0


def test_forget_refuses_to_guess_between_two_ids(db: Database) -> None:
    result = runner.invoke(app, ["forget", "--atom-id", "a:text", "--source-id", "b"])
    assert result.exit_code != 0
    assert "exactly one of atom_id or source_id" in str(result.exception)


def test_the_cli_answers_in_json_a_machine_can_read(db: Database) -> None:
    result = runner.invoke(app, ["remember", "钥匙在玄关抽屉", "--holder", "wife"])
    assert result.exit_code == 0
    assert json.loads(result.output)["text"] == "钥匙在玄关抽屉"


def test_working_lists_one_session_in_the_order_it_was_recorded(db: Database) -> None:
    first = run("remember", "烤箱要除垢", "--session", "cooking")
    second = run("remember", "面粉在储物架第二层", "--session", "cooking")
    run("remember", "周报周五交")

    working = run("working", "husband", "cooking")

    assert [atom["atom_id"] for atom in working] == [first["atom_id"], second["atom_id"]]


def test_working_refuses_to_guess_which_session_is_working(db: Database) -> None:
    result = runner.invoke(app, ["working", "husband", ""])
    assert result.exit_code != 0
    assert "a working set needs a session" in str(result.exception)


def test_consolidate_rolls_a_lane_up_once_and_then_says_nothing_new(db: Database) -> None:
    run("remember", "烤箱要除垢", "--scenario", "home")
    record = run("consolidate", "--scenario", "home", "--holder", "husband")
    assert record["atom_count"] == 1 and record["rollup_atom_id"]

    result = runner.invoke(app, ["consolidate", "--scenario", "home", "--holder", "husband"])
    assert result.exit_code == 0
    assert result.output.strip() == "nothing new to roll up"


def test_the_archive_can_be_read_before_it_moves_anything(db: Database) -> None:
    atom = run("remember", "前租户的 wifi 密码")

    preview = run("archive", "--older-than-days", "0", "--dry-run")
    assert preview["dry_run"] is True and preview["atom_ids"] == [atom["atom_id"]]
    assert run("archived") == []

    moved = run("archive", "--older-than-days", "0")
    assert moved["dry_run"] is False and moved["atom_ids"] == [atom["atom_id"]]
    assert [row["atom_id"] for row in run("archived")] == [atom["atom_id"]]
    assert run("memory-restore", atom["atom_id"]) == {"restored": 1}
    assert run("archived") == []


def test_the_cli_shows_and_settles_a_disagreement(db: Database) -> None:
    run("remember", "恒温器放在书房，设定 22 度", "--scenario", "home")
    run("remember", "恒温器调到 24 度", "--scenario", "home")

    listed = run("conflicts", "--holder", "husband")
    assert len(listed) == 1
    assert listed[0]["older_value"] == "22" and listed[0]["newer_value"] == "24"

    assert run("resolve-conflicts", str(listed[0]["conflict_id"])) == {"resolved": 1}
    assert run("conflicts", "--holder", "husband") == []
