"""Ask the store who knows something, then ask them.

The transactive rule this service implements: not knowing is fine when the directory knows
where to send you. Three things follow, and each one is a failure mode if left implicit.

- The directory is public, the content is not. `who_knows` counts every holder's matching
  memories, including memories the asker may not read, because "she knows" is the answer.
- A referral never invents an answer. If the asker may not read the holder's memories, the
  result is a pointer plus contact details, and the text stays where it is.
- Referral must terminate. Every hop records whom it asked, and the chain stops at the hop
  limit or when every candidate has been asked once.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from .config import Settings, get_settings
from .db import Database
from .holder_store import HolderStore, WhoKnowsCount
from .retrieval import RetrievalService
from .schemas import SearchFilters
from .text_index import index_text
from .transactive_schemas import (
    ReferralAnswer,
    WhoKnowsHit,
    WhoKnowsReport,
)

NO_HOLDER_KNOWS: Literal["no_holder_knows"] = "no_holder_knows"
LIBRARY = "library"
WHO_KNOWS_LIMIT = 8
MAX_HOPS_LIMIT = 10

# Confidence is ordinal: it orders candidates, it does not estimate a probability. The weights
# say what the evidence is worth relative to itself, and every hit carries the raw numbers too.
CONFIDENCE_SATURATE = 3
WEIGHT_STRENGTH = 0.60
WEIGHT_COVERAGE = 0.25
WEIGHT_DECLARED = 0.15


class TransactiveService:
    """who_knows and ask, built on the holder registry and the same retrieval as search."""

    def __init__(self, settings: Settings | None = None, database: Database | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = database or Database(self.settings)
        self.holders = HolderStore(self.db)
        self.retrieval = RetrievalService(self.settings, self.db)

    def who_knows(
        self, query: str, *, as_holder: str | None = None, limit: int = WHO_KNOWS_LIMIT
    ) -> WhoKnowsReport:
        """Rank the holders whose own memories answer this query.

        An empty result is the honest answer, not a fallback: nobody holds this, so the caller
        should say so instead of paraphrasing something unrelated.
        """
        if not query.strip():
            raise ValueError("who_knows needs a query")
        if limit <= 0:
            raise ValueError(f"who_knows needs a positive limit, got {limit}")
        counts = self.holders.who_knows_counts(query, limit)
        if not counts:
            return WhoKnowsReport(query=query, as_holder=as_holder, status=NO_HOLDER_KNOWS, hits=[])
        registered = {holder.holder_id: holder for holder in self.holders.list_holders()}
        best = max(count.top_score for count in counts)
        return WhoKnowsReport(
            query=query,
            as_holder=as_holder,
            status="found",
            hits=[
                self._hit(count, best, registered.get(count.holder_id), query)
                for count in counts
            ],
        )

    def ask(
        self,
        question: str,
        *,
        as_holder: str | None = None,
        max_hops: int = 3,
        include_text: bool = False,
    ) -> ReferralAnswer:
        """Answer a question by asking the asker first, then the directory's best candidates.

        `answered_by` is the asker when their own memory answered, `library` when an unowned
        artifact did, and the holder whose memory answered otherwise. `referred` means somebody
        knows but their memory is not readable by the asker.

        `max_hops` counts the holders asked besides the asker: the asker's own memory is hop 0,
        so max_hops=1 still asks the best candidate.
        """
        if not question.strip():
            raise ValueError("ask needs a question")
        if not 1 <= max_hops <= MAX_HOPS_LIMIT:
            raise ValueError(f"ask needs max_hops between 1 and {MAX_HOPS_LIMIT}, got {max_hops}")

        own = self._search(question, as_holder=as_holder, holder=None)
        if own:
            return self._answered(
                question, as_holder, asked=[as_holder or LIBRARY], hops=0, hits=own, include_text=include_text
            )

        asked: list[str] = [as_holder or LIBRARY]
        for hit in self.who_knows(question, as_holder=as_holder).hits:
            if hit.holder_id in asked:
                continue
            if len(asked) - 1 >= max_hops:
                break
            asked.append(hit.holder_id)
            readable = self._search(question, as_holder=as_holder, holder=hit.holder_id)
            if readable:
                return self._answered(
                    question,
                    as_holder,
                    asked=asked,
                    hops=len(asked) - 1,
                    hits=readable,
                    include_text=include_text,
                )
            return self._pointer(question, as_holder, asked, hit)
        return ReferralAnswer(
            question=question,
            as_holder=as_holder,
            status=NO_HOLDER_KNOWS,
            asked=asked,
            hops=len(asked) - 1,
            basis=["no holder has a memory that answers this"],
        )

    def _search(self, query: str, *, as_holder: str | None, holder: str | None):
        result = self.retrieval.search(
            query,
            top_k=5,
            filters=SearchFilters(holder=holder, as_holder=as_holder),
        )
        return result.hits

    def _answered(self, question, as_holder, *, asked, hops, hits, include_text) -> ReferralAnswer:
        """The hits already passed the visibility clause in SQL, so they may be shown."""
        top = hits[0]
        owner = top.atom.holder_id or LIBRARY
        return ReferralAnswer(
            question=question,
            as_holder=as_holder,
            status="answered",
            answered_by=owner,
            asked=asked,
            hops=hops,
            atom_ids=[hit.atom.atom_id for hit in hits],
            answer=top.atom.text if include_text else None,
            basis=[
                f"{len(hits)} memories readable by {as_holder or 'anyone'}",
                f"best match scores {top.final_score:.2f}",
                f"held by {owner}",
            ],
        )

    def _pointer(self, question, as_holder, asked, hit: WhoKnowsHit) -> ReferralAnswer:
        """The candidate knows but the asker cannot read it: return the contact, not the text."""
        contact = hit.contact
        return ReferralAnswer(
            question=question,
            as_holder=as_holder,
            status="referred",
            answered_by=hit.holder_id,
            asked=asked,
            hops=len(asked) - 1,
            basis=[
                f"{hit.holder_id} holds {hit.matched} matching memories the asker may not read",
                f"best match scores {hit.top_score:.2f}",
                f"reachable via {contact}" if contact else "no contact details registered",
            ],
        )

    def _hit(self, count: WhoKnowsCount, best: float, holder, query: str) -> WhoKnowsHit:
        declared = _declared_topics(holder.knows_about if holder else [], query)
        strength = count.top_score / best if best > 0 else 0.0
        coverage = min(1.0, count.matched / CONFIDENCE_SATURATE)
        confidence = (
            WEIGHT_STRENGTH * strength + WEIGHT_COVERAGE * coverage + WEIGHT_DECLARED * (1.0 if declared else 0.0)
        )
        basis = [
            f"holds {count.matched} matching memories",
            f"best match scores {count.top_score:.2f}",
        ]
        if count.latest_time:
            basis.append(f"most recent memory is from {count.latest_time}")
        if declared:
            basis.append(f"declared topics: {', '.join(declared)}")
        contact = dict(holder.contact) if holder else {}
        if contact:
            basis.append(f"reachable via {contact}")
        return WhoKnowsHit(
            holder_id=count.holder_id,
            name=holder.name if holder else "",
            confidence=round(confidence, 3),
            matched=count.matched,
            top_score=round(count.top_score, 3),
            latest_time=None if count.latest_time is None else _as_moment(count.latest_time),
            basis=basis,
            contact=contact,
        )


def _as_moment(value: str) -> datetime:
    """A stored timestamp that will not parse is a corrupt row, not a missing one."""
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"stored timestamp {value!r} is unreadable: {error}") from error


def _declared_topics(topics: list[str], query: str) -> list[str]:
    """Declared topics that share a searchable token with the query, using the index's own split."""
    query_tokens = set(index_text(query).split())
    if not query_tokens:
        return []
    return [topic for topic in topics if query_tokens & set(index_text(topic).split())]
