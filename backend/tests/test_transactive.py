"""The transactive test: I do not know where the keys are, I know my wife knows, I find my wife."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from typer.testing import CliRunner

import elysium.api as api_module
import elysium.cli as cli_module
from elysium.cli import app
from elysium.config import Settings
from elysium.db import Database
from elysium.holder_store import HolderStore
from elysium.ingestion import IngestionService
from elysium.memory import MemoryService
from elysium.migrations import SCHEMA_VERSION
from elysium.schemas import MemoryOrigin, Visibility, utc_now
from elysium.transactive import LIBRARY, NO_HOLDER_KNOWS, TransactiveService
from elysium.transactive_schemas import Holder

HOME_KEYS = "我们的钥匙放在玄关抽屉里"
WORK_KEYS = "备用钥匙在办公室第二个抽屉里"
QUERY = "钥匙"


class Store:
    """One SQLite file, the writer and the directory that read it."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.memory = MemoryService(settings=settings)
        self.db = self.memory.db
        self.transactive = TransactiveService(settings=settings, database=self.db)

    def wife_remembers(self, text: str, visibility: Visibility | None = None) -> str:
        atom = self.memory.remember(
            text, holder_id="wife", origin=MemoryOrigin.self_, scenario="home", visibility=visibility
        )
        return atom.atom_id

    def husband_remembers(self, text: str) -> str:
        atom = self.memory.remember(text, holder_id="husband", origin=MemoryOrigin.self_, scenario="home")
        return atom.atom_id

    def register(self, holder_id: str, **fields: Any) -> Holder:
        moment = utc_now()
        return self.transactive.holders.upsert(
            Holder(holder_id=holder_id, created_at=moment, updated_at=moment, **fields)
        )


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(Settings(home=tmp_path / "home", default_holder="husband"))


def test_the_directory_names_the_holder_and_says_why(store: Store) -> None:
    store.wife_remembers(HOME_KEYS)
    report = store.transactive.who_knows(QUERY, as_holder="husband")
    assert report.status == "found"
    assert report.hits[0].holder_id == "wife"
    assert report.hits[0].confidence > 0.0
    assert any("matching memories" in line for line in report.hits[0].basis)


def test_the_directory_counts_a_memory_the_asker_cannot_read(store: Store) -> None:
    """The whole point: knowing that she knows does not require reading her memory."""
    store.wife_remembers(HOME_KEYS)
    assert store.transactive.who_knows(QUERY, as_holder="husband").hits[0].matched == 1
    assert store.transactive._search(QUERY, as_holder="husband", holder="wife") == []


def test_a_private_memory_is_referred_and_not_leaked(store: Store) -> None:
    store.register("wife", name="小美", contact={"channel": "signal", "address": "+86-555"})
    store.wife_remembers(HOME_KEYS)
    answer = store.transactive.ask("钥匙在哪里", as_holder="husband")
    assert answer.status == "referred"
    assert answer.answered_by == "wife"
    assert answer.hops == 1
    assert answer.asked == ["husband", "wife"]
    assert answer.answer is None
    assert answer.atom_ids == []
    assert any("may not read" in line for line in answer.basis)
    assert any("signal" in line for line in answer.basis)


def test_the_askers_own_memory_answers_without_a_referral(store: Store) -> None:
    store.wife_remembers(HOME_KEYS)
    store.husband_remembers("我的工牌挂在显示器边上")
    answer = store.transactive.ask("工牌", as_holder="husband")
    assert answer.status == "answered"
    assert answer.answered_by == "husband"
    assert answer.hops == 0
    assert answer.asked == ["husband"]
    assert answer.answer is None


def test_text_shown_only_when_the_asker_may_already_read_it(store: Store) -> None:
    store.husband_remembers("我的工牌挂在显示器边上")
    with_text = store.transactive.ask("工牌", as_holder="husband", include_text=True)
    assert with_text.answer == "我的工牌挂在显示器边上"

    store.register("wife")
    store.wife_remembers(HOME_KEYS)
    referred = store.transactive.ask("钥匙在哪里", as_holder="husband", include_text=True)
    assert referred.status == "referred"
    assert referred.answer is None


