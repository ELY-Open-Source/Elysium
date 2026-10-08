"""Every harness measures a copy. The frozen baseline store is cited evidence, and the product
migrates whatever database it opens."""

from __future__ import annotations

import shutil
import time
from pathlib import Path


def copy_store(home: Path, scratch: Path) -> tuple[Path, float]:
    """Work on a copy: the baseline store is frozen evidence and must not be migrated in place."""
    source = home / "data" / "ely_eye.sqlite"
    if not source.is_file():
        raise SystemExit(
            f"{source}: no product database, build it with python -m bench.ingest_baseline"
        )
    data = scratch / "data"
    data.mkdir(parents=True, exist_ok=True)
    began = time.perf_counter()
    for suffix in ("", "-wal", "-shm"):
        if (path := Path(str(source) + suffix)).is_file():
            shutil.copyfile(path, data / (source.name + suffix))
    return scratch, time.perf_counter() - began
