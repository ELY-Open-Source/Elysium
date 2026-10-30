"""A cartridge is a retrieval scope: mount it and only it answers, append and the bundle follows."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import elysian.api as api_module
import elysian.cli as cli_module
from elysian import cartridge_store
from elysian.cartridge import CartridgeService
from elysian.cli import app
from elysian.config import Settings
from elysian.db import Database
from elysian.memory import MemoryService
from elysian.migrations import SCHEMA_VERSION
from elysian.retrieval import RetrievalService
from elysian.schemas import MemoryOrigin, SearchFilters

HOME_KEYS = "我们的钥匙放在玄关抽屉里"
WORK_KEYS = "备用钥匙在办公室第二个抽屉里"


class Store:
    """One SQLite file, the four services that read and write it."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.memory = MemoryService(settings=settings)
        self.db = self.memory.db
        self.cartridges = CartridgeService(settings=settings, database=self.db)
        self.search = RetrievalService(settings=settings, database=self.db)

    def remember(self, text: str, scenario: str) -> str:
        atom = self.memory.remember(
            text, holder_id="wife", origin=MemoryOrigin.self_, scenario=scenario
        )
        return atom.atom_id

    def cartridge(self, name: str, atom_ids: list[str]) -> str:
        atoms = self.db.get_atoms(atom_ids)
        sources = self.db.get_sources(sorted({atom.source_id for atom in atoms}))
        return self.cartridges.materialize(name, atoms, sources).cartridge_id

    def texts(self, query: str = "钥匙", **filters: Any) -> list[str]:
        eyes: dict[str, Any] = {"as_holder": "wife", **filters}
        result = self.search.search(query, filters=SearchFilters(**eyes))
        return [hit.atom.text for hit in result.hits]


@pytest.fixture
def store(tmp_path: Path, model_dir: Path) -> Store:
    return Store(Settings(home=tmp_path / "home", model_dir=model_dir, default_holder="wife"))


def test_mounting_one_cartridge_stops_the_other_from_answering(store: Store) -> None:
    home = store.cartridge("home", [store.remember(HOME_KEYS, "home")])
    work = store.cartridge("work", [store.remember(WORK_KEYS, "work")])
    assert sorted(store.texts()) == sorted([HOME_KEYS, WORK_KEYS])

    store.cartridges.switch(home)
    assert store.texts() == [HOME_KEYS]
    store.cartridges.switch(work)
    assert store.texts() == [WORK_KEYS]


def test_an_explicit_scope_overrides_what_is_mounted(store: Store) -> None:
    home = store.cartridge("home", [store.remember(HOME_KEYS, "home")])
    work = store.cartridge("work", [store.remember(WORK_KEYS, "work")])
    store.cartridges.switch(home)
    assert store.texts(cartridge_ids=[work]) == [WORK_KEYS]


def test_nothing_mounted_answers_from_the_whole_library(store: Store) -> None:
    store.cartridge("home", [store.remember(HOME_KEYS, "home")])
    state = store.cartridges.mount_state()
    assert state.mounted == []
    assert state.scoped is False
    assert state.atoms_in_scope == 0
    assert store.texts() == [HOME_KEYS]


def test_mounting_two_cartridges_answers_from_both(store: Store) -> None:
    home = store.cartridge("home", [store.remember(HOME_KEYS, "home")])
    work = store.cartridge("work", [store.remember(WORK_KEYS, "work")])
    store.cartridges.mount(home)
    store.cartridges.mount(work)
    state = store.cartridges.mount_state()
    assert sorted(state.mounted) == sorted([home, work])
    assert state.atoms_in_scope == 2
    assert sorted(store.texts()) == sorted([HOME_KEYS, WORK_KEYS])


def test_unmounting_reports_the_state_and_refuses_a_stranger(store: Store) -> None:
    home = store.cartridge("home", [store.remember(HOME_KEYS, "home")])
    store.cartridges.mount(home)
    state = store.cartridges.unmount(home)
    assert state.mounted == [] and state.scoped is False
    with pytest.raises(ValueError, match=f"{home} is not mounted; nothing to unmount"):
        store.cartridges.unmount(home)


