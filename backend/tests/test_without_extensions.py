"""A Python whose sqlite3 cannot load extensions (uv's on macOS) still keeps memory.

Only the dense leg reads the vec0 table, so only it may demand sqlite-vec; before this, every
connection loaded it and `elysian init` died on a stock macOS install.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from elysian import vector_index
from elysian.config import Settings
from elysian.memory import MemoryService
from elysian.retrieval import RetrievalService
from elysian.schemas import MemoryOrigin
from elysian.vector_index import VectorIndex


def refuse(_connection: object) -> None:
    raise SystemExit("this Python's sqlite3 cannot load extensions")


def test_remember_search_and_forget_need_no_extension(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vector_index, "load_extension", refuse)
    settings = Settings(home=tmp_path)
    memory = MemoryService(settings=settings)

    atom = memory.remember("the archive key is in the second drawer", holder_id="wife", origin=MemoryOrigin.self_)
    hits = RetrievalService(settings, memory.db).search("archive key").hits
    report = memory.forget(atom_id=atom.atom_id)

    assert [hit.atom.atom_id for hit in hits] == [atom.atom_id]
    assert report.atoms_deleted == 1
    assert VectorIndex(settings, memory.db).stats()["built"] is False


def test_the_dense_leg_still_demands_the_extension(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vector_index, "load_extension", refuse)
    settings = Settings(home=tmp_path, dense_embeddings_enabled=True)

    with pytest.raises(SystemExit, match="cannot load extensions"), VectorIndex(settings).connect():
        pass
