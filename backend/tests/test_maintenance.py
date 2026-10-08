"""Backup, restore and doctor: a store nobody can move is a store nobody trusts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ely_eye import cli as cli_module
from ely_eye import maintenance
from ely_eye.cartridge_store import set_mounts
from ely_eye.cli import app
from ely_eye.config import Settings
from ely_eye.db import Database
from ely_eye.memory import MemoryService
from ely_eye.migrations import SCHEMA_VERSION
from ely_eye.schemas import EvidenceAtom, MemoryOrigin, Modality, SourceRecord, TrustScores, utc_now
from ely_eye.storage import ObjectStore

KEYS = "the keys are on the shelf by the door"
PASSPORT = "the passport is in the blue box"


def _settings(tmp_path: Path) -> Settings:
    return Settings(home=tmp_path / "home", default_holder="wife")


def _store(settings: Settings, statements: tuple[str, ...] = (KEYS, PASSPORT)) -> Database:
    database = Database(settings)
    database.init()
    service = MemoryService(settings, database)
    for statement in statements:
        service.remember(statement, holder_id="wife", origin=MemoryOrigin.self_)
    return database


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_backup_carries_the_store_and_says_what_it_holds(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _store(settings)
    manifest = maintenance.backup(settings, tmp_path / "backup")
    assert (tmp_path / "backup" / maintenance.BACKUP_FILE).is_file()
    assert (tmp_path / "backup" / maintenance.MANIFEST_FILE).is_file()
    assert manifest.atoms == 2
    assert manifest.sources == 2
    assert manifest.cartridges == 0
    assert manifest.schema_version == SCHEMA_VERSION
    written = tmp_path / "backup" / maintenance.BACKUP_FILE
    assert manifest.sha256 == _digest(written)
    assert manifest.size_bytes == written.stat().st_size


def test_a_backup_refuses_to_overwrite_itself_without_permission(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _store(settings)
    maintenance.backup(settings, tmp_path / "backup")
    with pytest.raises(ValueError, match="already holds a backup"):
        maintenance.backup(settings, tmp_path / "backup")
    assert maintenance.backup(settings, tmp_path / "backup", force=True).atoms == 2


def test_backup_names_the_store_it_cannot_find(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(ValueError, match="nothing to back up"):
        maintenance.backup(settings, tmp_path / "backup")


def test_a_restore_brings_the_memories_back(tmp_path: Path) -> None:
    source = _settings(tmp_path)
    _store(source)
    manifest = maintenance.backup(source, tmp_path / "backup")
    destination = Settings(home=tmp_path / "elsewhere", default_holder="wife")
    restored = maintenance.restore(destination, tmp_path / "backup")
    assert restored.path == str(destination.db_path)
    assert manifest.atoms == 2
    database = Database(destination)
    assert database.atom_count() == 2
    assert {atom.text for atom in database.list_atoms()} == {KEYS, PASSPORT}


def test_a_restore_keeps_the_store_it_replaces(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _store(settings)
    maintenance.backup(settings, tmp_path / "backup")
    _store(settings, statements=("only one memory here",))
    with pytest.raises(ValueError, match="pass --force"):
        maintenance.restore(settings, tmp_path / "backup")
    maintenance.restore(settings, tmp_path / "backup", force=True)
    kept = settings.db_path.with_suffix(".before-restore")
    assert kept.is_file()
    with sqlite3.connect(kept) as connection:
        kept_atoms = int(connection.execute("SELECT COUNT(*) FROM atoms").fetchone()[0])
    assert kept_atoms == 3
    assert Database(settings).atom_count() == 2


def test_a_tampered_backup_is_refused(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _store(settings)
    maintenance.backup(settings, tmp_path / "backup")
    database_file = tmp_path / "backup" / maintenance.BACKUP_FILE
    database_file.write_bytes(database_file.read_bytes() + b"\x00")
    with pytest.raises(ValueError, match="does not match its manifest"):
        maintenance.restore(Settings(home=tmp_path / "elsewhere"), tmp_path / "backup")


def test_a_backup_from_a_newer_build_is_refused(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _store(settings)
    maintenance.backup(settings, tmp_path / "backup")
    database_file = tmp_path / "backup" / maintenance.BACKUP_FILE
    with sqlite3.connect(database_file) as connection:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 7}")
    manifest_path = tmp_path / "backup" / maintenance.MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = SCHEMA_VERSION + 7
    manifest["sha256"] = _digest(database_file)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="newer build"):
        maintenance.restore(Settings(home=tmp_path / "elsewhere"), tmp_path / "backup")


def test_a_folder_without_the_backup_pair_is_refused(tmp_path: Path) -> None:
    (tmp_path / "backup").mkdir()
    with pytest.raises(ValueError, match="is not a backup"):
        maintenance.restore(_settings(tmp_path), tmp_path / "backup")


def test_doctor_reports_a_store_that_does_not_exist_yet(tmp_path: Path) -> None:
    report = maintenance.doctor(_settings(tmp_path))
    assert report.ok is False
    assert len(report.problems) == 1
    assert "no memory store" in report.problems[0]
    assert report.atoms == 0


def test_doctor_passes_a_healthy_store(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _store(settings)
    report = maintenance.doctor(settings)
    assert report.ok is True
    assert report.problems == []
    assert report.atoms == 2
    assert report.sources == 2
    assert report.schema_version == SCHEMA_VERSION


def test_doctor_names_the_senses_a_store_holds_but_cannot_use(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = Database(settings)
    database.init()
    trust = TrustScores(parser=0.0, ocr=0.0, model=0.0)
    database.upsert_sources(
        [
            SourceRecord(source_id="img", path="file:///img.png", kind="image", mime="image/png", sha256="a", size_bytes=1),
            SourceRecord(source_id="aud", path="file:///a.mp3", kind="audio", mime="audio/mpeg", sha256="b", size_bytes=1),
        ]
    )
    database.upsert_atoms(
        [
            EvidenceAtom(
                atom_id="img:1",
                modality=Modality.image,
                source_id="img",
                source="file:///img.png",
                trust=trust,
                image_ref=ObjectStore(settings).put_bytes(b"\x89PNG\r\n\x1a\n", ".png", "image"),
            ),
            EvidenceAtom(atom_id="aud:1", modality=Modality.audio, source_id="aud", source="file:///a.mp3", trust=trust),
        ]
    )
    report = maintenance.doctor(settings)
    assert report.ok is True
    assert len(report.warnings) == 2
    assert "1 picture atom but no CLIP snapshot" in report.warnings[0]
    assert "1 audio atom but no speech snapshot" in report.warnings[1]


def test_doctor_names_picture_atoms_whose_bytes_are_gone(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = Database(settings)
    database.init()
    trust = TrustScores(parser=0.0, ocr=0.0, model=0.0)
    database.upsert_sources(
        [SourceRecord(source_id="img", path="file:///img.png", kind="image", mime="image/png", sha256="a", size_bytes=1)]
    )
    database.upsert_atoms(
        [
            EvidenceAtom(
                atom_id="img:1",
                modality=Modality.image,
                source_id="img",
                source="file:///img.png",
                trust=trust,
                image_ref="object://image/ab/deadbeef.png",
            )
        ]
    )
    report = maintenance.doctor(settings)
    assert "1 picture atom with no bytes behind them" in report.warnings[0]


def test_doctor_names_a_mount_whose_files_are_gone(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = _store(settings)
    database.write_cartridge(
        "cart-a", "Cart A", tmp_path / "gone", "{}", "dna", 10, utc_now()
    )
    set_mounts(database, ["cart-a"], utc_now())
    report = maintenance.doctor(settings)
    assert report.ok is False
    assert report.mounted == ["cart-a"]
    assert len(report.problems) == 1
    assert "is mounted but its files at" in report.problems[0]


def test_doctor_refuses_a_store_written_by_a_newer_build(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _store(settings)
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 7}")
    report = maintenance.doctor(settings)
    assert report.ok is False
    assert len(report.problems) == 1
    assert "this build understands" in report.problems[0]


def test_the_cli_backs_up_and_a_restore_bring_the_store_home(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    settings = _settings(tmp_path)
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)

    empty = runner.invoke(app, ["doctor"])
    assert empty.exit_code == 1
    assert "no memory store" in empty.output

    _store(settings)
    healthy = runner.invoke(app, ["doctor"])
    assert healthy.exit_code == 0
    assert json.loads(healthy.output)["atoms"] == 2

    backed_up = runner.invoke(app, ["backup", str(tmp_path / "backup")])
    assert backed_up.exit_code == 0
    assert json.loads(backed_up.output)["sha256"]

    elsewhere = Settings(home=tmp_path / "elsewhere", default_holder="wife")
    monkeypatch.setattr(cli_module, "get_settings", lambda: elsewhere)
    moved = runner.invoke(app, ["restore", str(tmp_path / "backup")])
    assert moved.exit_code == 0
    assert Database(elsewhere).atom_count() == 2