def test_a_shared_memory_is_readable_without_a_referral(store: Store) -> None:
    """A memory the asker may already read answers at hop 0: no referral, the text is shown."""
    store.register("wife")
    store.wife_remembers(HOME_KEYS, visibility=Visibility(scope="visible_to", holders=["husband"]))
    answer = store.transactive.ask("钥匙在哪里", as_holder="husband", include_text=True)
    assert answer.status == "answered"
    assert answer.answered_by == "wife"
    assert answer.hops == 0
    assert answer.answer == HOME_KEYS


def test_an_unowned_artifact_answers_as_the_library(store: Store) -> None:
    notebook = store.settings.home / "notebook.txt"
    notebook.write_text("the garage door code is written on the fuse box", encoding="utf-8")
    IngestionService(store.settings).ingest_path(notebook)
    answer = store.transactive.ask("garage door code", as_holder="wife", include_text=True)
    assert answer.status == "answered"
    assert answer.answered_by == LIBRARY
    assert "fuse box" in (answer.answer or "")


def test_nobody_knows_is_a_result_and_not_a_fabrication(store: Store) -> None:
    store.wife_remembers(HOME_KEYS)
    report = store.transactive.who_knows("潜水镜", as_holder="husband")
    assert report.status == NO_HOLDER_KNOWS
    assert report.hits == []

    answer = store.transactive.ask("潜水镜在哪里", as_holder="husband")
    assert answer.status == NO_HOLDER_KNOWS
    assert answer.answered_by is None
    assert answer.answer is None
    assert answer.basis == ["no holder has a memory that answers this"]


def test_the_referral_walks_once_and_never_asks_the_same_holder_twice(store: Store) -> None:
    store.register("wife")
    store.register("daughter")
    store.wife_remembers(HOME_KEYS)
    store.memory.remember(WORK_KEYS, holder_id="daughter", origin=MemoryOrigin.self_, scenario="work")
    answer = store.transactive.ask("钥匙在哪里", as_holder="husband", max_hops=1)
    assert answer.status in ("referred", "answered")
    assert len(answer.asked) == 2
    assert len(set(answer.asked)) == len(answer.asked)
    assert answer.asked[0] == "husband"


def test_the_hop_limit_is_enforced(store: Store) -> None:
    for bad in (0, 11):
        with pytest.raises(ValueError, match="max_hops between 1 and 10"):
            store.transactive.ask(QUERY, as_holder="husband", max_hops=bad)


def test_declared_topics_raise_the_confidence_and_say_so(store: Store) -> None:
    store.wife_remembers(HOME_KEYS)
    before = store.transactive.who_knows(QUERY, as_holder="husband").hits[0]
    store.register("wife", knows_about=["家里的钥匙"])
    after = store.transactive.who_knows(QUERY, as_holder="husband").hits[0]
    assert after.confidence > before.confidence
    assert any("declared topics" in line for line in after.basis)


def test_the_registry_refuses_to_delete_a_holder_who_still_holds(store: Store) -> None:
    store.register("wife")
    atom_id = store.wife_remembers(HOME_KEYS)
    with pytest.raises(ValueError, match="still holds 1 memories"):
        store.transactive.holders.delete("wife")
    store.memory.forget(atom_id=atom_id)
    store.transactive.holders.delete("wife")
    assert store.transactive.holders.list_holders() == []


def test_an_unknown_holder_kind_is_refused_at_the_door() -> None:
    with pytest.raises(ValidationError, match="'person', 'agent' or 'service'"):
        Holder.model_validate({"holder_id": "ghost", "kind": "ghost", "created_at": utc_now(), "updated_at": utc_now()})


def test_a_blank_holder_id_is_refused() -> None:
    with pytest.raises(ValidationError, match="directory entry has to name somebody"):
        Holder.model_validate({"holder_id": "  ", "created_at": utc_now(), "updated_at": utc_now()})


def test_a_store_without_holders_gains_the_table_on_reopen(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path / "home", default_holder="husband")
    database = Database(settings)
    with database.connect() as connection:
        connection.execute("DROP TABLE holders")
        connection.execute("PRAGMA user_version = 4")
    reopened = Database(settings)
    with reopened.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("SELECT COUNT(*) AS n FROM holders").fetchone()["n"] == 0