def test_append_adds_a_memory_and_the_bundle_follows(store: Store) -> None:
    home = store.cartridge("home", [store.remember(HOME_KEYS, "home")])
    before = next(m for m in store.cartridges.list_manifests() if m.cartridge_id == home)
    later = store.remember("备用钥匙在办公室第二个抽屉里", "home")
    after = store.cartridges.append(home, [later])

    assert after.dna != before.dna
    assert after.atom_count == before.atom_count + 1
    assert cartridge_store.membership_count(store.db, home) == 2
    rows = pq.read_table(store.settings.cartridge_dir / home / "atoms.parquet").num_rows
    assert rows == before.atom_count + 1

    store.cartridges.switch(home)
    assert sorted(store.texts()) == sorted([HOME_KEYS, WORK_KEYS])


def test_append_refuses_atoms_that_are_not_in_the_store(store: Store) -> None:
    home = store.cartridge("home", [store.remember(HOME_KEYS, "home")])
    with pytest.raises(ValueError, match="not in the store: mem-missing:text"):
        store.cartridges.append(home, ["mem-missing:text"])


def test_append_needs_something_to_append(store: Store) -> None:
    home = store.cartridge("home", [store.remember(HOME_KEYS, "home")])
    with pytest.raises(ValueError, match="append needs at least one atom"):
        store.cartridges.append(home, [])


