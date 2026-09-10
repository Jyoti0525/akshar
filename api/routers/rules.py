"""`/api/v1/rules` — the law behind a verdict. AKSHAR.md sections 15 and 11.

    "Retrieval exists to *show an officer the law behind a verdict*, nothing
     more."

This is tier 1 and it is deliberately small: the rulepack lists what is checked,
and `retrieval.citations` turns any `rule_ref` into the verbatim clause. A dict
lookup, under a millisecond, no model, no index, no network.

**Unauthenticated, following `/api/v1/rules` in `api/routers/ops.py`.** That
route publishes the rulepack on the stated ground that *"the argument for
rules-as-data is weakened by hiding them. There is nothing here that is not
already in a gazette."* Verbatim gazette text is the purest case of that, and
requiring a token to read the law while publishing the rule that applies it
would be incoherent. The list of rules stays where it is; this package adds only
the clause behind each one.

**Cacheable, because the gazette does not change between requests.** The
response carries a long `Cache-Control`, which is what lets the PWA hold tier 1
offline — §15: *"the whole corpus fits in browser memory, so the explainer can
work offline at tier L1."*
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from api.deps.resources import get_rulebook
from retrieval import search as tier2
from retrieval.citations import DOCUMENTS, Answer, Citation, load_index
from rules.loader import load_rulepack

router = APIRouter(prefix="/api/v1/rules", tags=["rules"])

CACHE_SECONDS = 86_400
"""A day. The gazette is amended by notification, not by the hour, and a stale
clause for a few hours is a far smaller problem than an officer with no clause
at all on a shop floor with one bar of signal.

Note that this is **not** the rulepack cache: a rulepack version bump must miss
every cached *verdict* (see `api/scanning._cache_lookup`), because a superseded
gazette produces a confident, legally wrong notice. Statute text carries no such
risk — it is quoted, not applied.
"""


def _citation(citation: Citation) -> dict[str, Any]:
    return {
        "ref": citation.ref,
        "document": citation.document,
        "heading": citation.heading,
        "text": citation.text,
        "page": citation.page,
        "kind": citation.kind,
        "parent_ref": citation.parent_ref,
        "source": citation.source,
        "read_as": citation.read_as,
        "quotable": citation.quotable,
        "caveat": citation.caveat,
    }


def _answer(answer: Answer) -> dict[str, Any]:
    """The wire shape, and `held` is the field that matters.

    A client must be able to tell "this is the clause" from "this is the
    provision around the clause" without parsing prose, so the distinction is a
    boolean rather than something inferred from whether `citation` is populated
    alongside `related`.
    """
    return {
        "ref": answer.ref,
        "held": answer.held,
        "citation": _citation(answer.citation) if answer.citation else None,
        "related": [_citation(item) for item in answer.related],
        "note": answer.note,
    }


@router.get("/citation")
async def citation_by_ref(
    response: Response,
    ref: Annotated[str, Query(min_length=1, max_length=200)],
) -> dict[str, Any]:
    """Resolve any citation string — the "why" button, in one call.

    Takes the `rule_ref` verbatim from a verdict, so a client never has to
    reformat a citation and no second vocabulary exists to drift.
    """
    response.headers["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    return _answer(load_index().resolve(ref))


@router.get("/search")
async def search_the_gazette(
    q: Annotated[str, Query(min_length=2, max_length=300)],
    limit: Annotated[int, Query(ge=1, le=25)] = tier2.DEFAULT_LIMIT,
    rulebook: Annotated[Any, Depends(get_rulebook)] = None,
) -> dict[str, Any]:
    """Tier 2 — free-text search across the gazette corpus. Section 15.

    **Declared before `/{rule_id}`**, because a path parameter would otherwise
    swallow `/search` and answer it as a lookup for a rule called "search".

    **Not cached.** The citation routes carry a day-long `Cache-Control`
    because a clause is the same clause tomorrow. A search result is a ranking,
    and re-indexing the corpus changes it; serving yesterday's ranking from a
    proxy would make an improved index invisible.
    """
    if rulebook is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Free-text search needs the rule corpus in Postgres. Tier 1 "
                "citation lookup is unaffected and still available at "
                "/api/v1/rules/citation."
            ),
        )

    result = tier2.search(
        q,
        lexical=rulebook.lexical,
        dense=rulebook.dense,
        fetch=rulebook.fetch,
        documents=DOCUMENTS,
        limit=limit,
    )
    return {
        "query": result.query,
        "considered": result.considered,
        "lexical_only": result.lexical_only,
        "note": result.note,
        "results": [
            {
                "ref": hit.ref,
                "doc_id": hit.doc_id,
                "document": hit.document,
                "heading": hit.heading,
                "text": hit.text,
                "page": hit.page,
                "kind": hit.kind,
                "source": hit.source,
                "read_as": hit.read_as,
                "quotable": hit.quotable,
                "caveat": hit.caveat,
                "score": round(hit.score, 6),
                "lexical_rank": hit.lexical_rank,
                "dense_rank": hit.dense_rank,
                "found_by_both": hit.found_by_both,
                # Offsets, never marked-up text. See `retrieval/highlight.py`:
                # the statute is returned exactly as held and the client draws
                # around it, so no renderer can alter a clause.
                "spans": [
                    {"start": sp.start, "end": sp.end, "term": sp.term}
                    for sp in hit.passage.spans
                ],
                "coverage": round(hit.passage.coverage, 3),
            }
            for hit in result.hits
        ],
    }


@router.get("/{rule_id}")
async def rule_detail(
    response: Response,
    rule_id: str,
) -> dict[str, Any]:
    """One rule of the pack, with the clause it rests on."""
    pack = load_rulepack()
    rule = next((r for r in pack.all_rules() if r.id == rule_id), None)
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No rule {rule_id!r} in the pack."
        )

    response.headers["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    return {
        "id": rule.id,
        "rule_ref": rule.rule_ref,
        "check": rule.check,
        "field": rule.field_name,
        "severity": rule.severity,
        "message": rule.message,
        "rulepack_version": pack.version_string,
        "law": _answer(load_index().resolve(rule.rule_ref)),
    }


__all__ = ["CACHE_SECONDS", "router"]
