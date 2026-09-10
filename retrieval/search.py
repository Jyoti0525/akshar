"""Tier 2 orchestration — BM25 and dense, fused, then marked up. AKSHAR.md §15.

    | **2. Hybrid search** | Officer types a free-text question | BM25 + dense,
      fused | ~40 ms |

**No SQLAlchemy here, on purpose.** The lexical half is a Postgres query and
the dense half needs an ONNX session, but this module takes both as callables.
It is the same discipline `tests/test_boundaries.py` enforces on `vision/`:
*"Extraction owns no connections [...] that keeps the whole pipeline runnable
in a unit test, and it is what lets the identical code run in a browser where
there is no Postgres."* Tier 2 has exactly the same future — §15 wants the
corpus searchable offline — so it is worth not conceding here.

**Degradation is reported, not hidden.** With no embedder the dense list is
empty, RRF still works, and the result is honest BM25. The caller is told,
because "search found nothing relevant" and "search ran at half strength" are
different things and only one of them is the officer's problem.

**Tier 2 hands off to tier 1, never around it.** A hit's `key` is the tier-1
lookup key, so the clause a search surfaces is the same object the "why" button
resolves. There is no second path by which a citation could mean something
different.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from retrieval import highlight, provenance
from retrieval.hybrid import Fused, K, fuse

DEFAULT_LIMIT = 10
CANDIDATES = 50
"""How deep each retriever goes before fusion.

Fusing only the top 10 of each would throw away the case RRF exists for: a
clause ranked 1st by BM25 and 30th by the embedding is usually the right
answer, and it is invisible if the dense list stops at 10. Fifty is cheap
against a 5,172-row sequential scan and deep enough that the two lists overlap.
"""


@dataclass(frozen=True, slots=True)
class Hit:
    """One retrieved clause, with why it ranked and how far to trust its text."""

    key: str
    doc_id: str
    ref: str
    document: str
    heading: str
    text: str
    page: int
    kind: str
    read_as: str
    score: float
    lexical_rank: int | None
    dense_rank: int | None
    passage: highlight.Passage

    @property
    def found_by_both(self) -> bool:
        return self.lexical_rank is not None and self.dense_rank is not None

    @property
    def quotable(self) -> bool:
        return self.read_as in provenance.QUOTABLE

    @property
    def caveat(self) -> str:
        return provenance.describe(self.read_as)

    @property
    def source(self) -> str:
        """The citation line a report prints, matching `citations.Citation`."""
        return f"{self.document}, page {self.page}"


@dataclass(frozen=True, slots=True)
class SearchResult:
    query: str
    hits: tuple[Hit, ...] = ()
    lexical_only: bool = False
    note: str = ""
    considered: int = 0
    _fused: tuple[Fused, ...] = field(default=(), repr=False)

    def __len__(self) -> int:
        return len(self.hits)


def search(
    query: str,
    *,
    lexical: Callable[[str, int], Sequence[str]],
    dense: Callable[[str, int], Sequence[str]] | None,
    fetch: Callable[[Sequence[str]], Mapping[str, Mapping[str, object]]],
    documents: Mapping[str, str] | None = None,
    limit: int = DEFAULT_LIMIT,
    candidates: int = CANDIDATES,
    k: int = K,
) -> SearchResult:
    """Run tier 2 and return marked-up clauses, best first.

    `dense=None` is the degraded mode, not an error — see the module docstring.
    """
    query = query.strip()
    if not query:
        return SearchResult(query=query, note="No question was asked.")

    lexical_keys = list(lexical(query, candidates))
    dense_keys = list(dense(query, candidates)) if dense is not None else []

    fused = fuse(lexical_keys, dense_keys, k=k, limit=limit)
    rows = fetch([item.key for item in fused])

    hits: list[Hit] = []
    for item in fused:
        row = rows.get(item.key)
        if row is None:
            # The index and the table disagree — a row deleted between the two
            # queries. Skipping is right: returning a citation with no text is
            # worse than returning one fewer result.
            continue
        text = str(row.get("text", ""))
        doc_id = str(row.get("doc_id", ""))
        hits.append(
            Hit(
                key=item.key,
                doc_id=doc_id,
                ref=str(row.get("ref", "")),
                document=(documents or {}).get(doc_id, doc_id),
                heading=str(row.get("heading", "")),
                text=text,
                page=int(row.get("page", 0) or 0),
                kind=str(row.get("kind", "")),
                read_as=str(row.get("source", provenance.TEXT_LAYER)),
                score=item.score,
                lexical_rank=item.lexical_rank,
                dense_rank=item.dense_rank,
                passage=highlight.passage(text, query),
            )
        )

    degraded = dense is None
    return SearchResult(
        query=query,
        hits=tuple(hits),
        lexical_only=degraded,
        note=(
            "No embedding model is loaded, so this is a keyword search only. "
            "Exact terms of art will still be found; a question phrased in "
            "words the statute does not use may not be."
            if degraded
            else ""
        ),
        considered=len({*lexical_keys, *dense_keys}),
        _fused=tuple(fused),
    )


__all__ = ["CANDIDATES", "DEFAULT_LIMIT", "Hit", "SearchResult", "search"]
