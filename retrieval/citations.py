"""Tier 1 — the retrieval that is not retrieval. AKSHAR.md section 15.

    "Every `Verdict` already carries `rule_ref` [...] **The citation is the
     retrieval key.** We do not need to search for Rule 7(2); we know it is
     Rule 7(2)."

    "Tier 1 covers the overwhelming majority of use. [...] Build it first; it is
     an afternoon's work and it is the feature officers will actually use."

A dictionary lookup, under a millisecond, offline-capable, and **deterministic**
— which is the property that matters. §15 opens by ruling a language model out
of the decision path because *"the same photo can yield different verdicts on
different days and nobody can explain why"*. The same argument applies to what
is shown beside a verdict: an officer who taps "why" twice must see the same
clause both times, and a nearest-neighbour search cannot promise that.

**So this module never guesses.** If a citation does not resolve exactly it says
so and names what it does hold. Three things follow from that, and each is a
failure mode this file exists to prevent:

*No near-miss fallback.* Not finding `Rule 7(2)` must never quietly return
`Rule 7`. The parent is returned only as an explicitly labelled `related` entry,
because "here is the rule this sub-rule sits in" is useful and "here is the law
you were asking about" would be false.

*Documents we do not hold say so.* Several rules in the pack cite the National
Standards Rules or the Numeration Rules, whose text is not in
`data/rulebook/extracted/`. Those return `held=False` with the document named,
which is a fact an officer can act on. Silently returning nothing reads as a
bug; returning the LMPC rule that mentions them would be a substitution.

*A citation the gazette itself duplicates is reported as ambiguous.* Rule 2 of
the Packaged Commodities Rules has **two clauses lettered (r)** — "wholesale
package" and "words and expression used herein". That is in the published text,
not in our parser, and picking one of them silently is how a report ends up
quoting a definition nobody cited.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from retrieval import provenance
from retrieval.chunker import Chunk, chunk_document

RULEBOOK_DIR = Path(__file__).resolve().parent.parent / "data" / "rulebook" / "extracted"

DOCUMENTS: dict[str, str] = {
    "lmpc_2011": "The Legal Metrology (Packaged Commodities) Rules, 2011",
    "ns_rules_2011": "The Legal Metrology (National Standards) Rules, 2011",
    "ns_rules_2019_amdt": "The Legal Metrology (National Standards) Amendment Rules, 2019",
    "numeration_2011": "The Legal Metrology (Numeration) Rules, 2011",
    "numeration_2011_amdt": "The Legal Metrology (Numeration) Amendment Rules, 2011",
    "general_rules_2011": "The Legal Metrology (General) Rules, 2011",
    "general_rules_2011_corr": "Corrigendum to the Legal Metrology (General) Rules, 2011",
    "approval_of_models_2011": "The Legal Metrology (Approval of Models) Rules, 2011",
    "approval_of_models_2019_amdt": (
        "The Legal Metrology (Approval of Models) Amendment Rules, 2019"
    ),
    "model_test_labs_2014": "Notification under the Approval of Models Rules, rr. 3-5",
    "iilm_rules_2011": "The Indian Institute of Legal Metrology Rules, 2011",
    "act_commencement_2010": "Legal Metrology Act, 2009 — commencement",
    "act_commencement_2011": "Legal Metrology Act, 2009 — commencement rescinded and refixed",
}
"""Every gazette the ingester knows how to name, by `doc_id`.

This is the *nameable* set, not the held set. Whether a document's text is
actually present is answered by `CitationIndex.held`, which asks whether the
index has chunks for it — one question with one answer, rather than a constant
that can fall out of step with the directory it describes.
"""

PRIMARY_DOCUMENT = "lmpc_2011"
"""Where an unqualified citation is looked up.

