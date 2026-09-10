"""Tier-1 retrieval — AKSHAR.md section 15.

    "Tier 1 covers the overwhelming majority of use. [...] Build it first; it is
     an afternoon's work and it is the feature officers will actually use."

The value of this feature is entirely that **no model wrote the answer**. So the
tests are about the ways a lookup can be confidently wrong, every one of which
this file has actually caught in the code below it:

- **the wrong Rule 7.** The gazette's Sixth Schedule numbers its items from 1
  again, so its item 7 ("Checking of other declarations") overwrote the real
  Rule 7 (principal display panel, area, size and letter) — the rule behind
  every height check we make.
- **a proviso eating the rest of the rule.** A new sub-rule must close an open
  proviso. Requiring otherwise silently dropped eight sub-rules, including
  Rule 18(5) — the retailer's offence.
- **a sub-rule that hid behind a footnote marker.** The gazette prints `*(6)`,
  and a pattern without the asterisk made Rule 12(6) disappear.
- **a near miss served as an answer.** `Rule 7(2)` must never quietly resolve to
  `Rule 7`.

The last one is the discipline the whole module is built around, and it is why
`Answer.held` is a boolean rather than something a caller infers.
"""

from __future__ import annotations

import re
from collections import Counter

import pytest

from retrieval.chunker import Chunk, chunk_document, restore_roman_markers
from retrieval.citations import RULEBOOK_DIR, CitationIndex, load_index
from retrieval.normalise import (
    repair_spacing,
    restore_ascii_punctuation,
    strip_page_furniture,
    tidy,
    vocabulary,
)
from rules.loader import load_rulepack


@pytest.fixture(scope="module")
def index() -> CitationIndex:
    return load_index()


# ---------------------------------------------------------------------------
# Repairing the PDF's spacing without editing the law
# ---------------------------------------------------------------------------


def test_a_split_word_is_rejoined_when_the_document_itself_says_so():
    text = "the decl aration and the decl aration and declaration declaration declaration"
    fixed, repairs = repair_spacing(text, vocabulary(text))

    assert "declaration" in fixed
    assert "decl aration" not in fixed
    assert repairs == 2


def test_two_ordinary_words_are_never_glued_together():
    """`of fice` must survive as two words when `of` is the commoner token.

    The repair may only restore a word the document already uses *and* only
    when the evidence says the fragments are debris. Getting this wrong would
    silently alter statute.
    """
    text = "of of of of of office in the of fice"
    fixed, _ = repair_spacing(text, vocabulary(text))

    assert "of fice" in fixed


def test_a_word_the_corpus_never_uses_is_never_invented():
    text = "any where any where any where"
    fixed, repairs = repair_spacing(text, vocabulary(text))

    assert fixed == text
    assert repairs == 0


def test_the_repair_examines_pairs_it_has_already_scanned_past():
    """The bug the lookahead exists for.

    Consuming both fragments means "the decl" is tested, rejected, and the scan
    resumes *after* "decl" — so "decl aration" is never examined. Every artefact
    preceded by a short ordinary word was invisible.
    """
    text = "in the decl aration " * 3 + "declaration declaration declaration declaration"
    fixed, repairs = repair_spacing(text, vocabulary(text))

    assert repairs == 3
    assert "decl aration" not in fixed


def test_page_numbers_survive_and_page_furniture_does_not():
    lines = ["<<<PAGE 9>>>", "(1) Every declaration", "Page 9 of 43", "shall appear."]

    kept = strip_page_furniture(lines)

    assert [page for page, _ in kept] == [9, 9]
    assert [text for _, text in kept] == ["(1) Every declaration", "shall appear."]


def test_tidy_collapses_the_wrapping_and_nothing_else():
    assert tidy("shall  not\nbe  less   than") == "shall not be less than"


# ---------------------------------------------------------------------------
# Chunking on the statute's own boundaries
# ---------------------------------------------------------------------------


def test_a_proviso_is_its_own_citable_chunk(index):
    """§15: *"the proviso IS the exclusion-zone rule."*

    `clear_space` cites `Rule 8(1) proviso`, and if the proviso were folded into
    Rule 8(1) an officer would be shown a sentence about the principal display
    panel that never mentions clear space.
    """
    proviso = index.get("Rule 8(1) proviso")

    assert proviso is not None
    assert proviso.text.startswith("Provided that")
    assert "free from printed information" in proviso.text


def test_the_provisos_lettered_clauses_stay_inside_it(index):
    """Rule 8(1)'s (a) and (b) *are* the clear-space distances.

    They restart the lettering at (a) rather than continuing a sequence, which
    is exactly how the chunker tells them from a clause that ends the proviso.
    """
    proviso = index.get("Rule 8(1) proviso")

    assert "at least the height of the numeral" in proviso.text
    assert "twice the height of numeral" in proviso.text


