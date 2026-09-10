"""Reciprocal Rank Fusion — tier 2's one piece of arithmetic. AKSHAR.md §15.

    "**Fusion:** Reciprocal Rank Fusion, `k=60`. No tuning, no learned weights,
     one line of SQL"

**Why fuse ranks and not scores.** BM25 returns an unbounded relevance figure
that depends on corpus statistics; cosine similarity returns a number in
[-1, 1]. They are not on the same scale, they are not on *a* scale, and any
attempt to combine them directly needs a normalisation constant that has to be
tuned against a labelled query set. §15 is explicit that no such set exists and
that building one is not this project. RRF ignores the scores entirely and uses
only the ordering, which is the one thing both retrievers agree on the meaning
of.

**Why hybrid at all**, from §15: *"Legal text is full of exact terms of art —
principal display panel, pre-packaged commodity, maximum permissible error.
Dense embeddings blur these; BM25 nails them."* A search for `principal display
panel` must return Rule 7, not a clause that is merely about labelling.

This module is deliberately pure. The lexical half runs in Postgres and the
dense half needs an ONNX session, but the fusion is arithmetic over two lists
of identifiers, so it is testable with no database, no model and no corpus.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

K = 60
"""The RRF constant, from §15, which takes it from the original Cormack et al.
formulation. It damps the contribution of the top rank so that one retriever
being confidently first does not automatically win: at k=60 the difference
between rank 1 and rank 2 is about 1.6%, while the difference between rank 1
and rank 60 is a factor of two. That is the property we want, because the two
retrievers disagree most at the top and agree most about the tail."""


@dataclass(frozen=True, slots=True)
class Fused:
    """One result, with enough provenance to explain why it ranked where it did.

    `lexical_rank` and `dense_rank` are kept rather than discarded because
    "found by both" and "found by one" are different kinds of answer, and an
    officer's trust in a search depends on being able to see which happened.
    """

    key: str
    score: float
    lexical_rank: int | None = None
    dense_rank: int | None = None

    @property
    def found_by_both(self) -> bool:
        return self.lexical_rank is not None and self.dense_rank is not None


def fuse(
    lexical: Sequence[str],
    dense: Sequence[str],
    *,
    k: int = K,
    limit: int | None = None,
) -> list[Fused]:
    """Combine two ranked lists of chunk keys into one.

    Each list contributes `1 / (k + rank)` per key, ranks being 1-based. A key
    in only one list still scores; it simply scores less than it would had both
    retrievers found it. That is the intended behaviour and not a fallback —
    BM25 alone is the right answer for an exact term of art that the embedding
    blurs, and the dense half alone is the right answer for a question phrased
    in words the statute never uses.

    Ties are broken by the better of the two ranks, then by key, so the order
    is total and repeatable. A search that returns results in a different order
    on a second run is indistinguishable from a broken one.
    """
    scores: dict[str, float] = {}
    lexical_at: dict[str, int] = {}
    dense_at: dict[str, int] = {}

    for rank, key in enumerate(lexical, start=1):
        if key in lexical_at:  # a retriever must not vote twice
            continue
        lexical_at[key] = rank
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)

    for rank, key in enumerate(dense, start=1):
        if key in dense_at:
            continue
        dense_at[key] = rank
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)

    fused = [
        Fused(
            key=key,
            score=score,
            lexical_rank=lexical_at.get(key),
            dense_rank=dense_at.get(key),
        )
        for key, score in scores.items()
    ]
    fused.sort(
        key=lambda item: (
            -item.score,
            min(
                item.lexical_rank or len(lexical) + 1,
                item.dense_rank or len(dense) + 1,
            ),
            item.key,
        )
    )
    return fused[:limit] if limit is not None else fused


def rank_of(fused: Iterable[Fused], key: str) -> int | None:
    """1-based position of `key`, or None. For tests and for explaining a result."""
    for position, item in enumerate(fused, start=1):
        if item.key == key:
            return position
    return None


__all__ = ["Fused", "K", "fuse", "rank_of"]
