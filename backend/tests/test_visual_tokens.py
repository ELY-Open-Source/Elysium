"""What a picture costs the model that reads it.

The first version divided pixels by 224x224, which priced a 1280x720 frame at 18 tokens —
less than its caption. A vision model spends one token per patch, and Qwen3-VL's patch is
32x32, so the same frame is 920. A context budget built on the old number holds six times
less picture than it claims.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

import elysian.ingestion_media as media_module
from elysian.config import Settings
from elysian.db import Database
from elysian.ingestion import IngestionService
from elysian.migrations import SCHEMA_VERSION, apply
from elysian.ocr import OcrResult
from elysian.storage import token_equivalent, visual_token_equivalent

FRAME = (1280, 720)


def _ingest(tmp_path: Path, settings: Settings) -> Database:
    """Run the real ingest path; each caller decides what its OCR says."""
    database = Database(settings)
    Image.new("RGB", FRAME, (10, 20, 30)).save(tmp_path / "frame.png")
    IngestionService(settings=settings, database=database).ingest_path(tmp_path / "frame.png")
    return database


def test_a_frame_is_priced_by_the_patches_a_vision_model_sees() -> None:
    assert visual_token_equivalent(1280, 720) == 920


def test_a_small_tile_still_costs_more_than_a_single_token() -> None:
    assert visual_token_equivalent(224, 224) == 49


def test_a_region_without_a_size_is_refused_rather_than_guessed() -> None:
    for width, height in ((0, 720), (1280, -1)):
        with pytest.raises(ValueError, match="needs a positive size"):
            visual_token_equivalent(width, height)


def test_an_ingested_image_carries_its_text_and_its_patches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(home=tmp_path)
    monkeypatch.setattr(media_module, "read_text_from_image", lambda path: OcrResult("购物车", 0.9, []))

    database = _ingest(tmp_path, settings)
    atom = database.list_atoms()[0]

    assert atom.token_equivalent == token_equivalent("购物车") + 920


def test_an_existing_store_is_repriced_by_the_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(home=tmp_path)
    monkeypatch.setattr(media_module, "read_text_from_image", lambda path: OcrResult("", 0.0, []))
    database = _ingest(tmp_path, settings)
    note = tmp_path / "notes.md"
    note.write_text("# 钥匙放在玄关抽屉里\n", encoding="utf-8")
    IngestionService(settings=settings, database=database).ingest_path(note)
    with database.connect() as connection:
        connection.execute("UPDATE atoms SET token_equivalent = 18 WHERE modality = 'image'")
        connection.execute("PRAGMA user_version = 6")

    with database.connect() as connection:
        apply(connection)

    atoms = {atom.modality.value: atom for atom in database.list_atoms()}
    assert atoms["image"].token_equivalent == 920, "the old 224x224 price must not survive the upgrade"
    assert atoms["text"].token_equivalent == token_equivalent(note.read_text(encoding="utf-8"))
    with database.connect() as connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION


def test_an_atom_without_a_layout_size_keeps_the_number_it_has(tmp_path: Path) -> None:
    """Nothing can be priced from a missing region, so the stored figure is left alone."""
    settings = Settings(home=tmp_path)
    database = Database(settings)
    with database.connect() as connection:
        apply(connection)
        connection.execute("PRAGMA user_version = 6")
        connection.execute(
            "INSERT INTO sources (source_id, path, kind, mime, sha256, size_bytes, created_at, metadata_json)"
            " VALUES ('s', '/tmp/x.png', 'image', 'image/png', 'h', 1, '2026-01-01T00:00:00+00:00', '{}')"
        )
        connection.execute(
            "INSERT INTO atoms (atom_id, source_id, modality, source, ingested_at, text, embedding_refs_json,"
            " layout_json, relations_json, trust_json, metadata_json, token_equivalent, origin)"
            " VALUES ('a1', 's', 'image', '/tmp/x.png', '2026-01-01T00:00:00+00:00', 'x', '[]', '{}', '[]', '{}', '{}', 18, 'artifact')"
        )

    with database.connect() as connection:
        apply(connection)
        assert int(connection.execute("SELECT token_equivalent FROM atoms WHERE atom_id = 'a1'").fetchone()[0]) == 18
