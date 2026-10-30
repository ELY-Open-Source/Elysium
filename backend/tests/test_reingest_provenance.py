"""Reading a file again must not hand it to the public.

Ingest stamps no holder, so the upsert used to write every re-read atom back as nobody's, and
nobody's memory answers every caller. Measured on the video corpus: re-ingesting 129 videos to
add speech left 26,413 frames and 28,363 transcript lines with an empty holder, and every
code, PDF and screenshot question then ranked against them.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from elysian.config import Settings
from elysian.db import Database
from elysian.ingestion import IngestionService
from elysian.retrieval import RetrievalService
from elysian.schemas import SearchFilters


def _service(tmp_path: Path) -> tuple[IngestionService, Settings]:
    settings = Settings(home=tmp_path / "home")
    return IngestionService(settings), settings


def _own(settings: Settings, holder: str) -> None:
    """Stamp every atom the way the corpus stamper does: a direct write of who holds it."""
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute(
            "UPDATE atoms SET holder_id = ?, scenario = 'home', event_time = '2026-09-30T00:00:00+00:00'",
            (holder,),
        )


def _note(tmp_path: Path, text: str) -> Path:
    note = tmp_path / "keys.md"
    note.write_text(text, encoding="utf-8")
    return note


def _holders(settings: Settings) -> set[tuple[str, str, str]]:
    with sqlite3.connect(settings.db_path) as connection:
        return {tuple(row) for row in connection.execute("SELECT holder_id, scenario, event_time FROM atoms")}


def test_a_second_read_keeps_the_holder_the_store_recorded(tmp_path: Path) -> None:
    service, settings = _service(tmp_path)
    note = _note(tmp_path, "the spare keys are in the glovebox")
    service.ingest_path(note)
    _own(settings, "wife")

    service.ingest_path(note)

    assert _holders(settings) == {("wife", "home", "2026-09-30T00:00:00+00:00")}


def test_a_reread_private_file_stays_out_of_another_holder_s_search(tmp_path: Path) -> None:
    service, settings = _service(tmp_path)
    note = _note(tmp_path, "the spare keys are in the glovebox")
    service.ingest_path(note)
    _own(settings, "wife")
    service.ingest_path(note)
    search = RetrievalService(settings=settings, database=Database(settings))

    assert search.search("glovebox", filters=SearchFilters(as_holder="wife")).hits
    assert search.search("glovebox", filters=SearchFilters(as_holder="neighbour")).status == "no_match"


def test_a_source_whose_atoms_disagree_about_their_holder_is_refused(tmp_path: Path) -> None:
    service, settings = _service(tmp_path)
    note = _note(tmp_path, "the spare keys are in the glovebox")
    service.ingest_path(note)
    database = Database(settings)
    (stored,) = database.list_atoms()
    database.upsert_atoms([stored.model_copy(update={"atom_id": f"{stored.atom_id}:2", "holder_id": "wife"})])

    with pytest.raises(ValueError, match="disagree about who holds them"):
        service.ingest_path(note)


def test_two_rows_that_only_join_to_the_same_string_still_disagree(tmp_path: Path) -> None:
    """("alice", "team\x1fhome") and ("alice\x1fteam", "home") once compared equal and the source was handed to alice."""
    service, settings = _service(tmp_path)
    note = _note(tmp_path, "the spare keys are in the glovebox")
    service.ingest_path(note)
    database = Database(settings)
    (stored,) = database.list_atoms()
    database.upsert_atoms(
        [
            stored.model_copy(update={"holder_id": "alice", "scenario": "team\x1fhome"}),
            stored.model_copy(update={"atom_id": f"{stored.atom_id}:2", "holder_id": "alice\x1fteam", "scenario": "home"}),
        ]
    )

    with pytest.raises(ValueError, match="disagree about who holds them"):
        service.ingest_path(note)


def test_a_time_on_one_atom_and_none_on_another_is_a_disagreement(tmp_path: Path) -> None:
    service, settings = _service(tmp_path)
    note = _note(tmp_path, "the spare keys are in the glovebox")
    service.ingest_path(note)
    _own(settings, "wife")
    database = Database(settings)
    (stored,) = database.list_atoms()
    database.upsert_atoms([stored.model_copy(update={"atom_id": f"{stored.atom_id}:2", "event_time": None})])

    with pytest.raises(ValueError, match="disagree about who holds them"):
        service.ingest_path(note)


def test_a_new_file_is_still_nobody_s_until_someone_claims_it(tmp_path: Path) -> None:
    service, settings = _service(tmp_path)
    service.ingest_path(_note(tmp_path, "the spare keys are in the glovebox"))

    assert {holder for holder, _, _ in _holders(settings)} == {""}
