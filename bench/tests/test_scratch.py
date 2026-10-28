"""A scratch copy is one run's working store; two runs on one path silently measure each other's data."""

import os
from pathlib import Path

import pytest

from bench import scratch


def test_a_live_holder_refuses_the_same_scratch(tmp_path: Path) -> None:
    """The collision I hit: a second run re-copied the store under a run that was ingesting into it."""
    if not Path("/proc/1").exists():
        pytest.skip("liveness is read from /proc")
    (tmp_path / scratch.HELD).write_text("1", encoding="utf-8")
    with pytest.raises(SystemExit, match="is held by pid 1"):
        scratch.claim(tmp_path)


def test_a_stale_claim_is_taken_over(tmp_path: Path) -> None:
    """A crashed run must not lock the scratch away forever."""
    (tmp_path / scratch.HELD).write_text("999999", encoding="utf-8")
    scratch.claim(tmp_path)
    assert (tmp_path / scratch.HELD).read_text(encoding="utf-8") == str(os.getpid())


def test_one_run_may_copy_more_than_once(tmp_path: Path) -> None:
    """Harnesses that score several arms re-copy on purpose; that is not a collision."""
    scratch.claim(tmp_path)
    scratch.claim(tmp_path)
    assert (tmp_path / scratch.HELD).read_text(encoding="utf-8") == str(os.getpid())


def test_copy_store_claims_the_copy_it_makes(tmp_path: Path) -> None:
    """The claim lives inside `copy_store`, so a harness cannot step on a live run by forgetting to call `claim`."""
    if not Path("/proc/1").exists():
        pytest.skip("liveness is read from /proc")
    source = tmp_path / "source"
    (source / "data").mkdir(parents=True)
    (source / "data" / "elysium.sqlite").write_text("store", encoding="utf-8")
    busy = tmp_path / "scratch"
    busy.mkdir()
    (busy / scratch.HELD).write_text("1", encoding="utf-8")
    with pytest.raises(SystemExit, match="is held by pid 1"):
        scratch.copy_store(source, busy)
    assert not (busy / "data").exists(), "the refusal must come before a byte is copied"
