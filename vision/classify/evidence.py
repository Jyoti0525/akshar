"""Weak evidence, combined — for lines the exact patterns could not match.

`regex_tier` asks "does this line match the rulepack's pattern for a field?"
and that is the right question when the line was read correctly. It is the
wrong question when it was not, and on real packs it often is not. The MRP
block on a dev pack comes back like this:

    'MPEE'       the label. 'MRP RS.' -- three edits away, unrecoverable alone
    '559.00'     the amount, read at confidence 1.00
    'otal tes)'  '(incl. of all taxes)' -- clearly that, and matching nothing

Every exact pattern fails, so the whole block is discarded and the pack is
reported as declaring no retail sale price.

So this module scores a line on several weak signals rather than requiring one
strong one. No signal here is sufficient by itself -- a price-shaped number is
also what `Rs. 20 OFF` looks like -- and two independent ones must agree.

**It does not rescue the block above, and the threshold was not lowered until
it did.** `'tes'` is two edits from `'taxes'` on a five-letter word and
`'MPEE'` is three from `'MRP'`; admitting either means tolerating a 40% error
rate inside a token, which is the point where fuzzy matching stops recovering
words and starts inventing them. Only the amount survives, and one signal is
not enough by design. What this recovers is the commoner case where *one* word
of a line is garbled and the rest is intact -- `'Net Qay: 50g'`, where the unit
symbol holds because one or two characters have fewer ways to go wrong. A line
where almost every word is broken is a reading failure, and the answer to a
reading failure is a better recogniser, not a more forgiving matcher.

**This is routing, not deciding.** What comes out is a reason to spend a crop
re-reading a region and to measure what is there. It is deliberately given a
low `field_confidence`, so the strict format rules in the rulepack still judge
the result on its merits and a garbled line cannot become a confident
violation. Section 3's second principle is untouched: the rulepack decides.

**The signals are drawn from the statute, not fitted to a corpus.** Rule 2(m)
requires the retail sale price to be declared inclusive of all taxes, so the
tax phrase is *mandatory* and its presence is evidence rather than a
coincidence worth learning. Rule 13(5) and the Second Schedule fix the unit
symbols, and they are one to two characters, which is why they survive
recognition errors that destroy whole words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field

from contracts import FieldName

MIN_SCORE = 2.0
"""Evidence needed before a line is worth a crop.

Every signal below is worth 1.0, so this requires **two independent signals**.
One is never enough: a price-shaped number alone is `Rs. 20 OFF`, and a stray
`g` after a number alone is half the ingredients list. Two weak signals
agreeing on the same field is a different kind of claim from one weak signal
asserted twice, and requiring agreement is what keeps this from becoming a
guess dressed up as a measurement.
"""


@dataclass(frozen=True, slots=True)
class Evidence:
    score: float
    reasons: list[str] = dc_field(default_factory=list)
    """Which signals fired, in words. Carried into the report so an officer
    disputing a reading sees the same three fragments we saw."""

    @property
    def is_worth_reading(self) -> bool:
        return self.score >= MIN_SCORE


def levenshtein(a: str, b: str) -> int:
    """Edit distance. Small and local rather than a dependency.

    Only ever called on single tokens -- the longest thing compared here is
    "quantity" -- so the quadratic cost is a few hundred operations per line.
    """
    if a == b:
        return 0
    if not a or not b:
        return len(a) or len(b)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            )
        previous = current
    return previous[-1]


def _tolerance(word: str) -> int:
    """How many edits a token of this length may absorb and still count.

    One edit per three characters, so `taxes` tolerates one and `quantity`
    two, and a three-letter token tolerates one. Chosen from the shape of the
    words rather than from a corpus: shorter tokens have fewer ways to be
    wrong, and allowing them the same absolute slack as a long one is how
    fuzzy matching starts finding things that are not there.
    """
    return max(1, len(word) // 3)


def _has_near_token(text: str, word: str) -> bool:
    """Does any token in `text` sit within tolerance of `word`?"""
    limit = _tolerance(word)
    for token in re.findall(r"[^\W\d_]+", text.lower()):
        # Length alone rules most tokens out before the distance is computed.
        if abs(len(token) - len(word)) <= limit and levenshtein(token, word) <= limit:
            return True
    return False


# -- the signals -----------------------------------------------------------

_AMOUNT = re.compile(r"\d{1,3}(?:[,\s]?\d{2,3})*\.\d{1,2}\b")
"""A price-shaped number: Rule 2(m) amounts carry paise, and the decimal is
what separates `559.00` from a batch code, a phone number or a pin code."""

_CURRENCY = re.compile(r"(?i)(?<![A-Za-z])(rs|inr|₹|रु)(?![A-Za-z])")
"""`Rs`, `INR`, the rupee sign, and its Hindi abbreviation."""

_QUANTITY = re.compile(
    r"(?i)\d+(?:\.\d+)?\s?(mg|kg|ml|g|l|cm|mm|m|t|N|U)(?![A-Za-z])"
)
"""A number joined to a lawful unit symbol -- Rule 13(5) and the Second
Schedule. One or two characters, so it survives errors that destroy words."""

_MRP_WORDS = ("mrp", "maximum", "retail", "price", "taxes", "inclusive", "incl")
_NET_WORDS = ("net", "weight", "quantity", "contents", "wt", "qty")


def score(text: str, target: FieldName) -> Evidence:
    """How much this line looks like `target`, when nothing matched exactly.

    Returns an `Evidence` whose `reasons` name each signal that fired. Only
    `mrp` and `net_quantity` are scored: they are the two U1 measures, the two
    with a statutory numeric form to lean on, and the two where a missed
    declaration costs a real check. Everything else returns nothing rather
    than a weak opinion.
    """
    reasons: list[str] = []
    stripped = text.strip()
    if not stripped:
        return Evidence(0.0)

    if target == "mrp":
        if _AMOUNT.search(stripped):
            reasons.append("carries a price-shaped amount with paise")
        if _CURRENCY.search(stripped):
            reasons.append("carries a rupee marker")
        near = [w for w in _MRP_WORDS if _has_near_token(stripped, w)]
        if near:
            reasons.append(f"reads close to {', '.join(near)}")
    elif target == "net_quantity":
        if _QUANTITY.search(stripped):
            reasons.append("carries a number joined to a lawful unit symbol")
        near = [w for w in _NET_WORDS if _has_near_token(stripped, w)]
        if near:
            reasons.append(f"reads close to {', '.join(near)}")
    else:
        return Evidence(0.0)

    return Evidence(float(len(reasons)), reasons)


def best_candidate(texts: list[str], target: FieldName) -> tuple[int, Evidence] | None:
    """The index of the line most likely to be `target`, or None.

    Ties are broken by the earlier line, which on a label is the one nearer the
    top of the panel. That is a weak reason, and it is used only to be
    deterministic: two lines with identical evidence is a case where we should
    read both, and the caller does.
    """
    best: tuple[int, Evidence] | None = None
    for i, text in enumerate(texts):
        found = score(text, target)
        if not found.is_worth_reading:
            continue
        if best is None or found.score > best[1].score:
            best = (i, found)
    return best


__all__ = ["MIN_SCORE", "Evidence", "best_candidate", "levenshtein", "score"]
