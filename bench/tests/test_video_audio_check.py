"""The video+audio harness must refuse to measure nothing, and must not touch frozen evidence."""

from pathlib import Path
from typing import Any

import pytest

from bench import video_audio_check


def test_a_frozen_report_is_not_overwritten_by_a_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reviewer runs harnesses in a worktree of its own; the committed evidence stays put, in any directory."""
    monkeypatch.setattr(video_audio_check, "_tracked", lambda path: True)
    frozen = tmp_path / "VIDEO_AUDIO.md"
    frozen.write_text("committed evidence", encoding="utf-8")
    with pytest.raises(SystemExit, match="is a frozen report"):
        video_audio_check.refuse_frozen_overwrite(frozen)
    elsewhere = tmp_path / "scratch" / "VIDEO_AUDIO.md"
    elsewhere.parent.mkdir()
    elsewhere.write_text("scratch", encoding="utf-8")
    with pytest.raises(SystemExit, match="is a frozen report"):
        video_audio_check.refuse_frozen_overwrite(elsewhere)


def test_a_harness_may_write_its_own_untracked_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default destination is the reports directory; refusing it would stop the shipped run."""
    monkeypatch.setattr(video_audio_check, "_tracked", lambda path: False)
    fresh = tmp_path / "VIDEO_AUDIO.md"
    fresh.write_text("not yet evidence", encoding="utf-8")
    video_audio_check.refuse_frozen_overwrite(fresh)


def test_an_absolute_path_to_the_frozen_directory_is_refused_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard asks about the file, not the spelling of its path."""
    monkeypatch.setattr(video_audio_check, "_tracked", lambda path: True)
    frozen = tmp_path / "VIDEO_AUDIO.md"
    frozen.write_text("committed evidence", encoding="utf-8")
    with pytest.raises(SystemExit, match="is a frozen report"):
        video_audio_check.refuse_frozen_overwrite(Path(frozen.resolve()))


def test_a_committed_report_is_frozen_without_any_stub(tmp_path: Path) -> None:
    """A stubbed `_tracked` proves the branch works, not that the guard does: this test uses the real git index."""
    committed = Path("bench/reports/LEGS.md")
    assert committed.exists(), "the acceptance needs a tracked report to refuse"
    with pytest.raises(SystemExit, match="is a frozen report"):
        video_audio_check.refuse_frozen_overwrite(committed)
    elsewhere = tmp_path / "LEGS.md"
    elsewhere.write_text("mine", encoding="utf-8")
    video_audio_check.refuse_frozen_overwrite(elsewhere)


def test_the_suite_arm_scores_every_answerable_query_and_the_smoke_knob_keeps_every_kind() -> None:
    """The cost of speech lands on the other modalities, so the after row must see all of them."""
    whole = video_audio_check.answerable_suite(0)
    assert all(query.gold for query in whole)
    assert {query.modality for query in whole} == set(video_audio_check.MODALITY_ORDER)
    smoke = video_audio_check.answerable_suite(60)
    assert 0 < len(smoke) <= 60
    assert {query.modality for query in smoke} == set(video_audio_check.MODALITY_ORDER)


def test_an_empty_video_arm_is_a_lie_not_a_zero() -> None:
    """The video arm is the point of the harness; a row of zeros there must stop the run."""
    with pytest.raises(SystemExit, match="nothing to rank"):
        video_audio_check._required(None, "every video question")


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


def _store(home: Path, videos: list[str], speech: int) -> Path:
    """A store with just the columns the reuse guard reads."""
    import sqlite3

    (home / "data").mkdir(parents=True)
    with sqlite3.connect(home / "data" / "ely_eye.sqlite") as connection:
        connection.execute("CREATE TABLE sources (source_id TEXT, kind TEXT)")
        connection.execute("CREATE TABLE atoms (modality TEXT, text TEXT, holder_id TEXT DEFAULT 'wife')")
        connection.executemany("INSERT INTO sources VALUES (?, 'video')", [(name,) for name in videos])
        connection.executemany("INSERT INTO atoms (modality, text) VALUES ('audio', 'said')", [() for _ in range(speech)])
    return home


def test_a_reused_speech_store_must_be_the_same_videos_with_speech(tmp_path: Path) -> None:
    home = _store(tmp_path / "home", ["a", "b"], speech=0)
    speech = _store(tmp_path / "speech", ["a", "b"], speech=3)

    reused = video_audio_check.reuse_speech(home, speech, tmp_path / "scratch")

    assert reused == {"reused": str(speech), "files": 2, "seconds": None}


def test_a_store_without_speech_is_not_reused(tmp_path: Path) -> None:
    home = _store(tmp_path / "home", ["a"], speech=0)
    silent = _store(tmp_path / "silent", ["a"], speech=0)

    with pytest.raises(SystemExit, match="carries no speech atoms"):
        video_audio_check.reuse_speech(home, silent, tmp_path / "scratch")


def test_a_store_of_other_videos_is_not_reused(tmp_path: Path) -> None:
    home = _store(tmp_path / "home", ["a", "b"], speech=0)
    other = _store(tmp_path / "other", ["a", "c"], speech=3)

    with pytest.raises(SystemExit, match="different video sources"):
        video_audio_check.reuse_speech(home, other, tmp_path / "scratch")


def test_the_scratch_cannot_be_the_store_it_reuses(tmp_path: Path) -> None:
    home = _store(tmp_path / "home", ["a"], speech=0)
    speech = _store(tmp_path / "speech", ["a"], speech=3)

    with pytest.raises(SystemExit, match="overwrite the very store"):
        video_audio_check.reuse_speech(home, speech, speech)


def test_a_store_with_atoms_nobody_holds_is_not_ranked(tmp_path: Path) -> None:
    """Re-ingest once wrote every video atom back as nobody's, and every holder's query ranked them."""
    import sqlite3

    store = _store(tmp_path / "speech", ["a"], speech=2)
    video_audio_check.require_owned(store, "after")
    with sqlite3.connect(store / "data" / "ely_eye.sqlite") as connection:
        connection.execute("UPDATE atoms SET holder_id = '' WHERE rowid = 1")

    with pytest.raises(SystemExit, match="1 atoms in .* have no holder"):
        video_audio_check.require_owned(store, "after")
