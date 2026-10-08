"""What this machine can actually perceive, computed once and read by status and doctor alike."""

from __future__ import annotations

from pathlib import Path

from .config import Settings
from .db import Database
from .embeddings import EmbeddingService
from .schemas import DenseState, SenseState, SenseStatus, VisualState
from .visual_index import VisualIndex


def sense_facts(settings: Settings, database: Database, visual: VisualIndex | None = None) -> SenseStatus:
    """Report the senses as facts, so the UI and the doctor cannot disagree about what is missing.

    A path set but gone on disk is a different failure from a path never set: the first is a broken
    install, the second is a machine that was never given that sense.
    """
    index = visual or VisualIndex(settings, database)
    claimed = _picture_claim(database)
    on_disk = index.visual_atom_ids()
    dense, covered, total = _dense_facts(settings, database)
    return SenseStatus(
        dense=dense,
        dense_covered=covered,
        store_atoms=total,
        picture_atoms=claimed,
        picture_bytes_missing=max(0, claimed - len(on_disk)),
        visual=_visual_state(index, on_disk),
        audio_atoms=_audio_count(database),
        speech=_sense_state(settings.asr_model_dir),
        captioning=_sense_state(settings.vlm_model_dir),
        clip_path=_stated(settings.clip_model_dir),
        asr_path=_stated(settings.asr_model_dir),
        vlm_path=_stated(settings.vlm_model_dir),
    )


def _dense_facts(settings: Settings, database: Database) -> tuple[DenseState, int, int]:
    total = database.atom_count()
    if not settings.dense_embeddings_enabled:
        return "off", 0, total
    loaded = EmbeddingService(settings, database).load_index()
    if loaded is None:
        return "missing", 0, total
    covered = len(loaded.atom_ids)
    return ("current" if covered == total else "behind"), covered, total


def _visual_state(visual: VisualIndex, pictures: set[str]) -> VisualState:
    """A store of pictures the index has not encoded yet is stale: they are invisible to search."""
    if not visual.available():
        return "absent"
    if not pictures:
        return "ready"
    loaded = visual.load()
    return "ready" if loaded is not None and set(loaded[0]) == pictures else "stale"


def _picture_claim(database: Database) -> int:
    """Atoms that say they hold a picture, whether or not the bytes survived."""
    with database.connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM v_atoms_current WHERE image_ref IS NOT NULL AND image_ref != ''"
        ).fetchone()
    return int(row[0])


def _sense_state(model_dir: Path | None) -> SenseState:
    """A sense with no configured snapshot is absent; one pointing at a deleted directory is missing."""
    if model_dir is None:
        return "absent"
    return "ready" if model_dir.exists() else "missing"


def _stated(model_dir: Path | None) -> str | None:
    return None if model_dir is None else str(model_dir)


def _audio_count(database: Database) -> int:
    with database.connect() as connection:
        row = connection.execute("SELECT COUNT(*) AS n FROM v_atoms_current WHERE modality = 'audio'").fetchone()
    return int(row["n"])
