"""Speech memories: what a recording becomes, and what happens when no model is configured."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from ely_eye import ingestion_media as media_module
from ely_eye.asr import DEFERRED, SpeechSegment, SpeechTranscriber, SpokenWord, decode_audio
from ely_eye.config import Settings
from ely_eye.db import Database
from ely_eye.ingestion import IngestionService, UnsupportedFile
from ely_eye.ocr import OcrResult
from ely_eye.schemas import Modality

WORDS = (
    SpokenWord(word="钥匙", start=0.58, end=0.9, confidence=0.91),
    SpokenWord(word="抽屉", start=1.02, end=1.4, confidence=0.77),
)
SEGMENTS = (
    SpeechSegment(text="钥匙在抽屉里", start=0.58, end=1.4, words=WORDS, confidence=0.84),
    SpeechSegment(text="", start=9.0, end=9.5, words=(), confidence=0.0),
)


class FakeTranscriber:
    """Stands in for whisper so the test asserts the shape we build from its answer."""

    def __init__(
        self,
        segments: tuple[SpeechSegment, ...] = SEGMENTS,
        available: bool = True,
        error: Exception | None = None,
    ) -> None:
        self.segments = segments
        self._available = available
        self.error = error
        self.calls: list[Path] = []

    def available(self) -> bool:
        return self._available

    def transcribe(self, path: Path) -> list[SpeechSegment]:
        self.calls.append(path)
        if self.error is not None:
            raise self.error
        return list(self.segments)


class FakeEncoded:
    def tobytes(self) -> bytes:
        return b"png-bytes"


class FakeCapture:
    """One frame, two frames of metadata: enough for the video reader to reach the speech step."""

    def __init__(self, _path: str) -> None:
        self.released = False

    def isOpened(self) -> bool:
        return True

    def get(self, property_id: int) -> float:
        return 1.0 if property_id == media_module.cv2.CAP_PROP_FPS else 2.0

    def set(self, _property_id: int, _value: float) -> None:
        return None

    def read(self) -> tuple[bool, Any]:
        return True, np.zeros((4, 4, 3), dtype=np.uint8)

    def release(self) -> None:
        self.released = True


class FakeCv2:
    CAP_PROP_FPS = 5
    CAP_PROP_FRAME_COUNT = 7
    CAP_PROP_POS_FRAMES = 1

    VideoCapture = FakeCapture

    @staticmethod
    def imencode(_suffix: str, _frame: Any) -> tuple[bool, FakeEncoded]:
        return True, FakeEncoded()


def _settings(tmp_path: Path, asr_model_dir: Path | None = None) -> Settings:
    return Settings(home=tmp_path / "home", asr_model_dir=asr_model_dir)


def _service(tmp_path: Path, transcriber: Any) -> tuple[IngestionService, Database]:
    settings = _settings(tmp_path)
    settings.ensure_dirs()
    database = Database(settings)
    service = IngestionService(settings=settings, database=database)
    service.transcriber = cast(SpeechTranscriber, transcriber)
    return service, database


def _audio(tmp_path: Path, name: str = "keynote.mp3") -> Path:
    path = tmp_path / name
    path.write_bytes(b"not really mp3")
    return path


def test_a_recording_becomes_memories_pointed_at_the_instant_each_word_was_said(
    tmp_path: Path,
) -> None:
    service, database = _service(tmp_path, FakeTranscriber())

    response = service.ingest_path(_audio(tmp_path))

    assert response.atom_count == 1, "the empty segment must not become a memory"
    atom = database.list_atoms()[0]
    assert atom.modality is Modality.audio
    assert atom.text == "钥匙在抽屉里"
    assert atom.source.endswith("#t=0.580")
    assert atom.atom_id.endswith(":speech:0000000580")
    assert atom.layout is not None and atom.layout.frame_second == pytest.approx(0.58)
    assert atom.metadata["start_seconds"] == pytest.approx(0.58)
    assert atom.metadata["end_seconds"] == pytest.approx(1.4)
    assert [(word["word"], word["start"]) for word in atom.metadata["words"]] == [("钥匙", 0.58), ("抽屉", 1.02)]
    assert atom.trust.model == pytest.approx(0.84), "the model's own confidence is the trust it earned"


def test_a_recording_without_a_model_is_recorded_and_says_why(tmp_path: Path) -> None:
    service, database = _service(tmp_path, FakeTranscriber(available=False))

    response = service.ingest_path(_audio(tmp_path))

    assert response.source_count == 1, "the file is known even when nothing was heard"
    assert response.atom_count == 0
    assert database.list_sources()[0].metadata["speech"] == DEFERRED
    assert response.skipped == [], "a file we have a reader for is not a skipped file"


def test_a_broken_model_leaves_a_note_instead_of_a_corpse(tmp_path: Path) -> None:
    service, _database = _service(tmp_path, FakeTranscriber(error=ValueError("ctranslate2 is gone")))

    response = service.ingest_path(_audio(tmp_path))

    assert response.source_count == 1
    assert response.atom_count == 0
    assert response.sources[0].metadata["speech"] == "failed: ctranslate2 is gone"


def test_a_video_learns_what_was_said_in_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, database = _service(tmp_path, FakeTranscriber())
    monkeypatch.setattr(media_module, "cv2", FakeCv2())
    monkeypatch.setattr(media_module, "read_text_from_image", lambda path: OcrResult("", 0.0, []))
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"not really mp4")

    service.ingest_path(video)

    modalities = {atom.modality for atom in database.list_atoms()}
    assert Modality.video_frame in modalities
    assert Modality.audio in modalities, "a silent OCR of frames misses everything that was spoken"
    assert database.list_sources()[0].metadata["speech"] == "1 segments of speech"


def test_a_file_we_cannot_read_fails_when_it_was_named_explicitly(tmp_path: Path) -> None:
    service, _database = _service(tmp_path, FakeTranscriber(available=False))
    mystery = tmp_path / "mystery.xyz"
    mystery.write_text("nope", encoding="utf-8")

    with pytest.raises(UnsupportedFile, match="no reader for .xyz"):
        service.ingest_path(mystery)


def test_a_walk_records_what_it_refused_to_read(tmp_path: Path) -> None:
    service, database = _service(tmp_path, FakeTranscriber(available=False))
    folder = tmp_path / "shelf"
    folder.mkdir()
    (folder / "note.md").write_text("# 钥匙放在抽屉里\n", encoding="utf-8")
    (folder / "mystery.bin").write_bytes(b"\x00\x01")

    response = service.ingest_path(folder)

    assert response.atom_count > 0, "the readable file is still ingested"
    assert [item.path for item in response.skipped] == [str(folder / "mystery.bin")]
    assert "no reader for .bin" in response.skipped[0].reason
    assert database.atom_count() == response.atom_count


def test_the_transcriber_names_the_snapshot_it_wants(tmp_path: Path) -> None:
    without = SpeechTranscriber(_settings(tmp_path))
    assert not without.available()
    with pytest.raises(SystemExit, match="ELY_EYE_ASR_MODEL_DIR"):
        without.transcribe(_audio(tmp_path))

    empty = tmp_path / "snapshot"
    empty.mkdir()
    half = SpeechTranscriber(_settings(tmp_path, asr_model_dir=empty))
    assert not half.available()
    with pytest.raises(SystemExit, match="holds no model.bin"):
        half.transcribe(_audio(tmp_path))


def test_a_file_with_no_audio_track_says_so(tmp_path: Path) -> None:
    markdown = tmp_path / "notes.md"
    markdown.write_text("# 钥匙\n", encoding="utf-8")

    with pytest.raises(ValueError, match="the audio cannot be decoded"):
        decode_audio(markdown)