Every bare `Rule 13(5)` in the rulepack means the Packaged Commodities Rules;
that is the instrument this tool enforces. It has to be stated somewhere,
because once the corpus holds thirteen gazettes there are thirteen Rule 2s.
"""

DOCUMENT_PREFIXES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Amendments first: `NS Rules 2019 Amendment` must not be eaten by the
    # pattern for the principal Rules and then fail to resolve against them.
    (
        re.compile(
            r"^\s*(?:NS|National\s+Standards)\s+(?:Amendment\s+)?Rules\s*,?\s*2019"
            r"(?:\s+Amendment)?\s*,?\s*",
            re.IGNORECASE,
        ),
        "ns_rules_2019_amdt",
    ),
    (
        re.compile(
            r"^\s*(?:LM\s*)?\(?Numeration\)?\s+(?:Amendment\s+)?Rules\s*,?\s*2011"
            r"\s+Amendment\s*,?\s*",
            re.IGNORECASE,
        ),
        "numeration_2011_amdt",
    ),
    (
        re.compile(
            r"^\s*Approval\s+of\s+Models\s+(?:Amendment\s+)?Rules\s*,?\s*2019"
            r"(?:\s+Amendment)?\s*,?\s*",
            re.IGNORECASE,
        ),
        "approval_of_models_2019_amdt",
    ),
    (
        re.compile(r"^\s*(?:NS|National\s+Standards)\s+Rules\s*,?\s*(?:2011)?\s*,?\s*", re.IGNORECASE),
        "ns_rules_2011",
    ),
    (
        re.compile(r"^\s*(?:LM\s*)?\(?Numeration\)?\s*Rules\s*,?\s*(?:2011)?\s*,?\s*", re.IGNORECASE),
        "numeration_2011",
    ),
    (
        re.compile(r"^\s*(?:LM\s*)?\(?General\)?\s+Rules\s*,?\s*(?:2011)?\s*,?\s*", re.IGNORECASE),
        "general_rules_2011",
    ),
    (
        re.compile(r"^\s*Approval\s+of\s+Models\s+Rules\s*,?\s*(?:2011)?\s*,?\s*", re.IGNORECASE),
        "approval_of_models_2011",
    ),
    (
        re.compile(
            r"^\s*(?:IILM|Indian\s+Institute\s+of\s+Legal\s+Metrology)\s+Rules\s*,?\s*"
            r"(?:2011)?\s*,?\s*",
            re.IGNORECASE,
        ),
        "iilm_rules_2011",
    ),
    (
        re.compile(
            r"^\s*(?:Model\s+)?(?:Approved\s+)?Test\s+(?:Labs|Laboratories)\s+Rules\s*,?\s*"
            r"(?:2014)?\s*,?\s*",
            re.IGNORECASE,
        ),
        "model_test_labs_2014",
    ),
    (re.compile(r"^\s*LMPC\s*,?\s*", re.IGNORECASE), "lmpc_2011"),
)
"""How a citation names the gazette it points into.

The rulepack writes `NS Rules Third Schedule item 7(1)(b)` and `LM (Numeration)
Rules 2011, r.2(3)`. Stripping the prefix leaves a reference in that document's
own vocabulary, which is the only form the chunker ever produced.

**Every held instrument is nameable, not just the three the rulepack cites.**
The corpus is thirteen documents; when only three could be addressed, a citation
into the General Rules -- 655 pages, the largest thing here -- fell through to
the primary document and resolved against the wrong gazette or not at all.
Amendments are listed ahead of the Rules they amend, since `NS Rules 2019
Amendment` otherwise matches the pattern for the principal Rules and is then
looked up in the wrong instrument.
"""

_SCHEDULE_ITEM = re.compile(r"\bSchedule\s+item\s+", re.IGNORECASE)
_NUMERIC_THEN_ALPHA = re.compile(r"\((\d{1,2})\)\((([a-z]{1,3}))\)\s*$")

EXTERNAL_DOCUMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bNS\s+Rules\b|\bNational\s+Standards\b", re.IGNORECASE),
        "The Legal Metrology (National Standards) Rules, 2011",
    ),
    (
        re.compile(r"\bNumeration\b", re.IGNORECASE),
        "The Legal Metrology (Numeration) Rules, 2011",
    ),
    (re.compile(r"\bLegal\s+Metrology\s+Act\b", re.IGNORECASE), "The Legal Metrology Act, 2009"),
)
"""Documents a rule may cite that we do not hold the text of.