def test_a_cartridge_without_a_fingerprint_cannot_be_mounted(store: Store) -> None:
    home = store.cartridge("home", [store.remember(HOME_KEYS, "home")])
    row = next(r for r in store.db.list_cartridges() if r["cartridge_id"] == home)
    manifest = json.loads(row["manifest_json"])
    manifest["kv_fingerprint"] = None
    store.db.write_cartridge(
        cartridge_id=home,
        name=row["name"],
        root_path=Path(row["root_path"]),
        manifest_json=json.dumps(manifest),
        dna=row["dna"],
        token_equivalent=row["token_equivalent"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )
    with pytest.raises(ValueError, match="carries no kv fingerprint; rebuild it before mounting"):
        store.cartridges.mount(home)


def test_a_mount_refuses_a_different_rope_and_names_the_field(
    store: Store, model_dir: Path, write_model_fixture: Callable[..., Path]
) -> None:
    home = store.cartridge("home", [store.remember(HOME_KEYS, "home")])
    write_model_fixture(model_dir, rope_parameters={"rope_type": "yarn", "factor": 2.0})
    with pytest.raises(ValueError, match="rope: factor: cartridge 4.0 vs local 2.0"):
        store.cartridges.mount(home)


def test_a_mount_refuses_when_the_machine_cannot_prove_the_model(store: Store) -> None:
    home = store.cartridge("home", [store.remember(HOME_KEYS, "home")])
    blind = CartridgeService(
        settings=Settings(home=store.settings.home, model_dir=None), database=store.db
    )
    with pytest.raises(ValueError, match="model_hash, tokenizer_hash, chat_template_hash, rope"):
        blind.mount(home)


def test_forgetting_a_memory_takes_it_out_of_the_cartridge(store: Store) -> None:
    atom_id = store.remember(HOME_KEYS, "home")
    home = store.cartridge("home", [atom_id])
    store.cartridges.mount(home)
    store.memory.forget(atom_id=atom_id, reason="moved")
    assert cartridge_store.membership_count(store.db, home) == 0
    assert store.texts() == []


def upload_home(client: TestClient) -> str:
    answer = client.post(
        "/api/ingest/upload?cartridge_name=home",
        files={"files": ("pantry.txt", b"the pantry keeps flour", "text/plain")},
    )
    assert answer.status_code == 200, answer.text
    return answer.json()["cartridge_id"]


def test_the_api_mounts_and_reports_the_scope(
    tmp_path: Path, model_dir: Path, monkeypatch: pytest.MonkeyPatch, write_token: str
) -> None:
    settings = Settings(
        home=tmp_path / "home", model_dir=model_dir, default_holder="wife", auth_token=write_token
    )
    monkeypatch.setattr(api_module, "get_settings", lambda: settings)
    client = TestClient(api_module.create_app(), headers={"Authorization": f"Bearer {write_token}"})

    atom = client.post("/api/memory", json={"text": HOME_KEYS, "scenario": "home"}).json()
    assert client.get("/api/mounts").json() == {"mounted": [], "scoped": False, "atoms_in_scope": 0}
    cartridge_id = upload_home(client)

    answer = client.post(f"/api/cartridges/{cartridge_id}/mount")
    assert answer.status_code == 200
    assert answer.json()["kv_fingerprint"]["rope"]["factor"] == 4.0
    assert client.get("/api/mounts").json() == {
        "mounted": [cartridge_id],
        "scoped": True,
        "atoms_in_scope": 2,
    }
    hits = client.post("/api/search", json={"query": "钥匙"}).json()["hits"]
    assert [hit["atom"]["atom_id"] for hit in hits] == [atom["atom_id"]]

    stranger = client.post("/api/cartridges/cartridge-does-not-exist/mount")
    assert stranger.status_code == 400 and "Unknown cartridge" in stranger.json()["detail"]
    assert client.post(f"/api/cartridges/{cartridge_id}/unmount").status_code == 200
    assert client.post(f"/api/cartridges/{cartridge_id}/unmount").status_code == 400


def test_the_api_appends_and_refuses_an_unknown_atom(
    tmp_path: Path, model_dir: Path, monkeypatch: pytest.MonkeyPatch, write_token: str
) -> None:
    settings = Settings(
        home=tmp_path / "home", model_dir=model_dir, default_holder="wife", auth_token=write_token
    )
    monkeypatch.setattr(api_module, "get_settings", lambda: settings)
    client = TestClient(api_module.create_app(), headers={"Authorization": f"Bearer {write_token}"})
    client.post("/api/memory", json={"text": HOME_KEYS, "scenario": "home"})
    cartridge_id = upload_home(client)

    answer = client.post(
        f"/api/cartridges/{cartridge_id}/append", json={"atom_ids": ["mem-nope:text"]}
    )
    assert answer.status_code == 400 and "not in the store" in answer.json()["detail"]

    extra = client.post("/api/memory", json={"text": WORK_KEYS, "scenario": "home"}).json()
    grown = client.post(
        f"/api/cartridges/{cartridge_id}/append", json={"atom_ids": [extra["atom_id"]]}
    )
    assert grown.status_code == 200 and grown.json()["atom_count"] == 3


def test_the_cli_mounts_and_answers_in_json(
    tmp_path: Path, model_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(home=tmp_path / "home", model_dir=model_dir, default_holder="wife")
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    runner = CliRunner()
    store = Store(settings)
    cartridge_id = store.cartridge("home", [store.remember(HOME_KEYS, "home")])

    mounted = runner.invoke(app, ["mount", cartridge_id])
    assert mounted.exit_code == 0, mounted.output
    assert json.loads(mounted.output)["cartridge_id"] == cartridge_id

    state = json.loads(runner.invoke(app, ["mounts"]).output)
    assert state == {"mounted": [cartridge_id], "scoped": True, "atoms_in_scope": 1}

    refused = runner.invoke(app, ["mount", "cartridge-does-not-exist"])
    assert isinstance(refused.exception, ValueError) and "Unknown cartridge" in str(
        refused.exception
    )


def test_a_third_version_store_gains_the_scope_tables_on_upgrade(
    tmp_path: Path, model_dir: Path
) -> None:
    settings = Settings(home=tmp_path / "home", model_dir=model_dir)
    first = Database(settings)
    with first.connect() as connection:
        connection.execute("DROP TABLE cartridge_atoms")
        connection.execute("DROP TABLE mounts")
        connection.execute("PRAGMA user_version = 3")

    reopened = Database(settings)
    with reopened.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert {"cartridge_atoms", "mounts"} <= tables
    assert version == SCHEMA_VERSION
    assert cartridge_store.mounted_ids(reopened) == []