def test_a_clause_that_continues_the_sequence_ends_the_proviso(index):
    """The mirror image, and it cost the whole second half of Rule 2.

    Definition (k) carries a proviso; (l) through (r) follow it. Treating them
    as part of the proviso meant `Rule 2(m)` — "retail sale price" — could not
    be looked up at all.
    """
    definition = index.get("Rule 2(m)")

    assert definition is not None
    assert "retail sale price" in definition.text
    assert "maximum price" in definition.text


def test_a_schedule_item_never_masquerades_as_a_rule(index):
    """The Sixth Schedule restarts its numbering at 1.

    Rule 7 must be the principal display panel rule, not the Schedule's item 7.
    """
    rule = index.get("Rule 7")
    item = index.get("Sixth Schedule, item 7")

    assert "Principal display panel" in rule.heading
    assert item is not None
    assert "Checking of other declarations" in item.text


def test_a_sub_rule_after_a_proviso_is_not_swallowed(index):
    """Eight sub-rules went missing this way, Rule 18(5) among them."""
    dealer = index.get("Rule 18(5)")

    assert dealer is not None
    assert dealer.kind == "sub_rule"


def test_a_sub_rule_marked_with_an_amendment_asterisk_is_still_found(index):
    """The gazette prints `*(6)`. Without the marker in the pattern, the rule
    behind `LMPC.QTY.BANNED_WORDS` did not exist."""
    banned = index.get("Rule 12(6)")

    assert banned is not None
    assert "exaggerated, misleading" in banned.text


def test_a_table_is_chunked_under_the_rule_that_prints_it(index):
    table = index.get("Rule 7, Table I")

    assert table is not None
    assert table.kind == "table"
    assert "Minimum height of numeral" in table.text


def test_a_rule_carries_everything_nested_inside_it(index):
    """`Rule 8` answers a question about Rule 8; `Rule 8(1) proviso` answers a
    narrower one. Both must be available at the specificity the citation used."""
    rule = index.get("Rule 8")

    assert "principal display panel" in rule.text
    assert "free from printed information" in rule.text


def test_every_rule_of_the_gazette_is_present(index):
    """34 rules, none dropped. Two separate bugs each removed one silently.

    Scoped to the principal rules. It used to count every `rule` chunk in the
    index, which was the same thing while the corpus was one document and
    became a count of thirteen gazettes' rule numbers when it was not.
    """
    numbers = {
        int(chunk.ref.split()[1])
        for group in index.chunks.values()
        for chunk in group
        if chunk.kind == "rule" and chunk.doc_id == "lmpc_2011"
    }

    assert numbers == set(range(1, 35))


def test_chunking_is_deterministic():
    """A citation shown twice must be the same text both times — the property
    that separates this from a nearest-neighbour search."""
    source = "1. Short title.-\n(1) These rules may be called the Rules.\n"

    first = chunk_document(source, doc_id="x")
    second = chunk_document(source, doc_id="x")

    assert [c.text for c in first] == [c.text for c in second]


# ---------------------------------------------------------------------------
# Resolution — and never a guess
# ---------------------------------------------------------------------------


def test_a_verdicts_citation_resolves_to_the_clause_behind_it(index):
    answer = index.resolve("Rule 7(3)")

    assert answer.held
    assert "1 mm" in answer.citation.text
    assert answer.citation.page > 0


def test_a_sub_rule_never_silently_resolves_to_its_parent(index):
    """The single most important test in this file.

    A near-miss answer is worse than no answer: an officer shown Rule 7 when
    they asked for Rule 7(2) has been told the wrong law, confidently and in
    the right format.
    """
    answer = index.resolve("Rule 7(99)")

    assert not answer.held
    assert answer.citation is None
    assert [c.ref for c in answer.related] == ["Rule 7"]
    assert "No clause is separately held" in answer.note


def test_a_citation_into_a_gazette_we_do_not_hold_names_it(index):
    """A blank answer reads as a bug; naming the document is actionable.

    This used to assert it against the National Standards Rules, which the
    corpus now holds. Pointing it at a document we genuinely do not carry —
    the Act itself, of which we hold only the commencement notifications —
    keeps the behaviour under test instead of the state that happened to
    produce it.
    """
    answer = index.resolve("Legal Metrology Act 2009, s.18(1)")

    assert not answer.held
    assert "Legal Metrology Act, 2009" in answer.note
    assert "Packaged Commodities" in answer.note


def test_the_national_standards_rules_now_answer_their_own_citations(index):
    """Four advisory checks cite item 7, and the gazette prints it as
    `7. Printing:(1) Symbols of units- (a) ... (b) ...` — the sub-item shares a
    line with its first clause, so nothing files under `7(1)`. `7(1)(b)` is
    restated as `7(b)`, which is where the gazette actually puts it."""
    answer = index.resolve("NS Rules Third Schedule item 7(1)(b)")

    assert answer.held
    assert answer.citation.doc_id == "ns_rules_2011"
    assert "unaltered in the plural" in answer.citation.text
    # Read off a scan, so it is findable but not quotable without a check.
    assert answer.citation.read_as == "ocr"


