"""Speech to text with word-level timings, so a spoken memory can be found and pointed at."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .config import Settings, get_settings

DOWNLOAD_HINT = (
    "fetch a faster-whisper CTranslate2 snapshot and set ELY_EYE_ASR_MODEL_DIR "
    "to the directory holding it"
)
DEFERRED = "deferred: no speech model snapshot"
MODEL_GRAPH = "model.bin"
SAMPLE_RATE = 16_000
CPU_THREADS = 4
TRANSCRIBE_KNOBS: dict[str, Any] = {
    "word_timestamps": True,
    "beam_size": 1,
    "temperature": (0.0,),
    "condition_on_previous_text": False,
    "vad_filter": False,
}


@dataclass(frozen=True)
class SpokenWord:
    word: str
    start: float
    end: float
    confidence: float


@dataclass(frozen=True)
class SpeechSegment:
    text: str
    start: float
    end: float
    words: tuple[SpokenWord, ...]
    confidence: float


def decode_audio(path: Path) -> np.ndarray:
    """Decode any container PyAV reads into mono 16 kHz floats, the shape the model wants.

    The decode lives here rather than inside faster-whisper because its own decoder calls
    av.open(metadata_errors=...), a keyword PyAV 19 no longer accepts. PyAV 19 raises its
    failures as OSError and ValueError subclasses, so FFmpegError is the only thing caught
    here and a caller's own error keeps its own message.
    """
    import av
    from av.error import FFmpegError

    frames: list[np.ndarray] = []
    try:
        with av.open(str(path)) as container:
            audio_streams = container.streams.audio
            if not audio_streams:
                raise ValueError(f"{path}: the file holds no audio track")
            resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
            for chunk in container.decode(audio_streams[0]):
                if not isinstance(chunk, av.AudioFrame):
                    continue
                for resampled in resampler.resample(chunk):
                    frames.append(np.asarray(resampled.to_ndarray()).reshape(-1))
    except FFmpegError as error:
        raise ValueError(f"{path}: the audio cannot be decoded ({error})") from error
    if not frames:
        raise ValueError(f"{path}: the audio track is empty")
    return np.concatenate(frames).astype(np.float32)


def audio_duration(path: Path) -> float:
    """Seconds of media the container claims; 0.0 when it does not say."""
    import av
    from av.error import FFmpegError

    try:
        with av.open(str(path)) as container:
            if not container.duration:
                return 0.0
            return container.duration / av.time_base
    except FFmpegError as error:
        raise ValueError(f"{path}: the container cannot be read ({error})") from error


def _confidence(words: list[Any]) -> float:
    scores = [float(word.probability) for word in words if getattr(word, "probability", None) is not None]
    if not scores:
        return 0.0
    return min(sum(scores) / len(scores), 1.0)


def _segment(segment: Any) -> SpeechSegment:
    words = list(getattr(segment, "words", None) or [])
    return SpeechSegment(
        text=segment.text.strip(),
        start=float(segment.start),
        end=float(segment.end),
        words=tuple(
            SpokenWord(
                word=spoken.word.strip(),
                start=float(spoken.start),
                end=float(spoken.end),
                confidence=float(getattr(spoken, "probability", 0.0) or 0.0),
            )
            for spoken in words
        ),
        confidence=_confidence(words),
    )


class SpeechTranscriber:
    """Whisper on CTranslate2: 88.9 seconds of speech in 1.7 seconds of CPU int8 (bench/reports/ASR.md)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._model: Any = None

    def model_dir(self) -> Path | None:
        return self.settings.asr_model_dir

    def available(self) -> bool:
        directory = self.model_dir()
        return directory is not None and (directory / MODEL_GRAPH).exists()

    def transcribe(self, path: Path) -> list[SpeechSegment]:
        """Words with the instant each was spoken; the timings are the point of the feature."""
        directory = self.model_dir()
        if directory is None:
            raise SystemExit(f"no speech model snapshot is configured; {DOWNLOAD_HINT}")
        if not (directory / MODEL_GRAPH).exists():
            raise SystemExit(f"{directory} holds no {MODEL_GRAPH}; {DOWNLOAD_HINT}")
        model = self._load(directory)
        # Greedy, no retry ladder, no carry-over: the same file must answer the same way twice.
        segments, _info = model.transcribe(decode_audio(path), **TRANSCRIBE_KNOBS)
        return [_segment(segment) for segment in segments]

    def _load(self, directory: Path) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                str(directory), device="cpu", compute_type="int8", cpu_threads=CPU_THREADS
            )
        return self._model