Recognised by name so the answer can be *"the National Standards Rules, which
this deployment does not carry"* rather than a blank. A named absence is
actionable; an empty result is indistinguishable from a broken lookup.
"""

_READ_WITH = re.compile(r"\s+read\s+with\s+", re.IGNORECASE)
_LMPC_PREFIX = re.compile(r"^\s*LMPC\s+", re.IGNORECASE)
_RULE_TOKEN = re.compile(r"^\s*(?:rule\s*|r\.\s*)(\d{1,3})\s*(.*)$", re.IGNORECASE)
# The gazette writes ranges with any of three dashes.
_RANGE = re.compile(r"^\((\d{1,2})\)\s*[-–—]\s*\((\d{1,2})\)\s*(.*)$")  # noqa: RUF001
_TABLE_SUFFIX = re.compile(r",?\s*Table[\s-]*([IVX]+)\s*$", re.IGNORECASE)
_SCHEDULE_SUFFIX = re.compile(
    r",\s*(First|Second|Third|Fourth|Fifth|Sixth|Seventh)\s+Schedule\s*$", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class Citation:
    """One clause, verbatim, with everything needed to check it against print."""

    ref: str
    doc_id: str
    document: str
    heading: str
    text: str
    page: int
    kind: str
    parent_ref: str | None = None
    ambiguous: bool = False
    read_as: str = provenance.TEXT_LAYER
    """How this page was read. Named `read_as` and not `source` because `source`
    on this class already means the citation line a report prints, and quietly
    changing what that means would alter every existing report."""

    @property
    def source(self) -> str:
        """What a report prints under the quotation."""
        return f"{self.document}, page {self.page}"

    @property
    def quotable(self) -> bool:
        """May this be reproduced as the words of the statute?"""
        return self.read_as in provenance.QUOTABLE

    @property
    def caveat(self) -> str:
        """The warning to print alongside, empty when none is needed."""
        return provenance.describe(self.read_as)


def _as_citation(chunk: Chunk, *, ambiguous: bool) -> Citation:
    return Citation(
        ref=chunk.ref,
        doc_id=chunk.doc_id,
        document=DOCUMENTS.get(chunk.doc_id, chunk.doc_id),
        heading=chunk.heading,
        text=chunk.text,
        page=chunk.page,
        kind=chunk.kind,
        parent_ref=chunk.parent_ref,
        ambiguous=ambiguous,
        read_as=chunk.source,
    )


@dataclass(frozen=True, slots=True)
class Answer:
    """What tier 1 says. Never a guess, sometimes an honest refusal."""

    ref: str
    citation: Citation | None = None
    related: tuple[Citation, ...] = ()
    note: str = ""

    @property
    def held(self) -> bool:
        return self.citation is not None


@dataclass
class CitationIndex:
    """`rule_ref` → verbatim text. §15's tier 1, and nothing more than a dict."""

    chunks: dict[str, list[Chunk]] = field(default_factory=lambda: defaultdict(list))

    @classmethod
    def from_chunks(cls, chunks: list[Chunk]) -> CitationIndex:
        index = cls()
        for chunk in chunks:
            index.chunks[_key(chunk.doc_id, chunk.ref)].append(chunk)
        return index

    @property
    def held(self) -> frozenset[str]:
        """The `doc_id`s this index actually has text for."""
        return frozenset(key.split("::", 1)[0] for key in self.chunks)

    def held_titles(self) -> list[str]:
        return sorted(DOCUMENTS.get(doc, doc) for doc in self.held)

    @classmethod
    def from_directory(cls, directory: Path = RULEBOOK_DIR) -> CitationIndex:
        """Build from the extracted gazette text.

        Built from the text rather than from a generated JSON artefact so there
        is exactly one source of truth and no way for the two to drift. The
        whole corpus chunks in a fraction of a second and the result is cached;
        `scripts/build_rulebook.py` writes the JSON for the browser, where §15
        wants tier 1 working offline.
        """
        chunks: list[Chunk] = []
        for path in sorted(directory.glob("*.txt")):
            chunks.extend(
                chunk_document(path.read_text(encoding="utf-8"), doc_id=path.stem)
            )
        return cls.from_chunks(chunks)

    def __len__(self) -> int:
        return sum(len(group) for group in self.chunks.values())

    def get(self, ref: str, *, doc_id: str = PRIMARY_DOCUMENT) -> Citation | None:
        """Exact lookup within one gazette.

        Scoped by document because thirteen gazettes have thirteen `Rule 2`s,
        and a global key makes `ambiguous` — which means *this gazette prints
        two clauses under one number* — fire on two unrelated instruments.
        """
        group = self.chunks.get(_key(doc_id, ref))
        if not group:
            return None
        return _as_citation(group[0], ambiguous=len(group) > 1)

    def variants(self, ref: str, *, doc_id: str = PRIMARY_DOCUMENT) -> tuple[Citation, ...]:
        """Every chunk filed under a ref. More than one means the gazette repeats it."""
        group = self.chunks.get(_key(doc_id, ref), [])
        return tuple(_as_citation(chunk, ambiguous=len(group) > 1) for chunk in group)

    # -- resolution ------------------------------------------------------

    def resolve(self, rule_ref: str) -> Answer:
        """Turn a verdict's citation into the clause behind it.

        The rulepack writes citations the way a lawyer would, and this reads
        them the same way. `LMPC r.13(5)(i) read with NS Rules Third Schedule
        item 7(2)` is one primary reference plus one to a document we do not
        hold, and the honest answer names both.
        """
        parts = _READ_WITH.split(rule_ref.strip(), maxsplit=1)
        primary = parts[0]
        secondary = parts[1] if len(parts) > 1 else ""

        answer = self._resolve_one(primary or rule_ref, asked=rule_ref)
        if not secondary:
            return answer

        note = answer.note
        external = _external_document(secondary)
        addition = (
            f"Read with {secondary.strip()} — {external}, whose text this deployment "
            f"does not hold."
            if external
            else f"Read with {secondary.strip()}."
        )
        return Answer(
            ref=answer.ref,
            citation=answer.citation,
            related=answer.related,
            note=f"{note} {addition}".strip(),
        )

    def _resolve_one(self, ref: str, *, asked: str) -> Answer:
        ref = ref.strip().rstrip(".,;")

        # Which gazette is this citation pointing into, and do we hold it?
        # These are two questions and they used to be one: the old code treated
        # "names another instrument" as "not held", which was true when the
        # corpus was a single document and became wrong the moment it was not.
        doc_id, ref, named = _split_document(ref)

        # An unqualified citation assumes the primary instrument. When the
        # index holds exactly one gazette and it is not that one, there is
        # nothing to be ambiguous about and the assumption is just wrong —
        # a deployment carrying a single document should answer from it.
        if not named and doc_id not in self.held and len(self.held) == 1:
            doc_id = next(iter(self.held))

        if doc_id not in self.held:
            named = DOCUMENTS.get(doc_id, doc_id)
            return Answer(
                ref=asked,
                note=(
                    f"{asked} is a provision of {named}. This deployment holds "
                    f"the text of: {', '.join(self.held_titles())}."
                ),
            )

        external = _external_document(ref)
        if external and doc_id == PRIMARY_DOCUMENT:
            return Answer(
                ref=asked,
                note=(
                    f"{ref} is a provision of {external}. This deployment holds "
                    f"the text of: {', '.join(self.held_titles())}."
                ),
            )

        related: list[Citation] = []

        # "Rule 5, Second Schedule" — the Schedule is where the detail lives, so
        # it is offered alongside rather than instead of the rule that invokes it.
        schedule = _SCHEDULE_SUFFIX.search(ref)
        if schedule:
            ref = _SCHEDULE_SUFFIX.sub("", ref)
            found = self.get(f"{schedule.group(1).title()} Schedule", doc_id=doc_id)
            if found:
                related.append(found)

        candidates = _candidate_refs(ref)
        for candidate in candidates:
            found = self.get(candidate, doc_id=doc_id)
            if found is not None:
                return Answer(
                    ref=asked,
                    citation=found,
                    related=tuple(related + self._siblings(found, ref, doc_id)),
                    note=(
                        "The gazette prints two clauses under this number; both are "
                        "shown."
                        if found.ambiguous
                        else ""
                    ),
                )

        # Nothing matched. Walk up and offer the enclosing provision **as
        # `related`, never as `citation`** — the distinction is the whole
        # discipline of this module. Two real cases in the current rulepack:
        #
        #   Rule 13(5)(i) — the gazette prints "(5) (i) No system of units …"
        #     on one line, so the sub-clause has no chunk of its own and its
        #     text is inside Rule 13(5). The parent genuinely contains what was
        #     asked for.
        #   Rule 12(6) — the published text runs (5) then (7). There is no
        #     sub-rule (6) to hold, and saying "Rule 12 is held and has no
        #     sub-rule (6)" points at a defect in our citation rather than
        #     leaving an officer to wonder whether retrieval is broken.
        #
        # Either way the answer is `held=False`. An officer is shown the wider
        # provision, told it is the wider provision, and never told it is the
        # clause they asked for.
        for ancestor in _ancestors(ref):
            found = self.get(ancestor, doc_id=doc_id)
            if found is not None:
                return Answer(
                    ref=asked,
                    related=(*related, found),
                    note=(
                        f"No clause is separately held under {ref!r}. The provision "
                        f"containing it, {found.ref}, is shown instead — either the "
                        f"gazette does not break it out, or the published numbering "
                        f"has no such sub-provision."
                    ),
                )

        return Answer(
            ref=asked,
            related=tuple(related),
            note=(
                f"No clause is held under {ref!r}. It is either a provision of a "
                f"gazette this deployment does not carry, or the citation does not "
                f"match the numbering of the published text."
            ),
        )

    def _siblings(self, found: Citation, ref: str, doc_id: str) -> list[Citation]:
        """The other clauses a reader needs beside this one."""
        extra: list[Citation] = []
        if found.ambiguous:
            extra.extend(self.variants(found.ref, doc_id=doc_id)[1:])
        # A range — "Rule 13(2)-(3)" — resolved to its first member. The rest of
        # the range is the other half of the citation, not a suggestion.
        for member in _range_members(ref)[1:]:
            sibling = self.get(member, doc_id=doc_id)
            if sibling is not None:
                extra.append(sibling)
        return extra


