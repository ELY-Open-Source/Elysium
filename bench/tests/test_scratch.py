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
