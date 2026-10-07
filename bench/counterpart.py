"""Mem0- and Zep-style memory counterparts, so the baseline table has an external reference point.

Both counterparts read the same ingested corpus and the same embeddings as the ely-eye arms;
only the memory management differs, which is the thing being compared.

* Mem0-style: one flat store, every item scoped by holder, sha256 dedup, no invalidation —
  a newer fact about the same subject sits next to the old one forever.
* Zep-style: the same items carry valid_from / valid_to; a newer item about the same subject
  closes the older one, and a query at time T cannot see a closed item.

Extraction is lexical, not LLM: Mem0's real `add()` and Zep's graph builder call a generator
model, and this round has no generator installed. The deviation is recorded in the report and
in bench/README.md; it is the same extractor for both counterparts, so the comparison between
them stays fair.

Run: python -m bench.run_external
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from itertools import pairwise
from pathlib import Path

import numpy as np

from bench.ingest_baseline import source_map
from bench.sets_common import MODALITIES, SETS, read_jsonl
from bench.systems import (
    DENSE_MODEL,
    MODELS,
    Atom,
    DenseIndex,
    local_model_dir,
    tokenize,
)

ITEM_CHARS = 400
OVERLAP_SUPERSEDE_LIMIT = 0.5
MIN_SUBJECT_TOKEN_CHARS = 4
STOPWORDS = frozenset(
    [
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "that", "this",
        "these", "those", "is", "are", "was", "were", "be", "been", "being", "what", "which",
        "who", "whom", "whose", "when", "where", "why", "how", "not", "no", "nor", "but", "if",
        "then", "than", "so", "as", "at", "by", "from", "into", "about", "over", "under",
        "again", "further", "once", "here", "there", "all", "any", "both", "each", "few",
        "more", "most", "other", "some", "such", "only", "own", "same", "he", "she", "they",
        "them", "his", "her", "their", "its", "it", "we", "you", "i", "me", "us", "him",
        "一个", "什么", "怎么", "为什么", "哪里", "时候", "这个", "那个", "可以", "应该",
        "我们", "你们", "他们", "自己", "因为", "所以", "但是", "如果",
    ]
)


@dataclass(frozen=True)
class SourceMeta:
    """What the frozen corpus index says about one source."""

    source_id: str
    holder: str
    scenario: str
    modality: str
    observed_at: str


@dataclass
class MemoryItem:
    """One remembered thing, with the three facts a shared memory needs: who, when, what."""

    item_id: str
    text: str
    source_id: str
    holder: str
    scenario: str
    observed_at: str
    subject: str
    valid_from: str
    valid_to: str | None = None


def load_source_index() -> dict[str, SourceMeta]:
    """source_id -> holder / scenario / modality / observed_at, from the frozen corpus index."""
    index: dict[str, SourceMeta] = {}
    for modality in MODALITIES:
        for record in read_jsonl(SETS / "corpus" / f"{modality}.jsonl"):
            missing = [key for key in ("source_id", "holder", "scenario", "observed_at") if not record.get(key)]
            if missing:
                raise SystemExit(f"{modality}: corpus record {record.get('source_id')} lacks {missing}")
            meta = SourceMeta(
                source_id=str(record["source_id"]),
                holder=str(record["holder"]),
                scenario=str(record["scenario"]),
                modality=modality,
                observed_at=str(record["observed_at"]),
            )
            if meta.source_id in index:
                raise SystemExit(f"{meta.source_id}: source id appears in two corpus indexes")
            index[meta.source_id] = meta
    if not index:
        raise SystemExit("no corpus index found, run python -m bench.build_sets first")
    return index


def load_item_atoms(db_path: Path) -> list[Atom]:
    """Atom text for every source the corpus index names, re-keyed from product ids to corpus ids.

    The product names a source by file content ({stem}_{sha256[:16]}, storage.py:28), which is not the
    id the frozen sets use. The sources table keeps the file path, and bench.ingest_baseline.source_map()
    is the corpus-id-to-path map, so the join recovers the corpus identity the gold answers are written in.
    """
    if not db_path.is_file():
        raise SystemExit(f"{db_path}: no baseline database, run python -m bench.ingest_baseline first")
    path_to_corpus_id = source_map()
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT a.atom_id, s.path, a.text FROM atoms a JOIN sources s ON s.source_id = a.source_id"
            " ORDER BY a.atom_id"
        ).fetchall()
    except sqlite3.OperationalError as error:
        raise SystemExit(f"{db_path}: cannot read the atoms table ({error})") from error
    finally:
        connection.close()
    if not rows:
        raise SystemExit(f"{db_path}: the atoms table is empty")
    atoms = [
        Atom(atom_id=str(atom_id), source_id=path_to_corpus_id[path], text=str(text or ""))
        for atom_id, path, text in rows
        if path in path_to_corpus_id
    ]
    if not atoms:
        raise SystemExit(f"{db_path}: none of its {len(rows)} atoms map to a corpus source id")
    return atoms


def split_items(text: str) -> list[str]:
    """Cut source text into rememberable chunks; sentence boundaries first, then a hard cut."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    pieces: list[str] = []
    for sentence in re.split(r"(?<=[.!?。！？；;])\s+", cleaned):
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > ITEM_CHARS:
            pieces.append(sentence[:ITEM_CHARS])
            sentence = sentence[ITEM_CHARS:]
        pieces.append(sentence)
    merged: list[str] = []
    buffer = ""
    for piece in pieces:
        if not buffer:
            buffer = piece
        elif len(buffer) + 1 + len(piece) <= ITEM_CHARS:
            buffer = f"{buffer} {piece}"
        else:
            merged.append(buffer)
            buffer = piece
    if buffer:
        merged.append(buffer)
    return merged


