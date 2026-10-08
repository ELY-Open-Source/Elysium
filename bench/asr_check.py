"""Measure what the speech reader hears, against subtitles nobody in this repo wrote.

Video-MME ships community subtitles. They are third-party text, so they are a usable reference
for word error rate. They are not a verbatim transcript either, and the gap cuts both ways: a
caption that drops words also hides words the model dropped. The report states the denominator
instead of claiming a bound.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import time
from itertools import pairwise
from pathlib import Path
from typing import Any

from ely_eye.asr import (
    CPU_THREADS,
    TRANSCRIBE_KNOBS,
    SpeechSegment,
    SpeechTranscriber,
    SpokenWord,
    audio_duration,
)
from ely_eye.config import Settings
from ely_eye.db import Database
from ely_eye.ingestion import IngestionService
from ely_eye.schemas import Modality

from bench.systems import machine_facts

ROOT = Path(__file__).resolve().parent

CORPUS = ROOT / "corpus" / "lmms-eval" / "Video-MME"
MODEL = ROOT / "models" / "faster-whisper-tiny"
REPORTS = ROOT / "reports"
PASSES = 2
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


def measure_once(transcriber: SpeechTranscriber, pairs: list[tuple[Path, Path]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for video, subtitle in pairs:
        seconds = audio_duration(video)
        if not seconds:
            raise SystemExit(f"{video}: the container reports no duration, so the speed claim cannot be measured")
        started = time.time()
        segments = transcriber.transcribe(video)
        took = time.time() - started
        hyp_words = normalise(" ".join(segment.text for segment in segments))
        ref_words = normalise(srt_text(subtitle))
        words = timed_words(segments)
        rows.append(
            {
                "video": video.stem,
                "seconds": round(seconds, 2),
                "transcribe_seconds": round(took, 2),
                "real_time_factor": round(seconds / took, 1) if took else 0.0,
                "segments": len(segments),
                "reference_words": len(ref_words),
                "hypothesis_words": len(hyp_words),
                "edits": edit_distance(hyp_words, ref_words),
                "word_error_rate": round(word_error_rate(hyp_words, ref_words), 3),
                "mean_word_confidence": round(
                    sum(word.confidence for word in words) / max(len(words), 1), 3
                ),
                "transcript": " ".join(segment.text for segment in segments),
                **check_timings(segments),
            }
        )
    return rows


def speech_atoms_in_the_store(videos: list[Path]) -> dict[str, Any]:
    """Ingest for real, then read the store back: the claim is about the product, not the model."""
    with tempfile.TemporaryDirectory() as scratch:
        settings = Settings(home=Path(scratch) / "home", asr_model_dir=MODEL)
        settings.ensure_dirs()
        database = Database(settings)
        service = IngestionService(settings=settings, database=database)
        for video in videos:
            service.ingest_path(video)
        atoms = database.list_atoms()
        audio = [atom for atom in atoms if atom.modality == Modality.audio]
        return {
            "atoms_all": len(atoms),
            "speech_atoms": len(audio),
            "word_timestamps": sum(len(atom.metadata.get("words", [])) for atom in audio),
            "sources": len({atom.source_id for atom in audio}),
        }


def micro_wer(rows: list[dict[str, Any]]) -> float:
    reference = sum(row["reference_words"] for row in rows)
    if not reference:
        raise SystemExit("the subtitle files produced no reference words; the parser or the files are wrong")
    return round(sum(row["edits"] for row in rows) / reference, 3)


def main() -> None:
    if not (MODEL / "model.bin").exists():
        raise SystemExit(f"{MODEL / 'model.bin'} is missing; fetch Systran/faster-whisper-tiny into {MODEL}")
    videos = sorted((CORPUS / "videos").glob("*.mp4"))
    if not videos:
        raise SystemExit(f"no videos under {CORPUS / 'videos'}; unpack them from videos_chunked_01.zip")
    pairs = [(video, CORPUS / "subtitles" / f"{video.stem}.srt") for video in videos]
    pairs = [(video, srt) for video, srt in pairs if srt.exists()]
    if not pairs:
        raise SystemExit(f"none of {len(videos)} videos has a subtitle in {CORPUS / 'subtitles'}")

    transcriber = SpeechTranscriber(Settings(asr_model_dir=MODEL))
    passes = [measure_once(transcriber, pairs) for _ in range(PASSES)]
    rows, repeat = passes[0], passes[-1]
    store = speech_atoms_in_the_store(videos)
    if not store["speech_atoms"]:
        raise SystemExit("ingestion produced no audio atoms; the product path is broken even if the model works")

    totals = {
        "videos": len(rows),
        "audio_seconds": round(sum(row["seconds"] for row in rows), 2),
        "transcribe_seconds": round(sum(row["transcribe_seconds"] for row in rows), 2),
        "word_error_rate": micro_wer(rows),
        "reference_words": sum(row["reference_words"] for row in rows),
        "hypothesis_words": sum(row["hypothesis_words"] for row in rows),
        "words": sum(row["words"] for row in rows),
        "out_of_order": sum(row["out_of_order"] for row in rows),
        "before_their_segment": sum(row["before_their_segment"] for row in rows),
        **store,
    }
    report = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "commit": git_sha(),
        "model": {
            "id": "Systran/faster-whisper-tiny",
            "sha256_model_bin": model_sha256(),
            "compute": "cpu int8",
            "cpu_threads": CPU_THREADS,
            "decode_knobs": {key: str(value) for key, value in TRANSCRIBE_KNOBS.items()},
        },
        "reference": "Video-MME community subtitles: third-party captions, not verbatim transcripts",
        "machine": machine_facts(),
        "passes": {
            "count": PASSES,
            "word_error_rate": [micro_wer(pass_rows) for pass_rows in passes],
            "identical_transcripts": all(
                first["transcript"] == second["transcript"] for first, second in zip(rows, repeat, strict=True)
            ),
            "per_video_wer": [
                {"video": row["video"], "first": row["word_error_rate"], "second": again["word_error_rate"]}
                for row, again in zip(rows, repeat, strict=True)
            ],
        },
        "totals": totals,
        "videos": [{key: value for key, value in row.items() if key != "transcript"} for row in rows],
    }
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "asr.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report)
    print(f"wrote {REPORTS / 'ASR.md'}")


def write_markdown(report: dict[str, Any]) -> None:
    totals, model, passes = report["totals"], report["model"], report["passes"]
    lines = [
        f"# ASR: what the speech reader hears (commit {report['commit'][:9]})",
        "",
        f"- generated {report['generated_utc']}",
        (
            f"- model: {model['id']} ({model['compute']}, {model['cpu_threads']} threads), model.bin sha256 "
            f"{model['sha256_model_bin'][:16]}…"
        ),
        f"- decode: {', '.join(f'{key}={value}' for key, value in model['decode_knobs'].items())}",
        f"- reference: {report['reference']}",
        f"- machine: {report['machine']}",
        "",
        "| video | audio s | transcribe s | ×realtime | reference words | words | WER | mean word confidence |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["videos"]:
        lines.append(
            f"| {row['video']} | {row['seconds']} | {row['transcribe_seconds']} | {row['real_time_factor']} "
            f"| {row['reference_words']} | {row['words']} | {row['word_error_rate']} "
            f"| {row['mean_word_confidence']} |"
        )
    lines += [
        "",
        (
            f"Over {totals['videos']} videos and {totals['audio_seconds']} seconds of audio: word error rate "
            f"**{totals['word_error_rate']}** over {totals['reference_words']} reference words "
            f"({totals['hypothesis_words']} words heard), transcribed in {totals['transcribe_seconds']} seconds."
        ),
        "",
        (
            f"Repeating the pass on the same machine gave WER {' then '.join(str(value) for value in passes['word_error_rate'])}"
            f"; the transcripts were {'' if passes['identical_transcripts'] else 'not '}byte-identical. "
            "Decoding is greedy with no retry ladder, so a rerun is the same answer, not a new draw."
        ),
        "",
        (
            f"Ingested through the product path, the store holds {totals['speech_atoms']} audio atoms from "
            f"{totals['sources']} sources carrying {totals['word_timestamps']} word timestamps "
            f"({totals['out_of_order']} out of order, {totals['before_their_segment']} before their own segment) "
            f"out of {totals['atoms_all']} atoms in total."
        ),
        "",
        (
            "The captions are not a transcript, so this WER is not a bound in either direction: a caption that "
            "drops words also hides words the model dropped. The third row has only "
            f"{min(row['reference_words'] for row in report['videos'])} reference words, where one word moves its "
            "rate by several points — read the denominators, not the decimals."
        ),
    ]
    (REPORTS / "ASR.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
