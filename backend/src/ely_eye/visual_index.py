"""A picture found by a picture, or by a sentence in either language.

Text search cannot reach an image with no words on it: OCR returns nothing, so the atom's
text is empty and the index has nothing to match. This index keeps one CLIP vector per image
atom and encodes the query with the matching tower — a picture with the image tower, a
sentence with the text tower — so both land in the same space and a screenshot can be found
either way.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .clip_encoder import DOWNLOAD_HINT, ClipEncoder
from .config import Settings, get_settings
from .db import Database
from .schemas import EvidenceAtom
from .storage import ObjectStore

INDEX_NAME = "clip_image_index.npy"
MAP_NAME = "clip_image_index_atoms.json"
GRAPH_PART = Path("onnx") / "model_fp16.onnx"

# Loading 48k vectors costs about as much as the search itself, and the API builds a fresh
# service per request, so the array is kept per process and re-read only when the file changes.
_LOADED: dict[tuple[str, float], tuple[list[str], np.ndarray]] = {}


def is_visual(atom: EvidenceAtom) -> bool:
    """An atom is findable by picture only if there is a picture behind it."""
    return bool(atom.image_ref)


class VisualIndex:
    """CLIP vectors for the image atoms, plus the two ways to ask for them."""

    def __init__(self, settings: Settings | None = None, database: Database | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = database or Database(self.settings)
        self.index_path = self.settings.cache_dir / INDEX_NAME
        self.map_path = self.settings.cache_dir / MAP_NAME
        self._encoder: ClipEncoder | None = None

    def model_dir(self) -> Path | None:
        """The CLIP snapshot, or None when this machine has not fetched one."""
        model_dir = self.settings.clip_model_dir
        if model_dir is None or not (model_dir / GRAPH_PART).exists():
            return None
        return model_dir

    def available(self) -> bool:
        return self.model_dir() is not None

    def encoder(self) -> ClipEncoder:
        if self._encoder is None:
            model_dir = self.model_dir()
            if model_dir is None:
                raise SystemExit(
                    f"visual search needs a Chinese-CLIP snapshot; set ELY_EYE_CLIP_MODEL_DIR. {DOWNLOAD_HINT}"
                )
            self._encoder = ClipEncoder(model_dir)
        return self._encoder

    def visual_atoms(self, atoms: list[EvidenceAtom] | None = None) -> list[EvidenceAtom]:
        """Image atoms whose bytes are still on disk; a dead reference cannot be encoded."""
        pool = self.db.list_atoms() if atoms is None else atoms
        store = ObjectStore(self.settings)
        kept: list[EvidenceAtom] = []
        for atom in pool:
            if not is_visual(atom):
                continue
            path = store.resolve(str(atom.image_ref))
            if path.exists():
                kept.append(atom)
        return kept

    def build(self, atoms: list[EvidenceAtom] | None = None) -> dict[str, Any]:
        """Encode every image atom once; the batch is what keeps this affordable."""
        started = time.monotonic()
        pool = self.visual_atoms(atoms)
        encoder = self.encoder()
        vectors: list[np.ndarray] = []
        kept: list[EvidenceAtom] = []
        batch: list[Image.Image] = []
        for atom in pool:
            try:
                with Image.open(ObjectStore(self.settings).resolve(str(atom.image_ref))) as picture:
                    batch.append(picture.convert("RGB"))
            except OSError as error:
                print(f"skipping {atom.atom_id}: the image will not open ({error})")
                continue
            kept.append(atom)
            if len(batch) >= 32:
                vectors.append(encoder.encode_images(batch))
                batch = []
        if batch:
            vectors.append(encoder.encode_images(batch))
        matrix = np.concatenate(vectors) if vectors else np.zeros((0, 512), dtype=np.float32)
        self._write([atom.atom_id for atom in kept], matrix)
        return {
            "atoms": len(kept),
            "dim": int(matrix.shape[1]) if matrix.size else 0,
            "seconds": round(time.monotonic() - started, 2),
            "model_dir": str(self.model_dir()),
        }

    def load(self) -> tuple[list[str], np.ndarray] | None:
        if not self.index_path.exists() or not self.map_path.exists():
            return None
        stamp = (str(self.index_path), self.index_path.stat().st_mtime)
        cached = _LOADED.get(stamp)
        if cached is not None:
            return cached
        atom_ids = _read_ids(self.map_path)
        vectors = np.load(self.index_path)
        if len(atom_ids) != vectors.shape[0]:
            raise ValueError(
                f"{self.map_path}: {len(atom_ids)} atoms for {vectors.shape[0]} vectors; rebuild with ely-eye index-visual"
            )
        _LOADED.clear()
        _LOADED[stamp] = (atom_ids, vectors)
        return atom_ids, vectors

    def drop(self) -> bool:
        """Delete the index files and the copy this process is holding.

        Forget has to void this index the way it voids the text one: a forgotten picture that
        still answers from an array in memory is a memory that was never forgotten.
        """
        removed = False
        for path in (self.index_path, self.map_path):
            if path.exists():
                path.unlink()
                removed = True
        _LOADED.clear()
        return removed

    def visual_atom_ids(self) -> set[str]:
        """Picture atoms whose bytes are still on disk, asked with one light query."""
        store = ObjectStore(self.settings)
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT atom_id, image_ref FROM v_atoms_current WHERE image_ref IS NOT NULL AND image_ref != ''"
            ).fetchall()
        kept: set[str] = set()
        for row in rows:
            try:
                path = store.resolve(str(row["image_ref"]))
            except ValueError:
                continue
            if path.exists():
                kept.add(str(row["atom_id"]))
        return kept

    def is_current(self, atom_ids: set[str] | None = None) -> bool:
        """True when the index covers exactly the picture atoms the store holds right now."""
        loaded = self.load()
        if loaded is None:
            return False
        wanted = self.visual_atom_ids() if atom_ids is None else atom_ids
        return wanted == set(loaded[0])

    def search_text(self, query: str, top_k: int, restrict: set[str] | None = None) -> list[tuple[str, float]]:
        vector = self.encoder().encode_texts([query])[0]
        return self._nearest(vector, top_k, restrict)

    def search_image(self, image: Path, top_k: int, restrict: set[str] | None = None) -> list[tuple[str, float]]:
        with Image.open(image) as picture:
            vector = self.encoder().encode_images([picture.convert("RGB")])[0]
        return self._nearest(vector, top_k, restrict)

    def _nearest(
        self, query_vector: np.ndarray, top_k: int, restrict: set[str] | None = None
    ) -> list[tuple[str, float]]:
        """Closest stored pictures, optionally inside one candidate pool.

        The pool is how a benchmark asks a smaller question — “which element of this screen” —
        without rebuilding the index per question.
        """
        loaded = self.load()
        if loaded is None or top_k <= 0:
            return []
        atom_ids, vectors = loaded
        if vectors.size == 0:
            return []
        query = _unit(query_vector.reshape(1, -1))[0]
        scores = _unit(vectors) @ query
        if restrict is not None:
            keep = np.fromiter((atom_id in restrict for atom_id in atom_ids), dtype=bool, count=len(atom_ids))
            scores = np.where(keep, scores, -np.inf)
        order = np.argsort(scores)[::-1][:top_k]
        return [(atom_ids[index], float(scores[index])) for index in order if np.isfinite(scores[index])]

    def _write(self, atom_ids: list[str], vectors: np.ndarray) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(self.index_path, vectors)
        self.map_path.write_text(json.dumps(atom_ids, ensure_ascii=False), encoding="utf-8")
        _LOADED.clear()


def _read_ids(path: Path) -> list[str]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{path}: the visual index map is unreadable ({error})") from error


def _unit(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms
