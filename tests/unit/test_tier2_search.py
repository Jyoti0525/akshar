"""Tier 2 and tier 3 — AKSHAR.md section 15.

    "**Fusion:** Reciprocal Rank Fusion, `k=60`. No tuning, no learned weights"
    "**Default: extractive, not generative.** Display the verbatim gazette text
     with the matched span highlighted. No model writes anything."

Tier 1 is correct by construction — a citation is a dictionary key. Tier 2 is a
*ranking*, which cannot be correct or incorrect in the same way, so the tests
here pin the properties that make a ranking trustworthy rather than asserting a
particular order:

- it is deterministic, because a search that reorders between runs is
  indistinguishable from a broken one;
- a clause found by both retrievers outranks one found by either alone;
- it degrades to lexical-only *and says so*;
- and the statute survives tier 3 byte for byte.

The last would matter in a hearing. The others are quality; that one is
integrity.
"""

from __future__ import annotations

import os

import pytest

from retrieval import highlight, search
from retrieval.hybrid import K, fuse, rank_of

# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------


def test_a_clause_both_retrievers_found_outranks_one_either_found_alone():
    """The entire reason for hybrid search, as one assertion."""
    fused = fuse(lexical=["both", "lex-only"], dense=["dense-only", "both"])

    assert fused[0].key == "both"
    assert fused[0].found_by_both


def test_a_clause_only_one_retriever_found_still_scores():
    """§15 keeps BM25 *because* it finds exact terms of art the embedding
    blurs. A term found only lexically must not be discarded for it."""
    fused = fuse(lexical=["principal-display-panel"], dense=["something-else"])

    assert rank_of(fused, "principal-display-panel") is not None
    assert not fused[0].found_by_both


def test_fusion_uses_ranks_and_not_scores():
    """RRF's contribution depends only on position, so the same ordering fuses
    identically whatever the retrievers' raw scores were. That is what lets
    BM25 and cosine — which share no scale — be combined at all."""
    assert fuse(["a", "b"], ["b", "a"])[0].score == pytest.approx(
        1.0 / (K + 1) + 1.0 / (K + 2)
    )


def test_fusion_is_deterministic_including_ties():
    """`a` and `c` here score identically. Ordering must still be total."""
    first = [item.key for item in fuse(["a", "b", "c"], ["c", "d", "a"])]
    second = [item.key for item in fuse(["a", "b", "c"], ["c", "d", "a"])]

    assert first == second
    assert first[:2] == ["a", "c"]


def test_a_retriever_cannot_vote_twice():
    """A duplicate key in one list would otherwise score as though two
    retrievers had agreed."""
    assert fuse(["x", "x"], [])[0].score == fuse(["x"], [])[0].score


def test_an_empty_dense_list_is_a_valid_search():
    """The no-model path: it must produce a ranking, not an error."""
    fused = fuse(["a", "b"], [])

    assert [item.key for item in fused] == ["a", "b"]
    assert fused[0].dense_rank is None


# ---------------------------------------------------------------------------
# Tier 3 — extractive
# ---------------------------------------------------------------------------

CLAUSE = (
    "7. Printing:(1) Symbols of units- (b) Shall remain unaltered in the plural; "
    "(c) Shall be written, without a final full stop (period) unless the context "
    "otherwise requires"
)


def test_the_statute_survives_highlighting_byte_for_byte():
    """**The integrity test.** Tier 3 returns offsets, never a rewritten
    string, so reassembling the segments must reproduce the clause exactly. A
    highlighter that could alter statute would be the only component in this
    system permitted to do so."""
    marked = highlight.passage(CLAUSE, "unit symbols plural full stop")

    assert "".join(text for text, _ in highlight.segments(marked)) == CLAUSE


def test_a_matched_span_points_at_the_word_it_claims():
    marked = highlight.passage(CLAUSE, "plural")

    assert [span.slice(CLAUSE).lower() for span in marked.spans] == ["plural"]


def test_matching_is_case_folded_and_tolerates_a_plural():
    """`symbols` in the gazette answers a question about a `symbol`."""
    marked = highlight.passage(CLAUSE, "what is a unit Symbol")

    assert "symbols" in {span.slice(CLAUSE).lower() for span in marked.spans}


def test_matching_is_not_stemming():
    """A stemmer conflates `packing` and `packaged`, which the Packaged
    Commodities Rules use to mean different things — the packing date of
    Rule 6(1)(d) is not the pre-packed commodity of Rule 2(l)."""
    assert highlight.passage("the packing date shall be declared", "packaged").spans == ()


def test_common_words_are_not_marked():
    """Highlighting every `the` highlights the clause, which is the same as
    highlighting nothing."""
    marked = highlight.passage(CLAUSE, "the of and in")

    assert marked.spans == ()
    assert marked.coverage == 0.0


def test_coverage_reports_how_much_of_the_question_was_met():
    marked = highlight.passage(CLAUSE, "symbols plural aeroplane")

    assert set(marked.matched_terms) == {"symbols", "plural"}
    assert marked.coverage == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

