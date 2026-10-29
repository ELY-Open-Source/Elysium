"""What a picture shows, written into its text, and what ingest does when no model answers.

The vision model is a served 9B, so these tests run the branches, not the weights: a stand-in
describer or a stand-in HTTP response answers, and the atom records whether its text came from
letters on the picture, from a model's sentences, or from nothing at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from PIL import Image

import elysium.describe as describe_module
import elysium.ingestion_media as media_module
from elysium.config import Settings
from elysium.db import Database
from elysium.describe import DEFERRED, VisionDescriber, describe_pictures
from elysium.ingestion import IngestionService
from elysium.ocr import OcrResult
from elysium.senses import sense_facts

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


def _ingest(
    tmp_path: Path, describer: object, monkeypatch: pytest.MonkeyPatch, ocr_text: str = ""
) -> tuple[Settings, Database]:
    settings = Settings(home=tmp_path / "home")
    database = Database(settings)
    service = IngestionService(settings=settings, database=database)
    service.describer = cast(VisionDescriber, describer)
    monkeypatch.setattr(media_module, "read_text_from_image", lambda path: OcrResult(ocr_text, 0.9, []))
    service.ingest_path(_picture(tmp_path))
    return settings, database


def test_a_wordless_picture_ingested_with_a_model_carries_the_description(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from elysium.storage import token_equivalent, visual_token_equivalent

    _, database = _ingest(tmp_path, FakeDescriber(), monkeypatch)

    atom = database.list_atoms()[0]
    assert atom.text == CAPTION
    assert atom.metadata["caption"] == "vlm"
    assert atom.trust.model == 0.6, "a sentence invented by a model is less trusted than printed letters"
    assert atom.token_equivalent == token_equivalent(CAPTION) + visual_token_equivalent(640, 360)


def test_a_picture_with_printed_words_is_described_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A screen's labels do not name its icons; the miss analysis found that is what screenshot questions ask."""
    describer = FakeDescriber()

    _, database = _ingest(tmp_path, describer, monkeypatch, ocr_text="Checkout")

    assert describer.calls == 1
    atom = database.list_atoms()[0]
    assert atom.text == f"Checkout\n{CAPTION}", "the printed words stay first and the description follows"
    assert atom.metadata["caption"] == "vlm"


def test_a_picture_without_a_model_says_so_in_the_atom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    describer = FakeDescriber(answer=None)

    _, database = _ingest(tmp_path, describer, monkeypatch, ocr_text="Checkout")

    atom = database.list_atoms()[0]
    assert atom.text == "Checkout"
    assert atom.metadata["caption"] == DEFERRED
    assert describer.calls == 1, "ingestion asks, and the answer is recorded as missing"


def test_a_model_that_fails_leaves_the_picture_ingestable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, database = _ingest(tmp_path, FakeDescriber(fails=True), monkeypatch)

    atom = database.list_atoms()[0]
    assert atom.text == ""
    assert atom.metadata["caption"].startswith("failed:"), "the atom says why it has no description"
    assert "ran out of memory" in atom.metadata["caption"]


def test_no_served_model_is_named_as_a_setup_step(tmp_path: Path) -> None:
    describer = VisionDescriber(Settings(home=tmp_path / "home"))

    assert not describer.available()
    with pytest.raises(SystemExit, match="ELYSIUM_VLM_BASE_URL"):
        describer.describe(_picture(tmp_path))


def test_the_request_carries_the_picture_and_turns_thinking_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: dict[str, Any] = {}

    def answer(url: str, json: dict[str, Any], timeout: object) -> httpx.Response:
        sent.update(url=url, body=json)
        return httpx.Response(200, json={"choices": [{"message": {"content": f"  {CAPTION}  "}}]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(describe_module.httpx, "post", answer)
    settings = Settings(home=tmp_path / "home", vlm_base_url="http://127.0.0.1:8001/v1")

    assert VisionDescriber(settings).describe(_picture(tmp_path)) == CAPTION
    assert sent["url"] == "http://127.0.0.1:8001/v1/chat/completions"
    assert sent["body"]["model"] == settings.model_id
    assert sent["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    parts = sent["body"]["messages"][0]["content"]
    assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_an_empty_answer_is_an_error_not_a_description(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def answer(url: str, json: dict[str, Any], timeout: object) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(describe_module.httpx, "post", answer)
    settings = Settings(home=tmp_path / "home", vlm_base_url="http://127.0.0.1:8001/v1")

    with pytest.raises(ValueError, match="answered with nothing"):
        VisionDescriber(settings).describe(_picture(tmp_path))


def test_a_store_described_later_matches_what_ingest_writes_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, database = _ingest(tmp_path, FakeDescriber(answer=None), monkeypatch, ocr_text="Checkout")
    described = settings.model_copy(update={"vlm_base_url": "http://127.0.0.1:8001/v1"})
    calls: list[Path] = []

    def describe(self: VisionDescriber, path: Path) -> str:
        calls.append(path)
        return CAPTION

    monkeypatch.setattr(VisionDescriber, "describe", describe)

    first = describe_pictures(described, database, workers=2)
    second = describe_pictures(described, database, workers=2)

    assert first == {"pending": 1, "described": 1}
    assert second == {"pending": 0, "described": 0}, "a described picture is not paid for twice"
    assert len(calls) == 1
    atom = database.list_atoms()[0]
    assert atom.text == f"Checkout\n{CAPTION}"
    assert atom.metadata["caption"] == "vlm"


def test_describing_with_nothing_served_stops_before_it_starts(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path / "home")

    with pytest.raises(SystemExit, match="nothing can describe the pictures"):
        describe_pictures(settings, Database(settings), workers=4)


def test_the_retired_snapshot_variable_names_its_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ELYSIUM_VLM_MODEL_DIR", "/models/qwen")

    with pytest.raises(SystemExit, match="ELYSIUM_VLM_BASE_URL"):
        Settings(home=tmp_path / "home")


def test_a_configured_model_that_does_not_answer_reads_missing(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path / "home", vlm_base_url="http://127.0.0.1:9/v1")

    status = sense_facts(settings, Database(settings))

    assert status.captioning == "missing"
    assert status.vlm_url == "http://127.0.0.1:9/v1"