def test_a_read_with_citation_answers_the_part_it_can(index):
    """`LMPC r.13(5)(i) read with NS Rules Third Schedule item 7(2)` is two
    references, and one of them is answerable.

    It used to be answerable only as far as `Rule 13(5)`, the parent, because
    the gazette prints `(5) (i) No system of units other than the International
    System of Units...` on one line and the clause never opened. Splitting the
    two markers makes the sub-clause itself the answer, which is the one the
    citation asked for.
    """
    answer = index.resolve("LMPC r.13(5)(i) read with NS Rules Third Schedule item 7(2)")

    assert answer.citation is not None
    assert answer.citation.ref == "Rule 13(5)(i)"
    # Not the full phrase: the text layer splits `International` and
    # `repair_spacing` will not join a fragment it cannot prove is one.
    assert "No system of units other than" in answer.citation.text
    # The other half names an instrument this citation does not resolve into.
    assert "National Standards" in answer.note


def test_a_table_citation_finds_the_table_the_gazette_prints_once(index):
    """`Rule 7(2), Table I` — the `(2)` names the sub-rule that invokes the
    table, and the gazette prints the table once, under Rule 7."""
    answer = index.resolve("Rule 7(2), Table I")

    assert answer.held
    assert answer.citation.ref == "Rule 7, Table I"


def test_a_range_citation_returns_every_sub_rule_it_spans(index):
    answer = index.resolve("Rule 13(2)-(3)")

    assert answer.held
    assert answer.citation.ref == "Rule 13(2)"
    assert "Rule 13(3)" in [c.ref for c in answer.related]


def test_a_schedule_citation_offers_the_schedule_beside_the_rule(index):
    answer = index.resolve("Rule 5, Second Schedule")

    assert answer.held
    assert answer.citation.ref == "Rule 5"


def test_the_abbreviated_form_is_the_same_citation(index):
    """`LMPC r.13(4)` and `Rule 13(4)` must not be two vocabularies."""
    assert index.resolve("LMPC r.13(4)").citation.ref == index.resolve("Rule 13(4)").citation.ref


def test_a_citation_the_gazette_duplicates_is_reported_as_such(index):
    """Rule 2 has two clauses lettered (r) in the published text.

    That is in the gazette, not in our parser, and picking one silently is how a
    report ends up quoting a definition nobody cited.
    """
    answer = index.resolve("Rule 2(r)")

    assert answer.held
    assert answer.citation.ambiguous
    assert len(answer.related) >= 1
    assert "two clauses" in answer.note


def test_lookup_is_case_and_whitespace_insensitive(index):
    assert index.resolve("  rule 8(1) PROVISO ").citation.ref == "Rule 8(1) proviso"


# ---------------------------------------------------------------------------
# The promise the rulepack makes
# ---------------------------------------------------------------------------


def test_every_citation_in_the_rulepack_gets_an_honest_answer(index):
    """Each `rule_ref` is a promise that "why" shows the officer something.

    Held, the enclosing provision clearly labelled, or a named gazette we do not
    carry — but never an empty response with no explanation.
    """
    unanswered = []
    for rule in load_rulepack().all_rules():
        answer = index.resolve(rule.rule_ref)
        if not (answer.held or answer.related or answer.note):
            unanswered.append(rule.rule_ref)

    assert unanswered == []


def test_most_of_the_rulepack_resolves_exactly(index):
    """A floor, not a target. The five National Standards citations and the one
    sub-clause the gazette prints inline are known and enumerated; a drop below
    this means something regressed in the chunker."""
    refs = {rule.rule_ref for rule in load_rulepack().all_rules()}
    exact = sum(1 for ref in refs if index.resolve(ref).held)

    assert exact >= 28, f"only {exact} of {len(refs)} citations resolve exactly"


def test_the_index_is_not_a_search_engine(index):
    """Nothing here embeds, ranks or scores. Tier 1 is a dict, and the same
    question asked twice returns the identical object."""
    first = index.resolve("Rule 8(1) proviso")
    second = index.resolve("Rule 8(1) proviso")

    assert first.citation.text == second.citation.text


def test_an_index_can_be_built_from_chunks_without_touching_the_disk():
    """`vision/` and `rules/` never open files at import; retrieval keeps the
    same discipline, so the index is testable with no corpus present."""
    index = CitationIndex.from_chunks(
        [
            Chunk(
                doc_id="x",
                ref="Rule 1(1)",
                parent_ref="Rule 1",
                heading="Short title",
                text="These rules may be called the Rules.",
                page=1,
            )
        ]
    )

    assert index.resolve("Rule 1(1)").held
    assert not index.resolve("Rule 2").held


# ---------------------------------------------------------------------------
# Over HTTP
# ---------------------------------------------------------------------------


def test_the_rules_list_says_which_citations_have_text(client_officer):
    """The existing `/api/v1/rules` gained one field rather than a rival route.

    Five of the pack's rules cite gazettes this deployment does not carry, and a
    "why" button that silently does nothing looks like a broken app rather than
    a missing document.
    """
    payload = client_officer.get("/api/v1/rules").json()

    assert payload["rules"]
    assert all("text_held" in rule for rule in payload["rules"])
    assert any(rule["text_held"] for rule in payload["rules"])
    assert payload["documents_held"]


def test_the_why_button_returns_the_verbatim_clause(client_officer):
    response = client_officer.get("/api/v1/rules/citation", params={"ref": "Rule 8(1) proviso"})
    payload = response.json()

    assert response.status_code == 200
    assert payload["held"]
    assert "free from printed information" in payload["citation"]["text"]
    assert "page" in payload["citation"]["source"]


def test_the_law_needs_no_token(client_officer):
    """`api/routers/ops.py` publishes the rulepack unauthenticated because
    *"there is nothing here that is not already in a gazette."* Verbatim gazette
    text is the purest case of that, so requiring a token to read the law while
    publishing the rule that applies it would be incoherent."""
    client_officer.headers.pop("Authorization")

    assert client_officer.get("/api/v1/rules/citation?ref=Rule 7(3)").status_code == 200


def test_the_response_is_cacheable_so_the_pwa_can_hold_it_offline(client_officer):
    """§15: the corpus fits in browser memory and tier 1 works offline at L1."""
    response = client_officer.get("/api/v1/rules/citation?ref=Rule 7(3)")

    assert "max-age" in response.headers["cache-control"]


def test_a_rule_detail_carries_the_clause_it_rests_on(client_officer):
    payload = client_officer.get("/api/v1/rules/LMPC.LETTER.MIN_HEIGHT").json()

    assert payload["rule_ref"] == "Rule 7(3)"
    assert payload["law"]["held"]
    assert "1 mm" in payload["law"]["citation"]["text"]


def test_an_unknown_rule_id_is_a_404_not_a_guess(client_officer):
    assert client_officer.get("/api/v1/rules/LMPC.NOT.A.RULE").status_code == 404


# ---------------------------------------------------------------------------
# A corpus of thirteen gazettes, not one
#
# Every test below guards a defect that appeared the moment a second document
# was ingested. None of them could fail while the corpus was a single file,
# which is exactly why they are worth having now.
# ---------------------------------------------------------------------------


def _two_document_index() -> CitationIndex:
    """Two gazettes that both print a Rule 3, because all of them do."""
    return CitationIndex.from_chunks(
        [
            Chunk(
                doc_id="lmpc_2011",
                ref="Rule 3",
                parent_ref=None,
                heading="Applicability of the Chapter",
                text="3. The provisions of this Chapter shall not apply to packages ...",
                page=4,
            ),
            Chunk(
                doc_id="numeration_2011",
                ref="Rule 3",
                parent_ref=None,
                heading="Manner in which numbers exceeding three digits shall be written",
                text="3. Numbers expressed in digits exceeding three shall be written ...",
                page=4,
            ),
        ]
    )


def test_the_same_rule_number_in_two_gazettes_is_not_one_ambiguous_rule():
    """`ambiguous` means *this gazette prints two clauses under one number*.

    Every instrument in the corpus has a Rule 1, 2 and 3. A globally keyed
    index reported the Packaged Commodities Rule 3 as ambiguous with the
    Numeration Rules' rule on writing numbers in words, and offered the second
    alongside the first — two unrelated provisions presented as a pair the
    gazette had printed together.
    """
    answer = _two_document_index().resolve("Rule 3")

    assert answer.held
    assert answer.citation.doc_id == "lmpc_2011"
    assert not answer.citation.ambiguous
    assert answer.related == ()


def test_an_unqualified_citation_means_the_principal_rules():
    """Which it must, because the rulepack writes bare refs everywhere."""
    answer = _two_document_index().resolve("Rule 3")
    assert answer.citation.heading.startswith("Applicability")


def test_a_citation_that_names_a_gazette_is_answered_from_that_gazette():
    answer = _two_document_index().resolve("LM (Numeration) Rules 2011, r.3")
    assert answer.held
    assert answer.citation.doc_id == "numeration_2011"
    assert "exceeding three" in answer.citation.text


def test_a_named_gazette_we_do_not_hold_is_still_named():
    """The rule that has not changed: a gap is reported as a gap, by name."""
    answer = _two_document_index().resolve("NS Rules Third Schedule item 7(1)(b)")

    assert not answer.held
    assert "National Standards" in answer.note
    # ...and the answer says what *is* held, so the gap is measurable.
    assert "Packaged Commodities" in answer.note