def subject_of(text: str) -> str:
    """The lexical stand-in for an entity: the most frequent content token in the item."""
    counts = Counter(
        token
        for token in tokenize(text)
        if len(token) >= MIN_SUBJECT_TOKEN_CHARS and token not in STOPWORDS and not token.isdigit()
    )
    if not counts:
        return ""
    token, count = counts.most_common(1)[0]
    return token if count >= 2 else ""


def overlap(first: str, second: str) -> float:
    """Jaccard overlap of two items' token sets; low overlap means they are not the same statement."""
    a, b = set(tokenize(first)), set(tokenize(second))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def build_items(atoms: Sequence[Atom], index: dict[str, SourceMeta]) -> list[MemoryItem]:
    """Turn ingested atoms into memory items, deduped by (holder, text hash) the way Mem0 dedups."""
    items: list[MemoryItem] = []
    seen: set[tuple[str, str]] = set()
    unknown: set[str] = set()
    for atom in atoms:
        meta = index.get(atom.source_id)
        if meta is None:
            unknown.add(atom.source_id)
            continue
        for position, text in enumerate(split_items(atom.text)):
            key = (meta.holder, hashlib.sha256(text.encode("utf-8")).hexdigest())
            if key in seen:
                continue
            seen.add(key)
            items.append(
                MemoryItem(
                    item_id=f"{atom.source_id}#{position}",
                    text=text,
                    source_id=atom.source_id,
                    holder=meta.holder,
                    scenario=meta.scenario,
                    observed_at=meta.observed_at,
                    subject=subject_of(text),
                    valid_from=meta.observed_at,
                )
            )
    if unknown:
        print(f"note: {len(unknown)} ingested sources are not in the corpus index and carry no memory scope")
    return items


def supersede(items: Sequence[MemoryItem]) -> int:
    """Close older items about the same subject when a newer, different statement arrives (Zep-style)."""
    by_subject: dict[tuple[str, str], list[MemoryItem]] = {}
    for item in items:
        if item.subject:
            by_subject.setdefault((item.holder, item.subject), []).append(item)
    closed = 0
    for group in by_subject.values():
        group.sort(key=lambda item: (item.observed_at, item.item_id))
        for older, newer in pairwise(group):
            if older.valid_to is not None or older.observed_at >= newer.observed_at:
                continue
            if overlap(older.text, newer.text) >= OVERLAP_SUPERSEDE_LIMIT:
                continue
            older.valid_to = newer.observed_at
            closed += 1
    return closed


@dataclass(frozen=True)
class _ItemArrays:
    """Per-item columns, built once so a query never walks 400k Python objects."""

    holder_ids: dict[str, int]
    holders: np.ndarray
    sources: list[str]
    sources_of_item: np.ndarray
    valid_from: np.ndarray
    valid_to: np.ndarray