_TRAILING_GROUP = re.compile(r"\([^()]*\)\s*$")


def _ancestors(ref: str) -> list[str]:
    """`Rule 13(5)(i)` → `Rule 13(5)`, `Rule 13`. Narrowest enclosing first."""
    ref = _TABLE_SUFFIX.sub("", re.sub(r"\s+proviso.*$", "", ref, flags=re.IGNORECASE)).strip()
    out: list[str] = []
    normalised = _RULE_TOKEN.match(ref)
    if normalised:
        ref = f"Rule {normalised.group(1)}{normalised.group(2).strip()}"
    while _TRAILING_GROUP.search(ref):
        ref = _TRAILING_GROUP.sub("", ref).strip()
        if ref:
            out.append(ref)
    return out


def _key(doc_id: str, ref: str) -> str:
    return f"{doc_id}::{ref.strip().lower()}"


def _split_document(ref: str) -> tuple[str, str, bool]:
    """`NS Rules Third Schedule item 7(1)(b)` → `("ns_rules_2011", "Third Schedule, item 7(1)(b)", True)`.

    The third value says whether the citation *named* a gazette. An unqualified
    reference is assumed to mean the primary instrument, but that is an
    assumption and the caller has to be able to tell it apart from a citation
    that said so.

    The comma matters. The chunker files schedule items as `Third Schedule,
    item 7`, because that is how a schedule item is cited in prose; the
    rulepack writes the same reference without the comma. Normalising here
    rather than loosening the lookup keeps the index keys exact.
    """
    for pattern, doc_id in DOCUMENT_PREFIXES:
        stripped = pattern.sub("", ref, count=1)
        if stripped != ref:
            return doc_id, _SCHEDULE_ITEM.sub("Schedule, item ", stripped).strip(), True
    return PRIMARY_DOCUMENT, _SCHEDULE_ITEM.sub("Schedule, item ", ref).strip(), False