def test_a_schedule_item_is_found_whether_or_not_the_citation_writes_the_comma():
    """The rulepack writes `Third Schedule item 3`; the chunker files
    `Third Schedule, item 3`. One of them has to give, and it is not the index."""
    index = CitationIndex.from_chunks(
        [
            Chunk(
                doc_id="ns_rules_2011",
                ref="Fourth Schedule, item 3",
                parent_ref="Fourth Schedule",
                heading="Permitted unit of volume",
                text="3. Permitted unit of volume - (1) The permitted unit of volume "
                "shall be litre (Symbol: l).",
                page=70,
            )
        ]
    )
    answer = index.resolve("NS Rules Fourth Schedule item 3")
    assert answer.held
    assert "litre" in answer.citation.text


# ---------------------------------------------------------------------------
# Reading a scan is not reading a text layer
# ---------------------------------------------------------------------------


def test_a_rule_number_orphaned_onto_its_own_line_is_still_a_rule():
    """OCR returns one box per printed line, and these gazettes indent the rule
    number far enough that it lands alone. The Numeration Rules lost rules 1
    and 2 this way — including r.2(3), which the rulepack cites."""
    text = (
        "<<<PAGE 4>>>\n"
        "2.\n"
        "Procedure for making Numeration.- (1) Every numeration shall be made\n"
        "in accordance with the decimal system.\n"
        "(3) In representing any number in digits, the International form of "
        "Indian numerals, namely, 0,1,2,3,4,5,6,7,8,9 or a combination thereof "
        "shall be used.\n"
    )
    refs = {c.ref: c for c in chunk_document(text, doc_id="numeration_2011")}

    assert "Rule 2" in refs
    assert "Rule 2(3)" in refs
    assert "0,1,2,3,4,5,6,7,8,9" in refs["Rule 2(3)"].text


def test_a_serial_number_in_a_table_is_not_an_orphaned_rule_heading():
    """The Second Schedule is a table whose first column is a serial number on
    its own line. Joining those to the next line rebuilt the standard pack
    sizes one row out of step — item 14 came back as `14. 15. Soaps` — and
    dropped items 6, 8 and 19 entirely. A commodity name is not a heading: the
    gazette ends every heading with a dash after a stop or colon, and a table
    cell does not.
    """
    text = (
        "<<<PAGE 30>>>\n"
        "5.\n"
        "6. Cereals and Pulses 100g, 200g, 500g, 1 kg, 2 kg, 5 kg\n"
        "8.\n"
        "Bread including brown bread but excluding bun. 100g and thereafter.\n"
    )
    chunks = chunk_document(text, doc_id="lmpc_2011")

    # Item 6 keeps its own commodity, and no chunk swallows the row after it.
    assert not any(c.text.startswith("5. 6.") for c in chunks)
    assert not any(c.text.startswith("8. Bread") for c in chunks)
    sixes = [c for c in chunks if c.ref.endswith(" 6")]
    assert sixes and "Cereals" in sixes[0].heading


def test_the_primary_source_is_unchanged_by_the_scan_handling(index):
    """329 is the number of *provisions* the hand-verified text layer yields,
    and it is the number that must not move without a reason that can be named:
    322 once meant the Second Schedule had been quietly rebuilt around a bad
    orphan-heading join.

    It was 318 until the completeness audit, and the eleven it gained can each
    be named. `Rule 31(1)`, the advertisement provision, and four chunks of the
    First Schedule including `Table I`, the maximum permissible errors on net
    quantity: text the chunker held that nothing could cite, because a rule
    whose heading is one word, and a rule that begins at its own sub-rule, both
    failed to open. `Rule 13(5)(i)`, which the rulepack cites, from a sub-rule
    printed with its first clause inline. And five sub-rules of the Sixth
    Schedule whose heading carried `(1)` on the end of it -- one of which also
    moved a proviso from the item onto the sub-rule it actually qualifies.

    Two collisions went the other way in the same pass: a table's column
    numbers, `1. 2. 3.`, had been opening a second item 1.

    The eight chunks above that are containers -- its seven Schedules and its
    preamble -- asserted separately so a regression in either half cannot be
    absorbed by the other.
    """
    lmpc = [c for group in index.chunks.values() for c in group if c.doc_id == "lmpc_2011"]
    containers = [c for c in lmpc if c.kind in ("schedule", "preamble")]

    assert len(lmpc) - len(containers) == 329
    assert sorted(c.ref for c in containers) == [
        "Fifth Schedule",
        "First Schedule",
        "Fourth Schedule",
        "Preamble",
        "Second Schedule",
        "Seventh Schedule",
        "Sixth Schedule",
        "Third Schedule",
    ]


# ---------------------------------------------------------------------------
# How a clause was read travels with the clause
# ---------------------------------------------------------------------------


def test_text_from_a_publishers_text_layer_is_quotable(index):
    answer = index.resolve("Rule 13(5)")
    assert answer.citation.read_as == "text-layer"
    assert answer.citation.quotable
    assert answer.citation.caveat == ""