@dataclass
class Counterpart:
    """One counterpart store: the same items, the same embeddings, different memory semantics."""

    name: str
    temporal: bool
    items: list[MemoryItem]
    model_dir: Path
    cache_name: str = "counterpart-items"
    timings: list[float] = field(default_factory=list)
    _index: DenseIndex | None = None
    _arrays: _ItemArrays | None = None

    def __post_init__(self) -> None:
        """The store is cheap to build; embeddings are paid for on the first search."""

    def _ensure_arrays(self) -> _ItemArrays:
        if self._arrays is None:
            holder_ids = {holder: code for code, holder in enumerate(sorted({item.holder for item in self.items}))}
            ordered_sources = sorted({item.source_id for item in self.items})
            source_ids = {source: code for code, source in enumerate(ordered_sources)}
            self._arrays = _ItemArrays(
                holder_ids=holder_ids,
                holders=np.array([holder_ids[item.holder] for item in self.items], dtype=np.int32),
                sources=list(ordered_sources),
                sources_of_item=np.array([source_ids[item.source_id] for item in self.items], dtype=np.int32),
                valid_from=np.array([item.valid_from for item in self.items], dtype="U64"),
                valid_to=np.array([item.valid_to or "" for item in self.items], dtype="U64"),
            )
        return self._arrays

    def _ensure_index(self) -> DenseIndex:
        if self._index is None:
            self._index = DenseIndex(
                [Atom(atom_id=item.item_id, source_id=item.source_id, text=item.text) for item in self.items],
                self.model_dir,
                cache_name=self.cache_name,
            )
        return self._index

    def visible(self, holder: str | None, as_of: str | None) -> np.ndarray:
        """Which items this query may see.

        Both stores isolate by holder. Only the temporal store uses time: an item is hidden once
        a newer statement closed it, and hidden until it was observed. The flat store has no notion
        of as_of, which is exactly Mem0's behaviour and exactly what the comparison measures.
        """
        arrays = self._ensure_arrays()
        if holder is None:
            mask = np.ones(len(self.items), dtype=bool)
        else:
            mask = arrays.holders == arrays.holder_ids.get(holder, -1)
        if self.temporal and as_of is not None:
            mask &= arrays.valid_from <= as_of
            mask &= (arrays.valid_to == "") | (arrays.valid_to > as_of)
        return mask

    def search(self, query: str, holder: str | None, as_of: str | None, top_k: int = 10) -> list[str]:
        """Rank sources for one query, restricted to the items the query is allowed to see."""
        started = time.perf_counter()
        scores = self._ensure_index().scores(query, self.model_dir)
        mask = self.visible(holder, as_of)
        arrays = self._ensure_arrays()
        masked = np.where(mask, scores, -np.inf)
        ranked: list[str] = []
        seen: set[int] = set()
        for position in np.argsort(-masked, kind="stable"):
            if not np.isfinite(masked[position]):
                break
            code = int(arrays.sources_of_item[position])
            if code in seen:
                continue
            seen.add(code)
            ranked.append(arrays.sources[code])
            if len(ranked) == top_k:
                break
        self.timings.append(time.perf_counter() - started)
        return ranked

    def percentile(self, fraction: float) -> float:
        if not self.timings:
            raise SystemExit(f"{self.name}: no timings recorded")
        if not 0.0 <= fraction <= 1.0:
            raise SystemExit(f"percentile must be within [0, 1], got {fraction}")
        return float(np.percentile(np.asarray(self.timings), fraction * 100))


def build_counterparts(items: list[MemoryItem], models: Path = MODELS) -> list[Counterpart]:
    """Mem0-style first (no invalidation), then Zep-style (the same items, closed by time)."""
    model_dir = local_model_dir(models, DENSE_MODEL)
    if not model_dir.is_dir():
        raise SystemExit(f"{model_dir}: dense model missing, run python -m bench.fetch_models first")
    mem0 = Counterpart(name="mem0_flat", temporal=False, items=items, model_dir=model_dir)
    zep_items = [replace(item) for item in items]  # same order, same ids: only validity windows differ
    closed = supersede(zep_items)
    print(f"zep_temporal: closed {closed} items by supersession out of {len(zep_items)}")
    # Both stores share one embedding cache because the item sequence is identical; only visibility differs.
    zep = Counterpart(name="zep_temporal", temporal=True, items=zep_items, model_dir=model_dir)
    return [mem0, zep]
