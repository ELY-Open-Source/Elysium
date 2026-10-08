"""Measure what the speech reader hears, against subtitles nobody in this repo wrote.

Video-MME ships community subtitles for its videos. They are third-party text, so they are a
fair reference for word error rate, with one caveat the report states: a caption track is not
a verbatim transcript, so the number is an upper bound on the model's real error rate.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from itertools import pairwise
from pathlib import Path
from typing import Any

from ely_eye.asr import SpeechSegment, SpeechTranscriber, SpokenWord
from ely_eye.config import Settings
from ely_eye.schemas import Modality

from bench.systems import machine_facts

ROOT = Path(__file__).resolve().parent

CORPUS = ROOT / "corpus" / "lmms-eval" / "Video-MME"
MODEL = ROOT / "models" / "faster-whisper-tiny"
REPORTS = ROOT / "reports"
PUNCTUATION = re.compile(r"[^\w' ]+")
TAGS = re.compile(r"<[^>]+>")
INDEX_LINE = re.compile(r"^\d+$")
TIMING_LINE = re.compile(r"-->")


def normalise(text: str) -> list[str]:
    cleaned = PUNCTUATION.sub(" ", text.lower())
    return [word for word in cleaned.split() if word]


def edit_distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for index, first in enumerate(left, start=1):
        current = [index]
        for column, second in enumerate(right, start=1):
            cost = 0 if first == second else 1
            current.append(min(previous[column] + 1, current[column - 1] + 1, previous[column - 1] + cost))
        previous = current
    return previous[-1]


def word_error_rate(hypothesis: list[str], reference: list[str]) -> float:
    if not reference:
        return 1.0
    return edit_distance(hypothesis, reference) / len(reference)


def srt_text(path: Path) -> str:
    lines = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or INDEX_LINE.match(stripped) or TIMING_LINE.search(stripped):
            continue
        lines.append(TAGS.sub(" ", stripped))
    return " ".join(lines)


def model_sha256() -> str:
    digest = hashlib.sha256()
    with (MODEL / "model.bin").open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_sha() -> str:
    done = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT.parent, capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def timed_words(segments: list[SpeechSegment]) -> list[SpokenWord]:
    return [word for segment in segments for word in segment.words if word.word]


def check_timings(segments: list[SpeechSegment]) -> dict[str, Any]:
    """Word clocks must run forward and stay inside their segment."""
    words = timed_words(segments)
    out_of_order = sum(1 for before, after in pairwise(words) if after.start < before.start)
    outside = sum(1 for segment in segments for word in segment.words if word.start < segment.start - 0.01)
    return {"words": len(words), "out_of_order": out_of_order, "before_their_segment": outside}


def main() -> None:
    if not (MODEL / "model.bin").exists():
        raise SystemExit(f"{MODEL / 'model.bin'} is missing; fetch Systran/faster-whisper-tiny into {MODEL}")
    videos = sorted((CORPUS / "videos").glob("*.mp4"))
    if not videos:
        raise SystemExit(f"no videos under {CORPUS / 'videos'}; unpack them from videos_chunked_01.zip")

    transcriber = SpeechTranscriber(Settings(asr_model_dir=MODEL))
    rows: list[dict[str, Any]] = []
    for video in videos:
        subtitle = CORPUS / "subtitles" / f"{video.stem}.srt"
        if not subtitle.exists():
            continue
        started = time.time()
        segments = transcriber.transcribe(video)
        took = time.time() - started
        hypothesis = " ".join(segment.text for segment in segments)
        reference = srt_text(subtitle)
        hyp_words, ref_words = normalise(hypothesis), normalise(reference)
        audio_seconds = max((segment.end for segment in segments), default=0.0)
        rows.append(
            {
                "video": video.stem,
                "seconds": round(audio_seconds, 1),
                "transcribe_seconds": round(took, 2),
                "real_time_factor": round(audio_seconds / took, 1) if took else 0.0,
                "segments": len(segments),
                "speech_atoms": sum(1 for segment in segments if segment.text),
                "modality": Modality.audio.value,
                "hypothesis_words": len(hyp_words),
                "reference_words": len(ref_words),
                "word_error_rate": round(word_error_rate(hyp_words, ref_words), 3),
                "mean_word_confidence": round(
                    sum(word.confidence for word in timed_words(segments)) / max(len(timed_words(segments)), 1), 3
                ),
                **check_timings(segments),
            }
        )
    if not rows:
        raise SystemExit(f"none of {len(videos)} videos has a subtitle in {CORPUS / 'subtitles'}")
    reference_words = sum(row["reference_words"] for row in rows)
    if not reference_words:
        raise SystemExit("the subtitle files produced no reference words; the parser or the files are wrong")

    totals = {
        "videos": len(rows),
        "audio_seconds": round(sum(row["seconds"] for row in rows), 1),
        "word_error_rate": round(
            sum(row["word_error_rate"] * row["reference_words"] for row in rows) / reference_words,
            3,
        ),
        "speech_atoms": sum(row["speech_atoms"] for row in rows),
        "words": sum(row["words"] for row in rows),
        "out_of_order": sum(row["out_of_order"] for row in rows),
        "before_their_segment": sum(row["before_their_segment"] for row in rows),
    }
    report = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "commit": git_sha(),
        "model": {"id": "Systran/faster-whisper-tiny", "sha256_model_bin": model_sha256(), "compute": "cpu int8"},
        "reference": "Video-MME community subtitles (third-party captions, not verbatim transcripts)",
        "machine": machine_facts(),
        "totals": totals,
        "videos": rows,
    }
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "asr.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report)
    print(f"wrote {REPORTS / 'ASR.md'}")


def write_markdown(report: dict[str, Any]) -> None:
    totals, model = report["totals"], report["model"]
    lines = [
        f"# ASR: what the speech reader hears (commit {report['commit'][:9]})",
        "",
        f"- generated {report['generated_utc']}",
        f"- model: {model['id']} ({model['compute']}), model.bin sha256 {model['sha256_model_bin'][:16]}…",
        f"- reference: {report['reference']}",
        f"- machine: {report['machine']}",
        "",
        "| video | audio s | transcribe s | ×realtime | speech atoms | words | WER | mean word confidence |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["videos"]:
        lines.append(
            f"| {row['video']} | {row['seconds']} | {row['transcribe_seconds']} | {row['real_time_factor']} "
            f"| {row['speech_atoms']} | {row['words']} | {row['word_error_rate']} | {row['mean_word_confidence']} |"
        )
    lines += [
        "",
        (
            f"Over {totals['videos']} videos and {totals['audio_seconds']} seconds of audio: word error rate "
            f"**{totals['word_error_rate']}** against captions nobody here wrote, {totals['speech_atoms']} speech "
            f"atoms carrying {totals['words']} word-level timestamps, {totals['out_of_order']} words out of order "
            f"and {totals['before_their_segment']} starting before their own segment."
        ),
        "",
        (
            "A caption track drops words a transcript keeps, so this WER is an upper bound on the model's real "
            "error. The point of the run is not the number: before this change an audio file produced no memory "
            "at all, and every word here now has an instant attached to it."
        ),
    ]
    (REPORTS / "ASR.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