def test_text_read_off_a_scan_is_searchable_but_carries_a_caveat():
    """A recogniser right 97% of the time per line will occasionally put a
    wrong digit in a height threshold. That clause can be found and shown; it
    cannot be reproduced as the words of the statute without saying so."""
    index = CitationIndex.from_chunks(
        [
            Chunk(
                doc_id="ns_rules_2011",
                ref="Third Schedule, item 7",
                parent_ref="Third Schedule",
                heading="Printing of symbols",
                text="7. Unit symbols shall be printed in lower case ...",
                page=68,
                source="ocr",
            )
        ]
    )
    citation = index.resolve("NS Rules Third Schedule item 7").citation

    assert citation.read_as == "ocr"
    assert not citation.quotable
    assert "Verify against the page" in citation.caveat

# ---------------------------------------------------------------------------
# Nothing in the thirteen instruments is left out
# ---------------------------------------------------------------------------
#
# The question these answer is not "does retrieval work" but "is any statute
# missing from it", and that failure is invisible from the outside: a search
# over a corpus with two thirds of the National Standards Rules absent returns
# confident, well-formatted, correctly-cited results all day.
#
# Each of these was false when it was first written. See RESULTS.md.

_WORD = re.compile(r"[A-Za-z0-9]+")


def _bag(text: str) -> Counter[str]:
    return Counter(word.lower() for word in _WORD.findall(text))


@pytest.fixture(scope="module")
def corpus_documents() -> list[tuple[str, str]]:
    return [(path.stem, path.read_text(encoding="utf-8")) for path in sorted(RULEBOOK_DIR.glob("*.txt"))]


def test_every_word_of_every_page_read_reaches_a_chunk(corpus_documents):
    """**The completeness test.** Coverage was 94.51% when this was first
    measured, and what the missing 5.49% contained was not marginal: the
    maximum-permissible-error table, the standard pack sizes, the Fifth
    Schedule's sampling plan, and two thirds of the National Standards Rules.

    Compared against the text *after* page furniture is stripped, because
    dropping running headers is deliberate. Everything else must survive.
    """
    unreachable: dict[str, list[str]] = {}
    for doc_id, raw in corpus_documents:
        # The same normalisation `chunk_document` performs, in the same order.
        # Brackets first: `repair_spacing` counts words, and the counts decide
        # which joins fire, so restoring punctuation afterwards compares two
        # different documents and reports statute as lost that never was.
        restored = restore_ascii_punctuation(raw)
        repaired, _ = repair_spacing(restored, vocabulary(restored))
        lines = restore_roman_markers(strip_page_furniture(repaired.splitlines()))
        source = _bag(" ".join(text for _, text in lines))
        chunked = _bag(" ".join(c.text for c in chunk_document(raw, doc_id=doc_id)))
        missing = source - chunked
        if missing:
            unreachable[doc_id] = [w for w, _ in missing.most_common(8)]

    assert not unreachable, f"statute that no chunk contains: {unreachable}"


def test_every_instrument_produces_chunks(corpus_documents):
    """Three did not. Both commencement notifications and the General Rules
    corrigendum have no numbered rule in them, and a chunker that only emits
    rules emitted nothing at all — so they were ingested, extracted, listed in
    the manifest, and absent from the retriever."""
    empty = [doc_id for doc_id, raw in corpus_documents if not chunk_document(raw, doc_id=doc_id)]

    assert not empty, f"held, extracted, and not in the corpus: {empty}"


def test_no_chunk_cites_a_parent_that_has_no_text(index):
    """114 did. Every Schedule item pointed at a Schedule that was a boundary in
    the parser and never a chunk, so an officer following `Second Schedule,
    item 6` up to its Schedule got nothing back."""
    refs: dict[str, set[str]] = {}
    for group in index.chunks.values():
        for chunk in group:
            refs.setdefault(chunk.doc_id, set()).add(chunk.ref)

    dangling: dict[str, str] = {}
    for group in index.chunks.values():
        for chunk in group:
            if chunk.parent_ref is not None and chunk.parent_ref not in refs[chunk.doc_id]:
                dangling[f"{chunk.doc_id}::{chunk.ref}"] = chunk.parent_ref

    assert not dangling, f"chunks whose parent has no chunk: {dict(list(dangling.items())[:6])}"


def test_the_schedules_a_rule_cites_are_in_the_corpus(index):
    """Rule 18 of the National Standards Rules gives effect to the Seventh and
    Eighth Schedules — the C.G.S. units and the units outside the SI. Both sit
    on page 73, which the page-language test classified as Devanagari and threw
    away, so the corpus held a rule referring to Schedules it did not contain.

    The Eighth is set as `THE EIGHT SCHEDULE` in the gazette. It is filed under
    the name rule 18 uses.
    """
    refs = {
        chunk.ref
        for group in index.chunks.values()
        for chunk in group
        if chunk.doc_id == "ns_rules_2011"
    }

    assert {"Seventh Schedule", "Eighth Schedule"} <= refs


