"""The memory model must carry holder, origin, time and scenario, and an old database must survive."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ely_eye.config import Settings
from ely_eye.db import Database
from ely_eye.migrations import SCHEMA_VERSION
from ely_eye.schemas import (
    EvidenceAtom,
    MemoryOrigin,
    Modality,
    SourceRecord,
    TimePrecision,
    TrustScores,
    Visibility,
)

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def _atom(atom_id: str, **overrides: object) -> EvidenceAtom:
    fields: dict[str, object] = {
        "atom_id": atom_id,
        "modality": Modality.text,
        "source_id": "src-1",
        "source": "notes/key.txt",
        "ingested_at": NOW,
        "text": "钥匙放在玄关抽屉里",
        "trust": TrustScores(parser=1.0),
        "token_equivalent": 8,
        "holder_id": "wife",
        "origin": MemoryOrigin.self_,
        "scenario": "home",
        "event_time": NOW - timedelta(days=1),
        "event_time_precision": TimePrecision.day,
        "event_time_source": "declared",
        "valid_from": NOW - timedelta(days=1),
    }
    fields.update(overrides)
    return EvidenceAtom(**fields)  # type: ignore[arg-type]


def _database(home: Path) -> Database:
    return Database(Settings(home=home))


def _seed_source(database: Database) -> None:
    database.upsert_sources(
        [
            SourceRecord(
                source_id="src-1",
                path="/tmp/key.txt",
                kind="text",
                mime="text/plain",
                sha256="0" * 64,
                size_bytes=12,
                created_at=NOW,
            )
        ]
    )


def _atom_columns(database: Database) -> set[str]:
    with database.connect() as connection:
        return {row[1] for row in connection.execute("PRAGMA table_info(atoms)")}


def test_a_fresh_database_carries_the_four_memory_dimensions(tmp_path: Path) -> None:
    database = _database(tmp_path)
    columns = _atom_columns(database)
    for column in (
        "holder_id",
        "origin",
        "scenario",
        "event_time",
        "event_time_end",
        "event_time_precision",
        "event_time_source",
        "valid_from",
        "valid_to",
        "supersedes_json",
        "visibility_json",
        "retention_until",
        "ingested_at",
    ):
        assert column in columns, column
    assert "time" not in columns, "ingestion time has one name: ingested_at"
    with database.connect() as connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION


def test_an_atom_round_trips_every_memory_dimension(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_source(database)
    atom = _atom(
        "atom-1",
        event_time_end=NOW - timedelta(hours=6),
        valid_to=NOW + timedelta(days=2),
        supersedes=["atom-0"],
        visibility=Visibility(scope="visible_to", holders=["husband"], purpose="household"),
        retention_until=NOW + timedelta(days=30),
    )
    database.upsert_atoms([atom])
    stored = database.get_atoms(["atom-1"])[0]
    assert stored.holder_id == "wife"
    assert stored.origin is MemoryOrigin.self_
    assert stored.scenario == "home"
    assert stored.event_time == atom.event_time
    assert stored.event_time_end == atom.event_time_end
    assert stored.event_time_precision is TimePrecision.day
    assert stored.event_time_source == "declared"
    assert stored.valid_from == atom.valid_from
    assert stored.valid_to == atom.valid_to
    assert stored.supersedes == ["atom-0"]
    assert stored.visibility.holders == ["husband"]
    assert stored.visibility.purpose == "household"
    assert stored.retention_until == atom.retention_until
    assert stored.ingested_at == NOW


def test_a_first_version_database_upgrades_in_place_and_keeps_its_rows(tmp_path: Path) -> None:
    path = tmp_path / "data" / "ely_eye.sqlite"
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE sources (
            source_id TEXT PRIMARY KEY, path TEXT NOT NULL, kind TEXT NOT NULL, mime TEXT NOT NULL,
            sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL, created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        );
        CREATE TABLE atoms (
            atom_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, modality TEXT NOT NULL,
            source TEXT NOT NULL, time TEXT NOT NULL, text TEXT NOT NULL, image_ref TEXT,
            embedding_refs_json TEXT NOT NULL, layout_json TEXT, relations_json TEXT NOT NULL,
            trust_json TEXT NOT NULL, token_equivalent INTEGER NOT NULL, metadata_json TEXT NOT NULL
        );
        INSERT INTO atoms VALUES (
            'legacy-1', 'src-1', 'text', 'old.txt', '2026-01-02T03:04:05+00:00', 'old memory',
            NULL, '[]', NULL, '[]', '{"parser": 1.0}', 4, '{}'
        );
        """
    )
    connection.commit()
    connection.close()

    database = _database(tmp_path)
    assert _atom_columns(database) >= {"holder_id", "origin", "valid_from", "ingested_at"}
    legacy = database.get_atoms(["legacy-1"])[0]
    assert legacy.text == "old memory"
    assert legacy.ingested_at == datetime.fromisoformat("2026-01-02T03:04:05+00:00")
    assert legacy.holder_id == "", "a legacy row has no known holder, and must not invent one"
    assert legacy.origin is MemoryOrigin.artifact