def test_the_http_surface_serves_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_token: str
) -> None:
    settings = Settings(home=tmp_path / "home", default_holder="husband", auth_token=write_token)
    monkeypatch.setattr(api_module, "get_settings", lambda: settings)
    client = TestClient(api_module.create_app(), headers={"Authorization": f"Bearer {write_token}"})

    store = Store(settings)
    store.wife_remembers(HOME_KEYS)

    created = client.post(
        "/api/holders/wife",
        json={"name": "小美", "knows_about": ["家里的钥匙"], "contact": {"channel": "signal"}},
    )
    assert created.status_code == 200
    assert created.json()["holder_id"] == "wife"
    assert client.get("/api/holders").json()[0]["name"] == "小美"
    assert client.get("/api/holders/nobody").status_code == 404

    knows = client.get("/api/holders/wife/knows", params={"query": QUERY}).json()
    assert knows["status"] == "found" and knows["hits"][0]["holder_id"] == "wife"

    asked = client.post("/api/ask", json={"question": "钥匙在哪里", "as_holder": "husband"}).json()
    assert asked["status"] == "referred" and asked["answered_by"] == "wife"

    who = client.post("/api/who_knows", json={"query": "钥匙", "as_holder": "husband"}).json()
    assert who["hits"][0]["basis"]

    blocked = client.delete("/api/holders/wife")
    assert blocked.status_code == 409 and "still holds" in blocked.json()["detail"]


def test_the_cli_asks_and_reports_the_referral(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(home=tmp_path / "home", default_holder="husband")
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    runner = CliRunner()
    Store(settings).wife_remembers(HOME_KEYS)

    assert runner.invoke(app, ["holder-set", "wife", "--name", "小美", "--contact", "channel=signal"]).exit_code == 0
    who = runner.invoke(app, ["who-knows", QUERY])
    assert who.exit_code == 0 and '"holder_id": "wife"' in who.stdout
    asked = runner.invoke(app, ["ask", "钥匙在哪里"])
    assert asked.exit_code == 0 and '"status": "referred"' in asked.stdout
    assert runner.invoke(app, ["holders"]).stdout.count("wife") >= 1
    assert runner.invoke(app, ["holder-set", "wife", "--contact", "not-a-pair"]).exit_code != 0


def test_the_cli_mints_a_token_that_proves_who_is_asking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(home=tmp_path / "home", default_holder="husband")
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    runner = CliRunner()
    Store(settings).wife_remembers(HOME_KEYS)

    issued = json.loads(runner.invoke(app, ["holder-issue", "wife"]).stdout)
    assert issued["holder_id"] == "wife" and issued["token"] and issued["issued_at"]
    assert HolderStore(Database(settings)).verify_token(issued["token"]) == "wife"
    assert issued["token"] not in runner.invoke(app, ["card"]).stdout, "the card is public and the token is not"

    revoked = json.loads(runner.invoke(app, ["holder-revoke", "wife"]).stdout)
    assert revoked["holder_id"] == "wife" and revoked["token_issued_at"] is None
    assert HolderStore(Database(settings)).verify_token(issued["token"]) is None


def test_the_card_is_read_back_from_the_store_rather_than_written_by_hand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(home=tmp_path / "home", default_holder="husband")
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    runner = CliRunner()
    store = Store(settings)
    store.wife_remembers(HOME_KEYS)
    store.husband_remembers(WORK_KEYS)
    store.register("neighbour", name="邻居", knows_about=["weather"])

    answer = runner.invoke(app, ["card"])
    assert answer.exit_code == 0, answer.stdout
    card = json.loads(answer.stdout)
    assert card["schema_version"] == SCHEMA_VERSION
    assert card["atoms"] == 2 and card["sources"] == 2
    assert card["modalities"] == {"text": 2} and card["has_audio"] is False
    assert card["mounts"] == {"mounted": [], "scoped": False, "atoms_in_scope": 0}

    named = {entry["holder_id"]: entry for entry in card["holders"]}
    assert named["wife"]["memories"] == 1 and named["wife"]["scenarios"] == ["home"]
    assert named["wife"]["newest_memory"], "a caller needs to know how stale the answer would be"
    assert named["neighbour"]["memories"] == 0 and named["neighbour"]["knows_about"] == ["weather"]
    assert HOME_KEYS not in answer.stdout, "the card says what a holder holds, never what they hold it to be"