def test_a_schedule_is_a_container_and_does_not_swallow_its_items(index):
    """D24. A rule carries its sub-rules because they are one provision read
    together; a Schedule is a container of independent specifications. Carrying
    them made the General Rules' Eighth Schedule a single 416 KB chunk whose
    embedding described its first four hundred words."""
    chunks = [c for group in index.chunks.values() for c in group]
    largest = max(chunks, key=lambda c: len(c.text))

    assert len(largest.text) < 100_000, f"{largest.doc_id}::{largest.ref} is {len(largest.text)} chars"
    assert any(c.kind == "schedule" for c in chunks)


# ---------------------------------------------------------------------------
# Is any provision missing? -- the second completeness audit
#
# Coverage proves no *text* was lost. It cannot prove that the text is
# reachable under the citation an officer would use, and those are different
# questions: the National Standards Rules were at 100% coverage while rules 4,
# 7 and 8 were filed under rules 3 and 6.
# ---------------------------------------------------------------------------

PRINCIPAL_RULES = (
    "lmpc_2011",
    "ns_rules_2011",
    "general_rules_2011",
    "approval_of_models_2011",
    "iilm_rules_2011",
    "numeration_2011",
)
"""The instruments that number their rules from 1 without a break.

Amendment rules are excluded because they amend the rules they name and no
others -- the 2019 National Standards amendment touches 1, 2, 5 to 8 and 10,
and the gaps are the point of it. So is `model_test_labs_2014`, a notification
whose opening paragraph is unnumbered.
"""


def _rule_numbers(chunks) -> set[int]:
    found = set()
    for chunk in chunks:
        match = re.match(r"^Rule (\d+)", chunk.ref)
        if match:
            found.add(int(match.group(1)))
    return found


def test_no_principal_rules_document_skips_a_rule_number(index):
    """**The provision-completeness test.** Every one of these documents had a
    hole when it was first run, and the holes were not at the margins: National
    Standards rules 4, 7 and 8 are the metre, the ampere and the kelvin.

    A hole is not a rule that went missing quietly. The gazette prints `8.` on
    a line of its own and starts at `(1)` on the next, so the rule never opened
    and its sub-rules were read as a *second* `Rule 6(2)` -- the kelvin filed
    under the second. An officer asking for rule 6(2) was shown two provisions,
    and neither the citation nor the text said anything was wrong.
    """
    holes: dict[str, list[int]] = {}
    for doc_id in PRINCIPAL_RULES:
        numbers = _rule_numbers(
            c for group in index.chunks.values() for c in group if c.doc_id == doc_id
        )
        assert numbers, f"{doc_id} produced no numbered rules at all"
        missing = [n for n in range(1, max(numbers) + 1) if n not in numbers]
        if missing:
            holes[doc_id] = missing

    assert not holes, f"rule numbers no chunk carries: {holes}"


def test_a_rule_that_begins_at_its_own_sub_rule_is_still_a_rule(index):
    """The National Standards Rules print rules 4 to 8 with no heading, and
    rules 5 and 6 with the heading and sub-rule (1) run together on one line.

    Both spellings now open the rule and leave the sub-rule to open under it,
    so the metre is `Rule 4(1)` rather than a second `Rule 3(1)`.
    """
    ns = {
        chunk.ref: chunk
        for group in index.chunks.values()
        for chunk in group
        if chunk.doc_id == "ns_rules_2011"
    }

    assert {"Rule 4", "Rule 5", "Rule 6", "Rule 7", "Rule 8"} <= set(ns)
    assert "metre" in ns["Rule 4"].text
    assert "kelvin" in ns["Rule 8"].text.lower()
    # And the rule it used to be filed under no longer answers for it.
    assert "metre" not in ns["Rule 3"].text


def test_a_full_width_bracket_does_not_hide_a_sub_rule():
    """The recogniser sets `(1)` as a CJK bracket on 212 lines of the corpus,
    and `SUB_RULE` reads an ASCII one. Thirteen sub-rules were invisible."""
    # Written as an escape, not the glyph: the point of the test is that this
    # codepoint is indistinguishable from `(` on a page, and not to a regex.
    bracket = "\uff08"
    restored = restore_ascii_punctuation(
        f"8.\n{bracket}1) Base unit of thermodynamic temperature-"
    )

    assert "(1)" in restored
    # A superscript is not punctuation and must survive: the Second Schedule
    # defines the unit of area as `m²`.
    assert restore_ascii_punctuation("Symbol: m²") == "Symbol: m²"


