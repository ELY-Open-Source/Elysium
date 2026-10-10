"""The video+audio harness must refuse to measure nothing, and must not touch frozen evidence."""

from pathlib import Path
from typing import Any

import pytest

from bench import video_audio_check


def test_a_frozen_report_is_not_overwritten_by_a_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reviewer runs harnesses in a worktree of its own; the committed evidence stays put."""
    monkeypatch.setattr(video_audio_check, "PAYLOAD", tmp_path / "video_audio.json")
    monkeypatch.setattr(video_audio_check, "_tracked", lambda path: True)
    frozen = tmp_path / "VIDEO_AUDIO.md"
    frozen.write_text("committed evidence", encoding="utf-8")
    with pytest.raises(SystemExit, match="is a frozen report"):
        video_audio_check.refuse_frozen_overwrite(frozen)
    elsewhere = tmp_path / "scratch" / "VIDEO_AUDIO.md"
    elsewhere.parent.mkdir()
    elsewhere.write_text("scratch", encoding="utf-8")
    video_audio_check.refuse_frozen_overwrite(elsewhere)


def test_a_harness_may_write_its_own_untracked_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default destination is the reports directory; refusing it would stop the shipped run."""
    monkeypatch.setattr(video_audio_check, "PAYLOAD", tmp_path / "video_audio.json")
    monkeypatch.setattr(video_audio_check, "_tracked", lambda path: False)
    fresh = tmp_path / "VIDEO_AUDIO.md"
    fresh.write_text("not yet evidence", encoding="utf-8")
    video_audio_check.refuse_frozen_overwrite(fresh)


def test_an_absolute_path_to_the_frozen_directory_is_refused_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard compares where the file really lands, not how the path was spelled."""
    monkeypatch.setattr(video_audio_check, "PAYLOAD", tmp_path / "video_audio.json")
    monkeypatch.setattr(video_audio_check, "_tracked", lambda path: True)
    frozen = tmp_path / "VIDEO_AUDIO.md"
    frozen.write_text("committed evidence", encoding="utf-8")
    with pytest.raises(SystemExit, match="is a frozen report"):
        video_audio_check.refuse_frozen_overwrite(Path(frozen.resolve()))


def test_the_probe_arm_switches_off_rather_than_ranking_nothing() -> None:
    """--probes 0 means "skip that arm"; a small count with the smoke knob means "you measured nothing"."""
    assert video_audio_check.probe_sample(0, 0) == []
    # The shipped sample keeps every modality; the smoke knob narrows it to video, where a
    # small count can miss the modality entirely (the reviewer's --limit 1 --probes 1 crash).
    assert any(query.modality == video_audio_check.VIDEO_MODALITY for query in video_audio_check.probe_sample(300, 0))
    for probes in (1, 5):
        with pytest.raises(SystemExit, match=f"--probes {probes} picked no answerable video query"):
            video_audio_check.probe_sample(probes, probes)


def test_an_empty_video_arm_is_a_lie_not_a_zero() -> None:
    """The video arm is the point of the harness; a row of zeros there must stop the run."""
    with pytest.raises(SystemExit, match="nothing to rank"):
        video_audio_check._required(None, "every video question")
    assert video_audio_check._score_of(None) == "skipped"


def test_a_missing_speech_snapshot_says_so_before_ranking(tmp_path: Path) -> None:
    """Without a snapshot every video defers, and the after row would equal the before row."""
    with pytest.raises(SystemExit, match="no speech snapshot"):
        video_audio_check.add_speech(tmp_path, [tmp_path / "a.mp4"], tmp_path / "no-snapshot", 0)


def test_a_store_without_video_sources_refuses(tmp_path: Path) -> None:
    """Speech has to join to a video source; a store with none would measure a new corpus."""
    import sqlite3

    videos = tmp_path / "videomme"
    videos.mkdir()
    (videos / "a.mp4").write_bytes(b"\x00")
    with pytest.raises(SystemExit, match="are not here"):
        video_audio_check.guard_videos(tmp_path / "nowhere", tmp_path)
    store = tmp_path / "store"
    (store / "data").mkdir(parents=True)
    connection = sqlite3.connect(store / "data" / "ely_eye.sqlite")
    connection.execute("CREATE TABLE sources (source_id text, kind text)")
    connection.commit()
    connection.close()
    with pytest.raises(SystemExit, match="holds no video sources"):
        video_audio_check.guard_videos(videos, store)


def test_every_measured_video_query_carries_gold() -> None:
    """An answerable-only set: a query with no gold would score 0 against nothing."""
    queries: list[Any] = video_audio_check.video_queries()
    assert queries, "the frozen suite must carry answerable video queries"
    assert all(query.modality == video_audio_check.VIDEO_MODALITY for query in queries)
    assert all(query.gold for query in queries)