ROWS: dict[str, dict[str, object]] = {
    "lmpc_2011::rule 7": {
        "doc_id": "lmpc_2011",
        "ref": "Rule 7",
        "heading": "Principal display panel",
        "text": "Every package shall bear a principal display panel.",
        "page": 8,
        "kind": "rule",
        "source": "text-layer",
    },
    "ns_rules_2011::third schedule, item 7": {
        "doc_id": "ns_rules_2011",
        "ref": "Third Schedule, item 7",
        "heading": "Printing",
        "text": CLAUSE,
        "page": 68,
        "kind": "clause",
        "source": "ocr",
    },
}


def _fetch(keys):
    return {key: ROWS[key] for key in keys if key in ROWS}


def test_a_hit_carries_the_key_tier_one_would_have_used():
    """Tier 2 hands off to tier 1 rather than around it: the clause a search
    surfaces is the same object the "why" button resolves."""
    result = search.search(
        "principal display panel",
        lexical=lambda q, n: ["lmpc_2011::rule 7"],
        dense=lambda q, n: [],
        fetch=_fetch,
    )

    assert result.hits[0].key == "lmpc_2011::rule 7"
    assert result.hits[0].ref == "Rule 7"


def test_search_without_an_embedder_says_it_ran_at_half_strength():
    """"Found nothing relevant" and "ran without half its machinery" are
    different facts, and only one of them is the officer's problem."""
    result = search.search(
        "principal display panel",
        lexical=lambda q, n: ["lmpc_2011::rule 7"],
        dense=None,
        fetch=_fetch,
    )

    assert result.lexical_only
    assert "keyword search only" in result.note
    assert len(result) == 1


def test_a_hit_read_off_a_scan_is_marked_unquotable():
    result = search.search(
        "unit symbols plural",
        lexical=lambda q, n: ["ns_rules_2011::third schedule, item 7"],
        dense=lambda q, n: [],
        fetch=_fetch,
    )

    hit = result.hits[0]
    assert hit.read_as == "ocr"
    assert not hit.quotable
    assert "Verify against the page" in hit.caveat


def test_a_ranked_key_with_no_row_is_dropped_not_rendered_empty():
    """The ranking and the table can disagree if a row is removed between the
    two queries. One fewer result beats a citation with no text under it."""
    result = search.search(
        "anything",
        lexical=lambda q, n: ["gone::rule 1", "lmpc_2011::rule 7"],
        dense=lambda q, n: [],
        fetch=_fetch,
    )

    assert [hit.key for hit in result.hits] == ["lmpc_2011::rule 7"]


def test_an_empty_question_is_not_a_search():
    result = search.search("   ", lexical=lambda q, n: [], dense=None, fetch=_fetch)

    assert len(result) == 0
    assert "No question" in result.note


def test_hits_are_marked_up_against_the_question_that_found_them():
    result = search.search(
        "unit symbols in the plural",
        lexical=lambda q, n: ["ns_rules_2011::third schedule, item 7"],
        dense=lambda q, n: [],
        fetch=_fetch,
    )

    hit = result.hits[0]
    assert hit.passage.spans
    assert "".join(t for t, _ in highlight.segments(hit.passage)) == hit.text


# ---------------------------------------------------------------------------
# Against the real corpus in Postgres
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("AKSHAR_TEST_DATABASE_URL")

pg = pytest.mark.skipif(
    not DATABASE_URL, reason="set AKSHAR_TEST_DATABASE_URL to search the real corpus"
)


@pytest.fixture(scope="module")
def rulebook():
    from sqlalchemy import create_engine

    from api.sql.rulebook import SqlRulebook

    book = SqlRulebook(create_engine(DATABASE_URL, future=True))
    rows, _ = book.counts()
    if rows == 0:
        pytest.skip("rule_chunks is empty; run scripts/index_corpus.py")
    return book


@pg
def test_the_corpus_is_loaded_with_a_vector_for_every_row(rulebook):
    rows, vectors = rulebook.counts()

    assert rows > 4000
    assert vectors == rows, "every chunk should carry an embedding after indexing"


@pg
def test_an_exact_term_of_art_is_found(rulebook):
    """§15's stated reason for keeping BM25: *principal display panel* must
    return the rule that uses the phrase, not something merely about labels."""
    result = search.search(
        "principal display panel",
        lexical=rulebook.lexical,
        dense=rulebook.dense,
        fetch=rulebook.fetch,
        limit=5,
    )

    assert result.hits
    assert any("principal display panel" in hit.text.lower() for hit in result.hits)


@pg
def test_a_question_in_words_the_statute_never_uses_still_finds_a_clause(rulebook):
    """The dense half earning its place: no gazette says "how big must the
    letters be"."""
    result = search.search(
        "how big must the letters on a package be",
        lexical=rulebook.lexical,
        dense=rulebook.dense,
        fetch=rulebook.fetch,
        limit=10,
    )

    assert result.hits
    assert any(hit.dense_rank is not None for hit in result.hits)


@pg
def test_a_query_postgres_would_choke_on_is_answered_not_five_hundred(rulebook):
    """`to_tsquery` raises a syntax error on ordinary punctuation, and this
    endpoint takes an officer's free text, so `websearch_to_tsquery` is not a
    stylistic preference."""
    assert rulebook.lexical("what is the MRP? (net quantity!)", 5) is not None
