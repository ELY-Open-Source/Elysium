"""Retrieval: SQLite FTS5 does the matching, RRF merges the signals that exist.

The first version pulled every atom into Python and rebuilt a BM25 index per query, so search
cost grew with the corpus instead of with the answer, and a Chinese query matched nothing
because the tokenizer had no CJK rule. Both are fixed below the score line: the index and the
query share `text_index`, and the ranking is a SQL query.
"""

from __future__ import annotations

import base64
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from . import cartridge_store, lifecycle_store
from .config import Settings, get_settings
from .db import Database
from .embeddings import EmbeddingService
from .schemas import EvidenceAtom, RetrievalHit, SearchFilters, SearchResult, utc_now
from .store_search import FtsPage, search_atoms
from .vector_index import VectorIndex
from .visual_index import VisualIndex

RRF_K = 60
CANDIDATE_WINDOW = 10
# Words decide most searches; a picture vector is only worth its encoding cost when words fell short.
THIN_SPARSE_PAGE = 2


class RetrievalService:
    def __init__(self, settings: Settings | None = None, database: Database | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = database or Database(self.settings)
        self.embeddings = EmbeddingService(self.settings, self.db)
        self.vectors = VectorIndex(self.settings, self.db, self.embeddings)
        self.visual = VisualIndex(self.settings, self.db)

    def search(
        self,
        query: str,
        top_k: int | None = None,
        *,
        filters: SearchFilters | None = None,
        cursor: str | None = None,
        image: Path | None = None,
    ) -> SearchResult:
        """Answer one query against the memories that are open right now.

        The candidate window is wider than the page so fusion has something to fuse; the cursor
        advances one page at a time and re-reads the tail of the window it came from, which is
        why no result is ever skipped between pages.
        """
        limit = top_k or self.settings.retrieval_top_k
        if limit <= 0:
            raise ValueError(f"search needs a positive limit, got {limit}")
        if not query.strip() and image is None:
            raise ValueError("search needs words or a picture to ask with, and got neither")
        offset = decode_cursor(cursor)
        criteria = (filters or SearchFilters()).model_dump(exclude_none=True)
        scope = criteria.get("cartridge_ids")
        if scope is None:
            scope = cartridge_store.mounted_ids(self.db) or None
        criteria["cartridge_ids"] = scope
        # A picture-only question has no words for BM25, so the word ranking is skipped rather than matching an empty expression.
        page = (
            search_atoms(self.db, query, limit=limit * CANDIDATE_WINDOW, offset=offset, **criteria)
            if query.strip()
            else FtsPage(rows=[], has_more=False)
        )
        rankings: list[list[str]] = [[atom_id for atom_id, _ in page.rows]]
        scores: dict[str, dict[str, float]] = defaultdict(dict)
        for atom_id, bm25 in page.rows:
            scores[atom_id]["sparse_score"] = bm25
        if self.embeddings.enabled():
            dense = self._dense_search(query, limit * CANDIDATE_WINDOW, criteria)
            rankings.append(list(dense))
            for atom_id, cosine in dense.items():
                scores[atom_id]["dense_score"] = cosine
        visual = self._visual_search(
            query,
            image,
            limit * CANDIDATE_WINDOW,
            scope,
            thin=len(rankings[0]) < limit * THIN_SPARSE_PAGE,
        )
        if visual:
            rankings.append(list(visual))
            for atom_id, cosine in visual.items():
                scores[atom_id]["visual_score"] = cosine
        hits = self._settle_conflicts(self._rank(rankings, scores, limit * CANDIDATE_WINDOW))[:limit]
        lifecycle_store.touch_recalls(self.db, [hit.atom.atom_id for hit in hits], utc_now())
        more = page.has_more or len(rankings[0]) > limit
        return SearchResult(
            query=query,
            status="hits" if hits else "no_match",
            hits=hits,
            next_cursor=encode_cursor(offset + limit) if hits and more else None,
        )

    def _dense_search(self, query: str, limit: int, criteria: dict[str, Any]) -> dict[str, float]:
        """The vectors sit beside the atoms, so a memory written a moment ago is findable.

        Every filter is applied inside the engine, in the same statement as the nearest-neighbour
        walk, so a scoped search cannot return a memory the caller was never allowed to see. The
        index catches up inside `search`, so nothing here has to rebuild it first.
        """
        query_vector = self.embeddings.embed_query(query)
        return self.vectors.search(
            query_vector,
            limit,
            holder=criteria.get("holder"),
            scenario=criteria.get("scenario"),
            source_id=criteria.get("source_id"),
            modality=criteria.get("modality"),
            since=_text(criteria.get("since")),
            until=_text(criteria.get("until")),
            cartridge_ids=criteria.get("cartridge_ids"),
            as_holder=criteria.get("as_holder"),
        )

    def _visual_search(
        self,
        query: str,
        image: Path | None,
        limit: int,
        scope: list[str] | None,
        *,
        thin: bool,
    ) -> dict[str, float]:
        """Ask the picture index when words are not enough.

        A screenshot with no text on it has nothing for FTS to match, so the sparse page comes
        back short; that is the signal to spend the encoding. An image query always asks for it.
        """
        if image is None and not thin:
            return {}
        if not self.visual.available() or self.visual.load() is None:
            return {}
        if image is not None:
            try:
                ranked = self.visual.search_image(image, limit)
            except (OSError, ValueError) as error:
                raise ValueError(f"the query image {image} cannot be read: {error}") from error
        else:
            ranked = self.visual.search_text(query, limit)
        if scope:
            allowed = cartridge_store.atoms_of_cartridges(self.db, scope)
            ranked = [(atom_id, score) for atom_id, score in ranked if atom_id in allowed]
        return dict(ranked)

    def _rank(self, rankings: list[list[str]], scores: dict[str, dict[str, float]], limit: int) -> list[RetrievalHit]:
        """Reciprocal rank fusion: rank position is comparable across signals, raw scores are not.

        The old blend multiplied BM25 by 0.55 and cosine by 0.35, which compared a term-frequency
        count to a bounded cosine and let the larger number decide. graph_score stays 0.0 until
        evidence edges are retrieved as their own ranking.
        """
        fused: dict[str, float] = {}
        for ranking in rankings:
            for position, atom_id in enumerate(ranking):
                fused[atom_id] = fused.get(atom_id, 0.0) + 1.0 / (RRF_K + position + 1)
        order = sorted(fused, key=lambda atom_id: (-fused[atom_id], atom_id))[:limit]
        atoms = {atom.atom_id: atom for atom in self.db.get_atoms(order)}
        hits: list[RetrievalHit] = []
        for atom_id in order:
            atom = atoms.get(atom_id)
            if atom is None:
                raise ValueError(f"search returned {atom_id} but the atom is not in the store")
            signal = scores.get(atom_id, {})
            hits.append(
                RetrievalHit(
                    atom=atom,
                    sparse_score=signal.get("sparse_score", 0.0),
                    dense_score=signal.get("dense_score", 0.0),
                    visual_score=signal.get("visual_score", 0.0),
                    final_score=fused[atom_id],
                )
            )
        return hits

    def _settle_conflicts(self, hits: list[RetrievalHit]) -> list[RetrievalHit]:
        """Drop the older side of a disagreement nobody settled, so one page cannot contradict itself.

        Both memories stay in the store and this only filters the page; the conflict row names
        which side was dropped and why. Settling is the holder's call, and until it happens the
        newer statement is what a reader should be shown. Only a pair seen whole is settled: the
        page is ranked from a window wider than itself, so both sides normally arrive together,
        and an answer that never recalled the newer memory leaves the older value standing —
        stale, but not silently contradicted by nothing.
        """
        losers = lifecycle_store.losing_sides(self.db, [hit.atom.atom_id for hit in hits])
        if not losers:
            return hits
        return [hit for hit in hits if hit.atom.atom_id not in losers]

    def recall(self, query: str, top_k: int | None = None, *, filters: SearchFilters | None = None) -> list[EvidenceAtom]:
        """The atoms a search would put in front of a model, no scoring attached."""
        return [hit.atom for hit in self.search(query, top_k, filters=filters).hits]


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


def decode_cursor(cursor: str | None) -> int:
    if cursor is None or cursor == "":
        return 0
    try:
        offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError(f"search cursor is unreadable: {cursor!r}") from error
    if offset < 0:
        raise ValueError(f"search cursor is unreadable: {cursor!r}")
    return offset


def _text(moment: datetime | None) -> str | None:
    """A time bound reaches SQLite as the same ISO text the atoms table stores."""
    return None if moment is None else moment.isoformat()
