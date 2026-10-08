"""A picture with no words on it, and what the ingest path does about it.

The vision model is a multi-gigabyte download, so these tests run the branch, not the weights:
a stand-in describer answers, and the atom records whether its text came from letters on the
picture, from a model's sentence, or from nothing at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from PIL import Image

import ely_eye.ingestion_media as media_module
from ely_eye.config import Settings
from ely_eye.db import Database
from ely_eye.describe import DEFERRED, VisionDescriber
from ely_eye.ingestion import IngestionService
from ely_eye.ocr import OcrResult

CAPTION = "一个购物车图标停在结算按钮旁边"


class FakeDescriber:
    """Stands in for the vision model and counts how often ingestion asked."""

    def __init__(self, answer: str | None = CAPTION, fails: bool = False) -> None:
        self.answer = answer
        self.fails = fails
        self.calls = 0

    def describe_or_none(self, path: Path) -> str | None:
        self.calls += 1
        if self.fails:
            raise RuntimeError("the vision model ran out of memory")
        return self.answer


def _picture(tmp_path: Path) -> Path:
    path = tmp_path / "scene.png"
    Image.new("RGB", (640, 360), (12, 34, 56)).save(path)
    return path


def _ingest(tmp_path: Path, describer: object, ocr_text: str = "") -> tuple[Settings, Database]:
    settings = Settings(home=tmp_path / "home")
    database = Database(settings)
    service = IngestionService(settings=settings, database=database)
    service.describer = cast(VisionDescriber, describer)
    media_module.read_text_from_image = lambda path: OcrResult(ocr_text, 0.9, [])
    service.ingest_path(_picture(tmp_path))
    return settings, database


def test_a_wordless_picture_ingested_with_a_model_carries_the_caption(tmp_path: Path) -> None:
    from ely_eye.storage import token_equivalent, visual_token_equivalent

    _, database = _ingest(tmp_path, FakeDescriber())

    atom = database.list_atoms()[0]
    assert atom.text == CAPTION
    assert atom.metadata["caption"] == "vlm"
    assert atom.trust.model == 0.6, "a sentence invented by a model is less trusted than printed letters"
    assert atom.token_equivalent == token_equivalent(CAPTION) + visual_token_equivalent(640, 360)


def test_a_wordless_picture_without_a_model_says_so_in_the_atom(tmp_path: Path) -> None:
    describer = FakeDescriber(answer=None)

    _, database = _ingest(tmp_path, describer)

    atom = database.list_atoms()[0]
    assert atom.text == ""
    assert atom.metadata["caption"] == DEFERRED
    assert describer.calls == 1, "ingestion asks, and the answer is recorded as missing"


def test_a_picture_with_printed_words_never_costs_a_model_call(tmp_path: Path) -> None:
    describer = FakeDescriber()

    _, database = _ingest(tmp_path, describer, ocr_text="Checkout")

    assert describer.calls == 0, "letters already on the picture are free"
    atom = database.list_atoms()[0]
    assert atom.text == "Checkout"
    assert atom.metadata["caption"] == ""


def test_a_model_that_fails_leaves_the_picture_ingestable(tmp_path: Path) -> None:
    describer = FakeDescriber(fails=True)

    _, database = _ingest(tmp_path, describer)

    atom = database.list_atoms()[0]
    assert atom.text == ""
    assert atom.metadata["caption"].startswith("failed:"), "the atom says why its text is empty"
    assert "ran out of memory" in atom.metadata["caption"]


def test_a_missing_snapshot_is_named_as_a_setup_step(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path / "home", vlm_model_dir=tmp_path / "nowhere")
    describer = VisionDescriber(settings)

    assert not describer.available()
    with pytest.raises(SystemExit, match="ELY_EYE_VLM_MODEL_DIR"):
        describer.describe(_picture(tmp_path))
