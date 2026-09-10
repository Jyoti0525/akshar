"""Tier 3, the extractive default. AKSHAR.md §15.

    "**Default: extractive, not generative.** Display the verbatim gazette text
     with the matched span highlighted. No model writes anything."

    "A generated paraphrase of a statute is an unattributed restatement of law
     that nobody signed off. The verbatim clause is the actual authority."

So tier 3 is not a generation step with the model switched off. It is a
different operation: locate the parts of the retrieved clause that answer the
question, and mark them *in place*. The text an officer reads is always the
gazette's, byte for byte.

**Spans, not a rewritten string.** This module returns offsets into the
original text and never a modified copy. A highlighter that returned marked-up
text would be the only component in the system permitted to alter statute, and
the first time an escaping bug mangled a clause it would do so invisibly. With
offsets the caller renders around the text; the text itself cannot change.

**Stemming is deliberately absent.** `matched` uses whole-word, case-folded
comparison and a small suffix rule, not a stemmer. A stemmer would conflate
`packing` and `packaged` — two terms the Packaged Commodities Rules use to mean
different things (`Rule 2(l)` pre-packed commodity, versus the packing date of
`Rule 6(1)(d)`) — and highlighting one when an officer asked about the other is
a quiet misdirection in a document that looks authoritative.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

WORD = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*|\d+(?:[.,]\d+)*")  # noqa: RUF001
"""The apostrophe is the typographic one as well as the ASCII one, because the
gazette is typeset and OCR reproduces what it sees."""

STOPWORDS: frozenset[str] = frozenset(
    ["a", "an", "the", "and", "or", "but", "if", "of", "to", "in", "on", "at", "by", "for", "with", "from", "as", "is", "are", "was", "were", "be", "been", "being", "it", "its", "this", "that", "these", "those", "which", "who", "whom", "what", "shall", "may", "must", "not", "no", "any", "such", "other", "than", "then", "there", "here", "when", "where", "how", "why", "all", "each", "both", "more", "most", "some"]
)
"""Words too common to mark. Highlighting every `the` in a clause highlights the
clause, which is the same as highlighting nothing."""

MIN_LENGTH = 3
"""Below this a token is noise — `mm` survives because it is a digit-adjacent
unit, but bare two-letter words carry no locating power."""

_PLURAL = re.compile(r"(?:ies|es|s)$")


@dataclass(frozen=True, slots=True)
class Span:
    """A half-open `[start, end)` range into the clause text, with the term."""

    start: int
    end: int
    term: str

    def slice(self, text: str) -> str:
        return text[self.start : self.end]


@dataclass(frozen=True, slots=True)
class Passage:
    """A clause, the spans worth marking in it, and how much of the query it met.

    `coverage` is the fraction of the query's meaningful terms that appear.
    It is reported rather than thresholded: §15 puts no model in this path, so
    the decision about whether a passage is good enough belongs to the person
    reading it, who can see the clause.
    """

    text: str
    spans: tuple[Span, ...]
    coverage: float

    @property
    def matched_terms(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for span in self.spans:
            seen.setdefault(span.term, None)
        return tuple(seen)


def terms(query: str) -> list[str]:
    """The query words worth locating, lower-cased, in order, deduplicated."""
    out: list[str] = []
    for match in WORD.finditer(query.lower()):
        token = match.group(0)
        if token in STOPWORDS or len(token) < MIN_LENGTH:
            continue
        if token not in out:
            out.append(token)
    return out


def _equivalent(token: str, term: str) -> bool:
    """Same word, allowing only a plural `s`/`es`/`ies`.

    Not a stemmer, and the restraint is the point — see the module docstring.
    `symbol`/`symbols` is the same term of art; `packing`/`packaged` is not.
    """
    if token == term:
        return True
    short, long_ = sorted((token, term), key=len)
    if not long_.startswith(short[:-1] if long_.endswith("ies") else short):
        return False
    remainder = long_[len(short) :]
    return bool(remainder) and bool(_PLURAL.fullmatch(remainder))


def find_spans(text: str, query: str) -> tuple[Span, ...]:
    """Every whole-word occurrence in `text` of a meaningful term from `query`."""
    wanted = terms(query)
    if not wanted:
        return ()
    spans: list[Span] = []
    for match in WORD.finditer(text):
        token = match.group(0).lower()
        for term in wanted:
            if _equivalent(token, term):
                spans.append(Span(match.start(), match.end(), term))
                break
    return tuple(spans)


def passage(text: str, query: str) -> Passage:
    """Mark a retrieved clause against the question that retrieved it."""
    wanted = terms(query)
    spans = find_spans(text, query)
    found = {span.term for span in spans}
    coverage = len(found) / len(wanted) if wanted else 0.0
    return Passage(text=text, spans=spans, coverage=coverage)


def segments(passage: Passage) -> list[tuple[str, bool]]:
    """The passage as `(text, is_match)` runs, for a renderer to lay out.

    Reconstructing the original by concatenating the first elements is an
    invariant the tests check, because the whole discipline of this module is
    that the statute survives the round trip unchanged.
    """
    out: list[tuple[str, bool]] = []
    cursor = 0
    for span in passage.spans:
        if span.start > cursor:
            out.append((passage.text[cursor : span.start], False))
        out.append((passage.text[span.start : span.end], True))
        cursor = span.end
    if cursor < len(passage.text):
        out.append((passage.text[cursor:], False))
    return out


__all__ = [
    "MIN_LENGTH",
    "STOPWORDS",
    "Passage",
    "Span",
    "find_spans",
    "passage",
    "segments",
    "terms",
]
