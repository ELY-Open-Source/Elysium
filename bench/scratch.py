"""Every harness measures a copy. The frozen baseline store is cited evidence, and the product
migrates whatever database it opens."""

from __future__ import annotations

import atexit
import os
import shutil
import time
from pathlib import Path

HELD = "held_by"


def _alive(pid: str) -> bool:
    """A live process holds the copy. Without /proc there is nothing to check, so a stale lock cannot block a run."""
    return pid.isdigit() and Path(f"/proc/{pid}").exists()


def claim(scratch: Path) -> None:
    """Refuse a copy another run is already using: two harnesses on one scratch overwrite each other's store mid-measurement."""
    lock = scratch / HELD
    if lock.exists():
        holder = lock.read_text(encoding="utf-8").strip()
        if _alive(holder) and holder != str(os.getpid()):
            raise SystemExit(
                f"{scratch} is held by pid {holder}; wait for that run or pass a different scratch path"
            )
    scratch.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(_release, scratch)


def _release(scratch: Path) -> None:
    """Drop the claim, but only if it is still ours."""
    lock = scratch / HELD
    if lock.exists() and lock.read_text(encoding="utf-8").strip() == str(os.getpid()):
        lock.unlink(missing_ok=True)


def copy_store(home: Path, scratch: Path) -> tuple[Path, float]:
    """Work on a copy: the baseline store is frozen evidence and must not be migrated in place."""
    source = home / "data" / "ely_eye.sqlite"
    if not source.is_file():
        raise SystemExit(
            f"{source}: no product database, build it with python -m bench.ingest_baseline"
        )
    claim(scratch)
    data = scratch / "data"
    data.mkdir(parents=True, exist_ok=True)
    began = time.perf_counter()
    for suffix in ("", "-wal", "-shm"):
        if (path := Path(str(source) + suffix)).is_file():
            shutil.copyfile(path, data / (source.name + suffix))
    return scratch, time.perf_counter() - began
