"""A figure goes back to the words it had before any description, and only from the store it came from."""

import sqlite3
from pathlib import Path

import pytest
from elysium.config import Settings
from elysium.db import Database
from elysium.describe import with_description
from elysium.memory import MemoryService
from elysium.schemas import EvidenceAtom, MemoryOrigin, Modality

from bench import redescribe_check


def _store(home: Path, modality: Modality) -> tuple[Database, EvidenceAtom]:
    settings = Settings(home=home)
    database = Database(settings)
    written = MemoryService(settings, database).remember("revenue by quarter", holder_id="analyst", origin=MemoryOrigin.self_)
    (atom,) = database.get_atoms([written.atom_id])
    picture = atom.model_copy(update={"modality": modality, "image_ref": "images/chart.png"})
    database.upsert_atoms([picture])
    return database, picture


def test_a_figure_takes_back_its_undescribed_words(tmp_path: Path) -> None:
    _, plain = _store(tmp_path / "before", Modality.image)
    after, _ = _store(tmp_path / "after", Modality.image)
    after.upsert_atoms([with_description(plain, "a bar chart, blue bars rising")])

    assert redescribe_check.undescribe(tmp_path / "after", tmp_path / "before") == 1

    (restored,) = after.get_atoms([plain.atom_id])
    assert restored.text == plain.text
    assert "caption" not in restored.metadata, "a restored figure must be pending again, or the backfill skips it"


def test_a_video_frame_keeps_its_description(tmp_path: Path) -> None:
    _store(tmp_path / "before", Modality.video_frame)
    after, frame = _store(tmp_path / "after", Modality.video_frame)
    after.upsert_atoms([with_description(frame, "four performers on a stage")])

    assert redescribe_check.undescribe(tmp_path / "after", tmp_path / "before") == 0
    assert "four performers" in after.get_atoms([frame.atom_id])[0].text


def test_an_undescribed_store_that_lacks_the_figure_is_refused(tmp_path: Path) -> None:
    _store(tmp_path / "after", Modality.image)
    Database(Settings(home=tmp_path / "other"))

    with pytest.raises(SystemExit, match="not the store DESCRIBE started from"):
        redescribe_check.undescribe(tmp_path / "after", tmp_path / "other")


def test_the_undescribed_store_is_read_without_being_migrated(tmp_path: Path) -> None:
    _, plain = _store(tmp_path / "before", Modality.image)
    after, _ = _store(tmp_path / "after", Modality.image)
    after.upsert_atoms([with_description(plain, "a bar chart, blue bars rising")])
    source = tmp_path / "before" / "data" / "elysium.sqlite"
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA user_version = 12")

    assert redescribe_check.undescribe(tmp_path / "after", tmp_path / "before") == 1
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 12, "the source store must not be migrated in place"