def test_a_schedule_part_tells_two_specifications_apart(index):
    """The Eighth Schedule of the General Rules is 126 pages of specifications
    -- filling machines, bulk meters, water meters, thermometers -- and each
    numbers its clauses from 1. `Eighth Schedule, item 3` named twenty-three
    provisions, so tier 1 could only refuse it."""
    refs = [
        chunk.ref
        for group in index.chunks.values()
        for chunk in group
        if chunk.doc_id == "general_rules_2011"
    ]

    assert any(re.match(r"^Eighth Schedule, Part [IVXL0-9]+, item ", ref) for ref in refs)


def test_a_row_of_column_numbers_is_not_a_provision(index):
    """`Sl. No. | Commodities | Quantities` and then `1. 2. 3.` beneath it. That
    opened a second `Second Schedule, item 1`, so the citation for baby food
    resolved to a table header as well."""
    items = [
        chunk
        for group in index.chunks.values()
        for chunk in group
        if chunk.doc_id == "lmpc_2011" and chunk.ref == "Second Schedule, item 1"
    ]

    assert len(items) == 1, "a citation resolving to two things is a citation to neither"
    assert "Baby food" in items[0].text


def test_a_heading_does_not_swallow_its_own_first_sub_rule(index):
    """`15.Permitted units.(1) The units specified in the Fourth Schedule may`
    is one line, and the whole of it was the heading. Sub-rule (1) was not a
    chunk while (2) and (3), printed on their own lines, were -- in 35 rules
    across every instrument in the corpus."""
    ns = {
        chunk.ref
        for group in index.chunks.values()
        for chunk in group
        if chunk.doc_id == "ns_rules_2011"
    }

    assert {"Rule 15(1)", "Rule 15(2)"} <= ns
    assert {"Rule 18(1)", "Rule 22(1)", "Rule 23(1)"} <= ns


def test_a_clause_letter_is_not_repaired_into_a_roman_numeral(index):
    """The repair that puts `(iii)` back where the scan read `(ili)` must never
    touch `(l)`.

    Rule 2(l) of the Packaged Commodities Rules defines *retail sale*, which is
    what `retail sale price` in rule 6(1)(e) is a price for. The first version
    of the repair rewrote it as `(i)` and took three of the pack's citations
    down with it.
    """
    answer = index.resolve("Rule 2(l)")

    assert answer.held
    assert answer.citation is not None
    assert "retail sale" in answer.citation.text.lower()


def test_a_clause_letter_read_as_a_digit_is_put_back(index):
    """The mirror of the repair above: `(l)` read as `(1)`.

    The National Standards Rules define *SI prefix* at rule 2(l), between
    `(k) "Schedule"` and `(m) "special units"`. Read as `(1)` it became a
    sub-rule of rule 2, taking the two definitions after it along with it, so
    `Rule 2(l)`, `Rule 2(m)` and `Rule 2(n)` were all unreachable and
    `Rule 2(1)` -- a sub-rule the gazette never printed -- answered instead.
    """
    ns = {
        chunk.ref: chunk.text
        for group in index.chunks.values()
        for chunk in group
        if chunk.doc_id == "ns_rules_2011"
    }

    assert "Rule 2(l)" in ns
    assert "si prefix" in ns["Rule 2(l)"].lower()
    # and the sub-rule the gazette never printed is gone
    assert "Rule 2(1)" not in ns


def test_the_definitions_run_unbroken_from_a_to_n(index):
    """Nothing between (a) and (n) may be missing or filed a level down."""
    refs = {
        chunk.ref
        for group in index.chunks.values()
        for chunk in group
        if chunk.doc_id == "ns_rules_2011"
    }
    expected = {f"Rule 2({letter})" for letter in "abcdefghijklmn"}

    assert expected <= refs, sorted(expected - refs)


def test_a_sub_rule_one_is_left_alone_unless_it_follows_clause_k():
    """The repair is positional, and must not fire anywhere else."""
    from retrieval.chunker import restore_ell_marker

    kept = [(1, "(j) something ends here;"), (1, "(1) A genuine sub-rule.")]
    assert restore_ell_marker(kept) == kept

    opening = [(1, "(k) the last clause;"), (1, "5. A new rule.-"), (1, "(1) Its first sub-rule.")]
    assert restore_ell_marker(opening) == opening

    repaired = restore_ell_marker([(1, "(k) the last clause;"), (1, "(1) the next one;")])
    assert repaired[1][1] == "(l) the next one;"


def test_a_scanned_roman_numeral_is_addressable(index):
    """`i`, `l` and `1` are one glyph to a recogniser, and 420 chunks were
    reachable only under a citation nobody could type."""
    refs = [chunk.ref for group in index.chunks.values() for chunk in group]
    mangled = [ref for ref in refs if re.search(r"\((?=[il1]*[l1])[il1]{2,3}\)", ref)]

    # What survives is `(11)`, which is sub-rule 11 far more often than it is a
    # damaged `(ii)` and is deliberately left alone.
    assert all("11" in ref for ref in mangled), mangled[:6]
    assert any(re.search(r"\(iii\)", ref) for ref in refs)

