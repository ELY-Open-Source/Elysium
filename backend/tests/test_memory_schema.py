"""The memory model must carry holder, origin, time and scenario, and an old database must survive."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from elysian.config import Settings
from elysian.db import Database
from elysian.migrations import SCHEMA_VERSION
from elysian.schemas import (
    EvidenceAtom,
    MemoryOrigin,
    Modality,
    SourceRecord,
    TimePrecision,
    TrustScores,
    Visibility,
)
from elysian.store_search import search_fts

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
    path = tmp_path / "data" / "elysian.sqlite"
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


def test_a_second_version_database_rebuilds_its_index_on_upgrade(tmp_path: Path) -> None:
    """A second-version store indexed raw text, so 钥匙 could never match; the upgrade fixes the index."""
    database = _database(tmp_path)
    _seed_source(database)
    database.upsert_atoms([_atom("key")])
    with database.connect() as connection:
        connection.execute("DELETE FROM atom_fts")
        connection.execute(
            "INSERT INTO atom_fts(atom_id, source, text) VALUES ('key', 'notes/key.txt', '钥匙放在玄关抽屉里')"
        )
        connection.execute("PRAGMA user_version = 2")
    assert search_fts(database, "钥匙", 5) == [], "the old index really could not answer this query"

    upgraded = _database(tmp_path)
    assert [atom_id for atom_id, _ in search_fts(upgraded, "钥匙", 5)] == ["key"]
    with upgraded.connect() as connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION


def test_a_fresh_database_carries_the_tier_columns_and_their_tables(tmp_path: Path) -> None:
    database = _database(tmp_path)
    columns = _atom_columns(database)
    for column in (
        "session_id",
        "importance",
        "recall_count",
        "last_recalled_at",
        "archived_at",
    ):
        assert column in columns, column
    with database.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
    assert {"consolidations", "conflicts"} <= tables, (
        "a lane's watermark and a store's disagreements are state, so they live in tables"
    )


def test_the_current_view_hides_an_archived_memory_without_deleting_it(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_source(database)
    database.upsert_atoms([_atom("kept"), _atom("archived")])
    with database.connect() as connection:
        connection.execute(
            "UPDATE atoms SET archived_at = ? WHERE atom_id = 'archived'", (NOW.isoformat(),)
        )
        visible = connection.execute("SELECT atom_id FROM v_atoms_current ORDER BY atom_id").fetchall()
    assert [row[0] for row in visible] == ["kept"], "the archive is a tier, not a deletion"
    assert database.atom_count() == 2


def test_a_ninth_version_database_gains_the_tiers_in_place(tmp_path: Path) -> None:
    """A ninth-version store had no tiers at all; the upgrade must add them and rebuild the view."""
    database = _database(tmp_path)
    _seed_source(database)
    database.upsert_atoms([_atom("key")])
    with database.connect() as connection:
        # The downgrade removes what a ninth build never had, view and indexes included, so the reopened store really is ninth-version.
        connection.executescript(
            """
            DROP VIEW IF EXISTS v_atoms_current;
            DROP INDEX IF EXISTS idx_atoms_session;
            DROP INDEX IF EXISTS idx_atoms_archived;
            ALTER TABLE atoms DROP COLUMN session_id;
            ALTER TABLE atoms DROP COLUMN importance;
            ALTER TABLE atoms DROP COLUMN recall_count;
            ALTER TABLE atoms DROP COLUMN last_recalled_at;
            ALTER TABLE atoms DROP COLUMN archived_at;
            DROP TABLE consolidations;
            DROP TABLE conflicts;
            PRAGMA user_version = 9;
            """
        )

    upgraded = _database(tmp_path)
    assert "archived_at" in _atom_columns(upgraded)
    assert [atom.atom_id for atom in upgraded.list_atoms()] == ["key"], "the upgrade kept the memories"
    with upgraded.connect() as connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION
        connection.execute("UPDATE atoms SET archived_at = ? WHERE atom_id = 'key'", (NOW.isoformat(),))
        hidden = connection.execute("SELECT count(*) FROM v_atoms_current").fetchone()[0]
    assert hidden == 0, (
        "the old view body survived the upgrade, so an archived memory would still answer"
    )


def test_an_eleventh_version_database_learns_that_a_future_retirement_is_still_current(tmp_path: Path) -> None:
    """v11's view hid a memory whose retirement is scheduled for next year; the upgrade must rewrite the body."""
    clock = datetime.now(UTC)
    database = _database(tmp_path)
    _seed_source(database)
    database.upsert_atoms([_atom("key", ingested_at=clock, valid_from=clock, valid_to=clock + timedelta(days=365))])
    with database.connect() as connection:
        # The body v11 shipped, written out here so the upgrade is judged against the thing it replaced.
        connection.executescript(
            """
            DROP VIEW IF EXISTS v_atoms_current;
            CREATE VIEW v_atoms_current AS
              SELECT * FROM atoms
              WHERE valid_to IS NULL
                AND (valid_from IS NULL OR valid_from <= strftime('%Y-%m-%dT%H:%M:%f+00:00','now'))
                AND (retention_until IS NULL OR retention_until >= strftime('%Y-%m-%dT%H:%M:%f+00:00','now'));
            PRAGMA user_version = 11;
            """
        )
        hidden = connection.execute("SELECT count(*) FROM v_atoms_current").fetchone()[0]
    assert hidden == 0, "the fixture must really look like a v11 store before it is upgraded"

    upgraded = _database(tmp_path)
    with upgraded.connect() as connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION
        visible = [str(row[0]) for row in connection.execute("SELECT atom_id FROM v_atoms_current")]
    assert visible == ["key"], (
        "the old view body survived, so a memory retiring next year would answer nothing today"
    )