def test_v_atoms_current_hides_closed_retired_and_unbegun_memories(tmp_path: Path) -> None:
    """The view answers 'what is usable right now', so it is written against the real clock."""
    moment = datetime.now(UTC)
    database = _database(tmp_path)
    _seed_source(database)
    database.upsert_atoms(
        [
            _atom("live"),
            _atom("closed", valid_to=moment - timedelta(days=1)),
            _atom("lapsed", retention_until=moment - timedelta(days=1)),
            _atom("future", valid_from=moment + timedelta(days=5)),
        ]
    )
    with database.connect() as connection:
        visible = {row["atom_id"] for row in connection.execute("SELECT atom_id FROM v_atoms_current")}
    assert visible == {"live"}
    assert database.atom_count() == 4, "the view hides, it does not delete"


def test_an_unknown_origin_is_refused_by_the_database(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_source(database)
    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO atoms (atom_id, source_id, modality, source, ingested_at, text, "
                "embedding_refs_json, relations_json, trust_json, token_equivalent, metadata_json, origin) "
                "VALUES ('x', 'src-1', 'text', 's', '2026-05-01T12:00:00+00:00', 't', '[]', '[]', "
                "'{\"parser\": 1.0}', 1, '{}', 'whispered')"
            )


def test_the_schema_refuses_a_database_newer_than_this_build(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connect() as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(SystemExit, match="understands"):
        _database(tmp_path)


def test_times_must_be_ordered_and_an_atom_cannot_supersede_itself() -> None:
    with pytest.raises(ValueError, match="valid_to precedes valid_from"):
        _atom("bad-1", valid_from=NOW, valid_to=NOW - timedelta(days=1))
    with pytest.raises(ValueError, match="event_time_end precedes event_time"):
        _atom("bad-2", event_time=NOW, event_time_end=NOW - timedelta(days=1))
    with pytest.raises(ValueError, match="cannot supersede itself"):
        _atom("bad-3", supersedes=["bad-3"])


def test_atoms_as_of_walks_the_validity_timeline(tmp_path: Path) -> None:
    """Time travel is a method because a SQLite view cannot take a parameter."""
    database = _database(tmp_path)
    _seed_source(database)
    database.upsert_atoms(
        [
            _atom("live"),
            _atom("closed", valid_from=NOW - timedelta(days=10), valid_to=NOW - timedelta(days=1)),
            _atom("future", valid_from=NOW + timedelta(days=5)),
        ]
    )
    assert {atom.atom_id for atom in database.atoms_as_of(NOW)} == {"live"}
    assert {atom.atom_id for atom in database.atoms_as_of(NOW - timedelta(days=2))} == {"closed"}
    assert database.atoms_as_of(NOW, holder="nobody") == []
    assert {atom.atom_id for atom in database.atoms_as_of(NOW, holder="wife")} == {"live"}
