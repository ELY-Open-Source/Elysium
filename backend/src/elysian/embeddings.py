"""The text side of the senses: one model, one unit vector per memory that has words."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .config import Settings, get_settings
from .db import Database
from .schemas import EvidenceAtom


class EmbeddingService:
    """`model` is injectable so a test can rank without loading a 500 MB snapshot."""

    def __init__(
        self, settings: Settings | None = None, database: Database | None = None, model: Any | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.db = database or Database(self.settings)
        self._model = model
        self._dim: int | None = None

    def enabled(self) -> bool:
        return self.settings.dense_embeddings_enabled

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        """Unit-normalized float32 rows, in the order given."""
        if not texts:
            raise ValueError("encode_texts was asked to encode nothing")
        vectors = self._load_model().encode(
            [{"text": text} for text in texts], normalize_embeddings=True, show_progress_bar=False
        )
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2:
            raise ValueError(f"the embedding model returned a {matrix.shape} array, expected rows of vectors")
        return normalize(matrix)

    def encode_atoms(self, atoms: list[EvidenceAtom]) -> np.ndarray:
        return self.encode_texts([_text_of(atom) for atom in atoms])

    def embed_query(self, query: str) -> np.ndarray:
        return self.encode_texts([query])[0]

    def probe_dim(self) -> int:
        """The width this model produces, asked before the vector table is created."""
        if self._dim is None:
            self._dim = int(self.encode_texts(["dimension probe"]).shape[1])
        return self._dim

    def _load_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(str(self._model_ref()), trust_remote_code=True)
        return self._model

    def _model_ref(self) -> str | Path:
        """A local snapshot when one is set; otherwise the hub id, which SentenceTransformer caches."""
        directory = self.settings.embedding_model_dir
        if directory is None:
            return self.settings.embedding_model_id
        if not directory.exists():
            raise SystemExit(f"{directory}: the embedding model has not been downloaded")
        return directory


def _text_of(atom: EvidenceAtom) -> str:
    return atom.text or ""


def normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms
