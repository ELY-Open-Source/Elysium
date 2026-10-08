"""Retrieval arms for the ablation. Every arm reads the same merged baseline database.

The arms are the product's own signals, switched on one at a time: sparse BM25, dense
cosine, the evidence graph, the product's weighted fusion, and fusion plus a cross-encoder
reranker. Rankings are lists of source ids: an atom votes for its source, and a source is
ranked by its best atom.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from bench.ingest_baseline import source_map

if TYPE_CHECKING:
    from ely_eye.db import Database
from bench.sets_common import ROOT

RUNS = ROOT / "runs" / "baseline"
INDEX_DIR = RUNS / "index"
MODELS = ROOT / "models"
DENSE_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RERANK_MODEL = "BAAI/bge-reranker-base"
THREADS_PER_QUERY = 4


def _pin_threads() -> None:
    """Fix the CPU budget per query before torch loads; a run that grabs all 32 cores measures the scheduler."""
    for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(variable, str(THREADS_PER_QUERY))


_pin_threads()


def machine_facts() -> dict[str, Any]:
    """Hardware plus the load at report time: latency numbers mean nothing without it."""
    return {
        "system": platform.system(),
        "release": platform.release(),
        "cpus": os.cpu_count(),
        "threads_per_query": int(os.environ.get("OMP_NUM_THREADS", THREADS_PER_QUERY)),
        "load_average_1_5_15": [round(value, 2) for value in os.getloadavg()],
    }


def local_model_dir(models: Path, repo_id: str) -> Path:
    """Where a fetched model lives: one flat directory per repo, named by its repo name only."""
    return models / repo_id.split("/")[-1]
DENSE_DIM = 384
FUSION_WEIGHTS = {"sparse": 0.55, "dense": 0.35, "graph": 0.10}
RERANK_CANDIDATES = 50
RERANK_TEXT_CHARS = 400
ARMS = ("bm25_only", "dense_only", "graph_only", "no_rerank", "fusion_rerank")


@dataclass(frozen=True)
class Atom:
    atom_id: str
    source_id: str
    text: str


def load_atoms(db_path: Path) -> list[Atom]:
    """Every atom in the merged database, keyed by the benchmark's source id.

    The product names a source by content hash (`11089_4f2a...`), while the frozen
    sets name the same file by its corpus id. `sources.path` is the only column
    that identifies the original file, so the two id spaces are joined through it.
    """
    if not db_path.is_file():
        raise SystemExit(f"{db_path}: no merged baseline database, run python -m bench.ingest_baseline first")
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT a.atom_id, s.path, a.text FROM atoms AS a "
            "JOIN sources AS s ON s.source_id = a.source_id ORDER BY a.atom_id"
        ).fetchall()
    except sqlite3.OperationalError as error:
        raise SystemExit(f"{db_path}: cannot read the atoms table ({error})") from error
    finally:
        connection.close()
    if not rows:
        raise SystemExit(f"{db_path}: the atoms table is empty")
    mapping = source_map()
    unknown = sorted({str(path) for _, path, _ in rows if str(path) not in mapping})
    if unknown:
        raise SystemExit(f"{db_path}: {len(unknown)} atom paths are not corpus files, first {unknown[:3]}")
    return [
        Atom(atom_id=str(atom_id), source_id=str(mapping[str(path)]), text=str(text or ""))
        for atom_id, path, text in rows
    ]


def tokenize(text: str) -> list[str]:
    """The product's tokenizer: word characters plus CJK, lowercased."""
    return re.findall(r"[\w\u4e00-\u9fff]+", text.lower())


class SparseIndex:
    """BM25 over atom text, built once; the product rebuilds it on every query."""

    def __init__(self, atoms: Sequence[Atom]) -> None:
        from rank_bm25 import BM25Okapi

        corpus = [tokenize(f"{atom.text} {atom.source_id}") for atom in atoms]
        self._model = BM25Okapi(corpus)
        self._count = len(atoms)

    def scores(self, query: str) -> np.ndarray:
        tokens = tokenize(query)
        if not tokens:
            return np.zeros(self._count, dtype=np.float64)
        return np.asarray(self._model.get_scores(tokens), dtype=np.float64)


def _cache_key(model_dir: Path, atoms: Sequence[Atom]) -> str:
    """A cache name that follows the atom set, so a scale-curve subset can never
    be scored with the full corpus's vectors (or the other way round)."""
    joined = "\n".join(atom.atom_id for atom in atoms)
    return f"{model_dir.name}-{hashlib.sha256(joined.encode('utf-8')).hexdigest()[:16]}"


class DenseIndex:
    """Brute-force cosine over cached sentence embeddings, one vector per atom."""

    def __init__(self, atoms: Sequence[Atom], model_dir: Path, batch_size: int = 256, cache_name: str = "") -> None:
        self._cache_name = cache_name or _cache_key(model_dir, atoms)
        self._vectors = self._load_or_build(atoms, model_dir, batch_size)

    def _vectors_path(self, model_dir: Path) -> Path:
        return INDEX_DIR / f"{self._cache_name}.npy"

    def _load_or_build(self, atoms: Sequence[Atom], model_dir: Path, batch_size: int) -> np.ndarray:
        path = self._vectors_path(model_dir)
        order_path = INDEX_DIR / f"{self._cache_name}.atoms.json"
        atom_ids = [atom.atom_id for atom in atoms]
        if path.is_file() and order_path.is_file():
            try:
                vectors = np.load(path)
                cached_ids = json.loads(order_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise SystemExit(f"{order_path}: cached dense index is unreadable ({error})") from error
            if cached_ids == atom_ids and vectors.shape == (len(atoms), DENSE_DIM):
                return vectors
            if cached_ids != atom_ids:
                raise SystemExit(
                    f"{path}: cached vectors cover {len(cached_ids)} atoms but the database has {len(atoms)}; "
                    "delete bench/runs/baseline/index and rebuild"
                )
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        model = _sentence_model(model_dir)
        texts = [atom.text[:RERANK_TEXT_CHARS] if atom.text else atom.source_id for atom in atoms]
        vectors = model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > 2000,
        ).astype(np.float32)
        if vectors.shape[1] != DENSE_DIM:
            raise SystemExit(f"{model_dir}: expected {DENSE_DIM} dimensions, got {vectors.shape[1]}")
        np.save(path, vectors)
        order_path.write_text(json.dumps(atom_ids), encoding="utf-8")
        return vectors

    def scores(self, query: str, model_dir: Path) -> np.ndarray:
        model = _sentence_model(model_dir)
        vector = model.encode([query], normalize_embeddings=True, convert_to_numpy=True).astype(np.float32)
        return np.asarray(self._vectors @ vector[0], dtype=np.float64)


_MODELS: dict[str, Any] = {}


def _sentence_model(model_dir: Path) -> Any:
    """Load a sentence-transformers model once per process.

    The query path called this per query, and constructing the model from disk cost
    more than the encode itself: dense arm p50 was 1.7s of which most was loading, and
    the latency-vs-size curve came out flat because a constant dominated it.
    sentence-transformers ships no stubs, so the model is typed Any rather than a fake object.
    """
    key = str(model_dir)
    if key not in _MODELS:
        from sentence_transformers import SentenceTransformer

        if not model_dir.is_dir():
            raise SystemExit(f"{model_dir}: model not downloaded, run python -m bench.fetch_models first")
        _MODELS[key] = SentenceTransformer(key, local_files_only=True)
    return _MODELS[key]


def top_sources(scores: np.ndarray, atoms: Sequence[Atom], top_k: int) -> list[str]:
    """Rank sources by their best-scoring atom; ties break on source id."""
    if len(scores) != len(atoms):
        raise SystemExit(f"scores has {len(scores)} entries for {len(atoms)} atoms")
    best: dict[str, float] = {}
    for atom, score in zip(atoms, scores, strict=True):
        current = best.get(atom.source_id)
        if current is None or score > current:
            best[atom.source_id] = float(score)
    ranked = sorted(best.items(), key=lambda item: (-item[1], item[0]))
    return [source_id for source_id, _ in ranked[:top_k]]


def fuse(sparse: np.ndarray, dense: np.ndarray, graph: np.ndarray) -> np.ndarray:
    """The product's weighted mix, with each signal scaled to [0, 1]."""
    return (
        FUSION_WEIGHTS["sparse"] * _unit(sparse)
        + FUSION_WEIGHTS["dense"] * _unit(dense)
        + FUSION_WEIGHTS["graph"] * _unit(graph)
    )


def _unit(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values
    low = float(values.min())
    high = float(values.max())
    if high - low <= 1e-12:
        return np.zeros_like(values)
    return (values - low) / (high - low)


class Reranker:
    """Cross-encoder over the fusion candidate list."""

    def __init__(self, model_dir: Path) -> None:
        if not model_dir.is_dir():
            raise SystemExit(f"{model_dir}: model not downloaded, run python -m bench.fetch_models first")
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(str(model_dir), local_files_only=True)

    def scores(self, query: str, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros(0, dtype=np.float64)
        pairs = [(query, text[:RERANK_TEXT_CHARS] or " ") for text in texts]
        return np.asarray(self._model.predict(pairs, batch_size=16), dtype=np.float64)


def arm_needs(arm: str, models: Path) -> bool:
    """Whether an arm's model files are present, so a run can skip it instead of crashing."""
    if arm not in ARMS:
        raise SystemExit(f"{arm}: unknown arm, expected one of {ARMS}")
    required: list[Path] = []
    if arm in ("dense_only", "no_rerank", "fusion_rerank"):
        required.append(local_model_dir(models, DENSE_MODEL))
    if arm == "fusion_rerank":
        required.append(local_model_dir(models, RERANK_MODEL))
    return all(directory.is_dir() for directory in required)


class ArmRunner:
    """One arm, ranked queries in batches, with wall-clock timings recorded."""

    def __init__(self, arm: str, atoms: Sequence[Atom], models: Path) -> None:
        if arm not in ARMS:
            raise SystemExit(f"{arm}: unknown arm, expected one of {ARMS}")
        self.arm = arm
        self.atoms = atoms
        self.models = models
        self.timings: list[float] = []
        self._sparse: SparseIndex | None = None
        self._dense: DenseIndex | None = None
        self._reranker: Reranker | None = None
        if arm in ("bm25_only", "no_rerank", "fusion_rerank"):
            self._sparse = SparseIndex(atoms)
        if arm in ("dense_only", "no_rerank", "fusion_rerank"):
            self._dense = DenseIndex(atoms, local_model_dir(models, DENSE_MODEL))
        if arm == "fusion_rerank":
            self._reranker = Reranker(local_model_dir(models, RERANK_MODEL))

    def rank(self, query: str, top_k: int = 10) -> list[str]:
        started = time.perf_counter()
        ranked = self._rank(query, top_k)
        self.timings.append(time.perf_counter() - started)
        return ranked

    def _rank(self, query: str, top_k: int) -> list[str]:
        if self.arm == "graph_only":
            # The product never populates atom.relations, so the graph signal is a constant.
            graph = np.zeros(len(self.atoms), dtype=np.float64)
            return top_sources(graph, self.atoms, top_k)
        sparse = self._sparse.scores(query) if self._sparse is not None else np.zeros(len(self.atoms))
        if self.arm == "bm25_only":
            return top_sources(sparse, self.atoms, top_k)
        dense_dir = local_model_dir(self.models, DENSE_MODEL)
        dense = (
            self._dense.scores(query, dense_dir) if self._dense is not None else np.zeros(len(self.atoms))
        )
        if self.arm == "dense_only":
            return top_sources(dense, self.atoms, top_k)
        graph = np.zeros(len(self.atoms), dtype=np.float64)
        fused = fuse(sparse, dense, graph)
        if self.arm == "no_rerank":
            return top_sources(fused, self.atoms, top_k)
        candidates = top_sources(fused, self.atoms, RERANK_CANDIDATES)
        by_source = _best_atom_text(self.atoms, candidates)
        if self._reranker is None:
            raise SystemExit(f"{self.arm}: the reranker model is missing, run python -m bench.fetch_models")
        rerank_scores = self._reranker.scores(query, [text for _, text in by_source])
        order = sorted(zip(candidates, rerank_scores, strict=True), key=lambda item: (-item[1], item[0]))
        return [source_id for source_id, _ in order[:top_k]]

    def percentile(self, fraction: float) -> float:
        if not self.timings:
            raise SystemExit(f"{self.arm}: no timings recorded")
        if not 0.0 <= fraction <= 1.0:
            raise SystemExit(f"percentile must be within [0, 1], got {fraction}")
        return float(np.percentile(np.asarray(self.timings), fraction * 100))


# Which measured signals each arm consumes; JointRunner times each signal once and attributes it to every arm that uses it.
ARM_COMPONENTS: dict[str, tuple[str, ...]] = {
    "bm25_only": ("sparse",),
    "dense_only": ("dense",),
    "graph_only": ("graph",),
    "no_rerank": ("sparse", "dense", "graph", "fuse"),
    "fusion_rerank": ("sparse", "dense", "graph", "fuse"),
}


class JointRunner:
    """Every requested arm over one corpus, computing each signal once per query.

    ArmRunner recomputes the sparse and dense signals per arm; over 166K atoms that is
    hours of duplicated work. This pass computes each signal once and derives every
    arm's ranking from it, so a ranking matches ArmRunner's exactly while latency is
    attributed to the components that arm actually uses.
    """

    def __init__(self, arms: Sequence[str], atoms: Sequence[Atom], models: Path) -> None:
        for arm in arms:
            if arm not in ARMS:
                raise SystemExit(f"{arm}: unknown arm, expected one of {ARMS}")
        if not arms:
            raise SystemExit("JointRunner needs at least one arm")
        self.arms = [arm for arm in ARMS if arm in arms]
        self.atoms = atoms
        self.models = models
        self.timings: dict[str, list[float]] = {arm: [] for arm in self.arms}
        self._sparse: SparseIndex | None = None
        self._dense: DenseIndex | None = None
        self._reranker: Reranker | None = None
        if any(arm in ("bm25_only", "no_rerank", "fusion_rerank") for arm in self.arms):
            self._sparse = SparseIndex(atoms)
        if any(arm in ("dense_only", "no_rerank", "fusion_rerank") for arm in self.arms):
            self._dense = DenseIndex(atoms, local_model_dir(models, DENSE_MODEL))
        if "fusion_rerank" in self.arms:
            self._reranker = Reranker(local_model_dir(models, RERANK_MODEL))

    def rank_all(self, query: str, top_k: int = 10) -> dict[str, tuple[list[str], float]]:
        """Rank one query with every arm; returns {arm: (source_ids, seconds)}."""
        signals: dict[str, np.ndarray] = {}
        seconds: dict[str, float] = {}
        started = time.perf_counter()
        signals["graph"] = np.zeros(len(self.atoms), dtype=np.float64)
        seconds["graph"] = time.perf_counter() - started
        if self._sparse is not None:
            started = time.perf_counter()
            signals["sparse"] = self._sparse.scores(query)
            seconds["sparse"] = time.perf_counter() - started
        if self._dense is not None:
            started = time.perf_counter()
            signals["dense"] = self._dense.scores(query, local_model_dir(self.models, DENSE_MODEL))
            seconds["dense"] = time.perf_counter() - started
        if any(arm in ("no_rerank", "fusion_rerank") for arm in self.arms):
            started = time.perf_counter()
            signals["fuse"] = fuse(
                signals.get("sparse", np.zeros(len(self.atoms))),
                signals.get("dense", np.zeros(len(self.atoms))),
                signals["graph"],
            )
            seconds["fuse"] = time.perf_counter() - started
        ranked: dict[str, tuple[list[str], float]] = {}
        for arm in self.arms:
            started = time.perf_counter()
            order = self._order(arm, query, signals, top_k)
            total = sum(seconds[name] for name in ARM_COMPONENTS[arm]) + (time.perf_counter() - started)
            self.timings[arm].append(total)
            ranked[arm] = (order, total)
        return ranked

    def _order(self, arm: str, query: str, signals: dict[str, np.ndarray], top_k: int) -> list[str]:
        if arm == "graph_only":
            return top_sources(signals["graph"], self.atoms, top_k)
        if arm == "bm25_only":
            return top_sources(signals["sparse"], self.atoms, top_k)
        if arm == "dense_only":
            return top_sources(signals["dense"], self.atoms, top_k)
        fused = signals["fuse"]
        if arm == "no_rerank":
            return top_sources(fused, self.atoms, top_k)
        candidates = top_sources(fused, self.atoms, RERANK_CANDIDATES)
        by_source = _best_atom_text(self.atoms, candidates)
        if self._reranker is None:
            raise SystemExit(f"{arm}: the reranker model is missing, run python -m bench.fetch_models")
        rerank_scores = self._reranker.scores(query, [text for _, text in by_source])
        order = sorted(zip(candidates, rerank_scores, strict=True), key=lambda item: (-item[1], item[0]))
        return [source_id for source_id, _ in order[:top_k]]


def _best_atom_text(atoms: Sequence[Atom], source_ids: Sequence[str]) -> list[tuple[str, str]]:
    longest: dict[str, str] = {}
    for atom in atoms:
        if atom.source_id in longest:
            if len(atom.text) > len(longest[atom.source_id]):
                longest[atom.source_id] = atom.text
        else:
            longest[atom.source_id] = atom.text
    return [(source_id, longest.get(source_id, "")) for source_id in source_ids]


def _corpus_ids(database: Database) -> dict[str, str]:
    """Join the store's content-hash source ids to the ids the frozen sets call a source by.

    Without this join the product's hits and the gold answers share no name, and a correct answer
    scores zero — which is what an earlier report recorded as "0% overlap with the fast path".
    """
    mapping = source_map()
    ids: dict[str, str] = {}
    unknown: list[str] = []
    for source in database.list_sources():
        corpus_id = mapping.get(str(Path(source.path).resolve()))
        if corpus_id is None:
            unknown.append(source.source_id)
        else:
            ids[source.source_id] = corpus_id
    if unknown:
        raise SystemExit(f"{database.path}: {len(unknown)} store sources are not corpus files, first {unknown[:3]}")
    return ids


def live_product_rankings(
    db_home: Path,
    queries: Sequence[str],
    top_k: int = 10,
    as_holders: Sequence[str | None] | None = None,
) -> tuple[list[list[str]], list[int], list[float]]:
    """Rankings from the unmodified RetrievalService, with per-query wall time.

    Rankings carry the benchmark's source ids, so they are comparable with the arms and with gold.
    `as_holders` asks each query as its own holder, which is how a transactive memory is used: the
    asker does not know where the answer is, only who might.

    The second list counts how many distinct sources the product's top-k atoms came from: the
    product ranks atoms and never diversifies, so ten slots can be filled by fragments of one
    document, and that is invisible once the hits are collapsed.
    """
    from ely_eye.config import Settings
    from ely_eye.db import Database
    from ely_eye.retrieval import RetrievalService
    from ely_eye.schemas import SearchFilters

    if as_holders is not None and len(as_holders) != len(queries):
        raise SystemExit(f"{len(as_holders)} holders for {len(queries)} queries")
    settings = Settings(home=db_home)
    database = Database(settings)
    service = RetrievalService(settings=settings, database=database)
    corpus_ids = _corpus_ids(database)
    rankings: list[list[str]] = []
    distinct: list[int] = []
    timings: list[float] = []
    for index, query in enumerate(queries):
        holder = as_holders[index] if as_holders is not None else None
        started = time.perf_counter()
        hits = service.search(query, top_k=top_k, filters=SearchFilters(as_holder=holder)).hits
        timings.append(time.perf_counter() - started)
        # The product ranks atoms; collapse to sources by first (best) hit so the arms stay comparable.
        sources: list[str] = []
        for hit in hits:
            source_id = corpus_ids[hit.atom.source_id]
            if source_id not in sources:
                sources.append(source_id)
        distinct.append(len({corpus_ids[hit.atom.source_id] for hit in hits}))
        rankings.append(sources[:top_k])
    return rankings, distinct, timings