def _unlinked_index_rows(database: Database) -> int:
    with database.connect() as connection:
        return int(
            connection.execute(
                "SELECT count(*) FROM atom_fts AS f LEFT JOIN atoms AS a ON a.rowid = f.rowid AND a.atom_id = f.atom_id WHERE a.atom_id IS NULL"
            ).fetchone()[0]
        )


def test_every_index_row_sits_on_its_atoms_rowid_through_rewrites_and_deletes(tmp_path: Path) -> None:
    """A write finds its index row by rowid; matched by the unindexed atom_id, each write scanned the whole index."""
    database = _database(tmp_path)
    _seed_source(database)
    database.upsert_atoms([_atom("first"), _atom("second"), _atom("third")])
    database.upsert_atoms([_atom("second", text="the spare key hangs by the door")])
    database.delete_atoms(["third"])

    assert _unlinked_index_rows(database) == 0
    with database.connect() as connection:
        assert int(connection.execute("SELECT count(*) FROM atom_fts").fetchone()[0]) == 2
    assert [atom_id for atom_id, _ in search_fts(database, "spare", 5)] == ["second"]


def test_a_batch_naming_one_atom_twice_keeps_one_index_row(tmp_path: Path) -> None:
    """Two files with the same bytes give one atom_id; the second index insert must not hit the first's rowid."""
    database = _database(tmp_path)
    _seed_source(database)
    database.upsert_atoms([_atom("key", text="the key is in the drawer"), _atom("key", text="the key is by the door")])

    assert _unlinked_index_rows(database) == 0
    with database.connect() as connection:
        assert int(connection.execute("SELECT count(*) FROM atom_fts").fetchone()[0]) == 1
    assert database.get_atoms(["key"])[0].text == "the key is by the door"
    assert [atom_id for atom_id, _ in search_fts(database, "door", 5)] == ["key"]


def test_a_twelfth_version_database_moves_its_index_rows_onto_the_atoms_rowids(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_source(database)
    database.upsert_atoms([_atom("key")])
    with database.connect() as connection:
        connection.execute("DELETE FROM atom_fts")
        connection.execute("INSERT INTO atom_fts(rowid, atom_id, source, text) VALUES (999, 'key', 'notes/key.txt', '钥匙 放在 玄关')")
        connection.execute("PRAGMA user_version = 12")
    assert _unlinked_index_rows(database) == 1

    upgraded = _database(tmp_path)
    assert _unlinked_index_rows(upgraded) == 0
    upgraded.upsert_atoms([_atom("key", text="the key moved to the drawer")])
    with upgraded.connect() as connection:
        assert int(connection.execute("SELECT count(*) FROM atom_fts").fetchone()[0]) == 1, "a rewrite must replace its row, not add a second"
