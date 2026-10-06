"""Retrieval metrics with no model and no dependency: recall@k, MRR, nDCG@10, Wilson bounds.

Rankings are lists of source ids; gold is the set of source ids a third party marked
correct. Unanswerable queries carry an empty gold set, so they are scored by abstention
behaviour instead of recall, and never mixed into the recall denominator.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

Z_TWO_SIDED_95 = 1.959963984540054


@dataclass(frozen=True)
class QueryScore:
    query_id: str
    answerable: bool
    gold: int
    recall_at_1: float
    recall_at_5: float
    recall_at_10: float
    ndcg_at_10: float
    mrr: float
    first_hit_rank: int | None
    abstained: bool
    top_hit_from_holder: bool | None


def recall_at_k(ranked: Sequence[str], gold: set[str], k: int) -> float:
    """Fraction of gold sources inside the first k results; 0.0 when gold is empty."""
    if not gold:
        return 0.0
    return len(gold & set(ranked[:k])) / len(gold)


def reciprocal_rank(ranked: Sequence[str], gold: set[str]) -> float:
    for position, source_id in enumerate(ranked, start=1):
        if source_id in gold:
            return 1.0 / position
    return 0.0


def first_hit_rank(ranked: Sequence[str], gold: set[str]) -> int | None:
    for position, source_id in enumerate(ranked, start=1):
        if source_id in gold:
            return position
    return None


def ndcg_at_10(ranked: Sequence[str], gold: set[str]) -> float:
    """Binary-relevance nDCG@10; 0.0 when gold is empty."""
    if not gold:
        return 0.0
    dcg = sum(
        1.0 / math.log2(position + 1)
        for position, source_id in enumerate(ranked[:10], start=1)
        if source_id in gold
    )
    ideal = sum(1.0 / math.log2(position + 1) for position in range(1, min(len(gold), 10) + 1))
    return dcg / ideal


def wilson_lower_bound(successes: int, trials: int, z: float = Z_TWO_SIDED_95) -> float:
    """One number: the lower end of the Wilson score interval for a binomial proportion."""
    if trials <= 0:
        raise SystemExit(f"wilson needs a positive trial count, got {trials}")
    if not 0 <= successes <= trials:
        raise SystemExit(f"wilson needs 0 <= {successes} <= {trials}")
    rate = successes / trials
    denominator = 1.0 + z * z / trials
    centre = rate + z * z / (2 * trials)
    spread = z * math.sqrt((rate * (1.0 - rate) + z * z / (4 * trials)) / trials)
    return max(0.0, (centre - spread) / denominator)


def chance_recall_at_k(gold: int, corpus_size: int, k: int) -> float:
    """Expected recall@k for a uniformly random ranking: k/N, whatever the gold count.

    A random top-k holds a k/N share of every subset, so the share of gold found does not
    depend on how many sources are gold; gold only decides whether the question is answerable.
    """
    if corpus_size <= 0:
        raise SystemExit(f"chance needs a positive corpus size, got {corpus_size}")
    if gold <= 0:
        return 0.0
    return min(1.0, k / corpus_size)


def score_query(
    query_id: str,
    ranked: Sequence[str],
    gold: set[str],
    holder: str | None = None,
    holder_of: dict[str, str] | None = None,
) -> QueryScore:
    """Score one query; abstention is only defined when the system can signal no_match."""
    abstained = not ranked
    top_holder = None
    if holder_of is not None and ranked:
        top_holder = holder_of.get(ranked[0])
    return QueryScore(
        query_id=query_id,
        answerable=bool(gold),
        gold=len(gold),
        recall_at_1=recall_at_k(ranked, gold, 1),
        recall_at_5=recall_at_k(ranked, gold, 5),
        recall_at_10=recall_at_k(ranked, gold, 10),
        ndcg_at_10=ndcg_at_10(ranked, gold),
        mrr=reciprocal_rank(ranked, gold),
        first_hit_rank=first_hit_rank(ranked, gold),
        abstained=abstained,
        top_hit_from_holder=None if holder is None else top_holder == holder,
    )


def aggregate(scores: Sequence[QueryScore]) -> dict[str, float | int]:
    """Mean metrics over answerable queries plus abstention over unanswerable ones."""
    answerable = [score for score in scores if score.answerable]
    unanswerable = [score for score in scores if not score.answerable]
    if not answerable:
        raise SystemExit("aggregate needs at least one answerable query")

    def mean(field: str) -> float:
        return sum(getattr(score, field) for score in answerable) / len(answerable)

    hits_10 = sum(1 for score in answerable if score.recall_at_10 > 0.0)
    holder_known = [score for score in unanswerable if score.top_hit_from_holder is not None]
    return {
        "n_answerable": len(answerable),
        "n_unanswerable": len(unanswerable),
        "recall_at_1": mean("recall_at_1"),
        "recall_at_5": mean("recall_at_5"),
        "recall_at_10": mean("recall_at_10"),
        "ndcg_at_10": mean("ndcg_at_10"),
        "mrr": mean("mrr"),
        "hit_at_10": hits_10 / len(answerable),
        "hit_at_10_wilson_lower": wilson_lower_bound(hits_10, len(answerable)),
        "abstention_rate_answerable": sum(1 for s in answerable if s.abstained) / len(answerable),
        "abstention_rate_unanswerable": (
            sum(1 for s in unanswerable if s.abstained) / len(unanswerable) if unanswerable else 0.0
        ),
        "wrong_holder_confidence_unanswerable": (
            sum(1 for s in holder_known if s.top_hit_from_holder) / len(holder_known)
            if holder_known
            else 0.0
        ),
    }