def _external_document(ref: str) -> str | None:
    for pattern, name in EXTERNAL_DOCUMENTS:
        if pattern.search(ref):
            return name
    return None


def _range_members(ref: str) -> list[str]:
    """`Rule 13(2)-(3)` → the sub-rules it spans."""
    match = _RULE_TOKEN.match(ref)
    if not match:
        return []
    number, tail = match.group(1), match.group(2).strip()
    span = _RANGE.match(tail)
    if not span:
        return []
    first, last = int(span.group(1)), int(span.group(2))
    return [f"Rule {number}({n})" for n in range(first, last + 1)]


def _candidate_refs(ref: str) -> list[str]:
    """The keys to try, in order, most specific first. **No near misses.**

    Every entry here is a *restatement* of the same citation in the numbering
    the gazette uses, never a broader one. `Rule 7(2), Table I` becomes
    `Rule 7, Table I` because the gazette prints Table I once, under Rule 7, and
    the `(2)` in the citation names the sub-rule that invokes it — the table is
    the same table either way. `Rule 7(2)` never becomes `Rule 7`.
    """
    ref = re.sub(r"\s+", " ", ref).strip()
    candidates = [ref]

    members = _range_members(ref)
    if members:
        candidates.extend(members)

    table = _TABLE_SUFFIX.search(ref)
    if table:
        head = _TABLE_SUFFIX.sub("", ref).strip()
        rule = _RULE_TOKEN.match(head)
        if rule:
            candidates.append(f"Rule {rule.group(1)}, Table {table.group(1).upper()}")

    normalised = _RULE_TOKEN.match(ref)
    if normalised:
        # `r.13(5)(i)` and `Rule 13(5)(i)` are the same citation.
        candidates.append(f"Rule {normalised.group(1)}{normalised.group(2).strip()}")

    # `item 7(1)(b)` → `item 7(b)`, tried only after the literal form.
    #
    # The National Standards Rules print item 7 as `7. Printing:(1) Symbols of
    # units- (a) ... (b) ...` — the sub-item and its first clause share a line,
    # so no `(1)` level is opened and (a)-(d) file directly under 7. The
    # clauses ARE the whole of (1), so dropping it restates the same citation
    # rather than widening it.
    #
    # Last in the list on purpose. If a document ever did print both `7(1)(b)`
    # and `7(2)(b)`, the literal form is found first, and a genuine collision
    # under the collapsed key surfaces through `ambiguous` instead of being
    # quietly resolved to whichever came first.
    collapsed = _NUMERIC_THEN_ALPHA.sub(r"(\2)", ref)
    if collapsed != ref:
        candidates.append(collapsed)

    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        key = candidate.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(candidate)
    return ordered


@lru_cache(maxsize=1)
def load_index() -> CitationIndex:
    """The process-wide index. Built once; the corpus does not change at runtime."""
    return CitationIndex.from_directory()


def explain(rule_ref: str) -> Answer:
    """What an officer sees when they tap "why" on a verdict."""
    return load_index().resolve(rule_ref)


__all__ = [
    "DOCUMENTS",
    "EXTERNAL_DOCUMENTS",
    "RULEBOOK_DIR",
    "Answer",
    "Citation",
    "CitationIndex",
    "explain",
    "load_index",
]
