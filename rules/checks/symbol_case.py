"""`symbol_case` — National Standards Third Schedule item 7(2).

"unit symbols shall be printed in lower case, unless the unit is named after a
person."

`250 ML` is printed on an enormous number of Indian packs and it is not the
prescribed symbol; `ml` is. The proper-name carve-out is why `N` (newton),
`Pa` (pascal), `A` (ampere) and `K` (kelvin) keep their capital, so it must be
an exception list rather than a blanket lower-case rule.

There is a second list, and it exists because this rule contradicted the
rulepack. `LMPC.UNIT.LITRE_SYMBOL` ships `enabled: false` -- the gazette gives
`l`, BIPM accepts `L`, and the pack takes the view that reporting it would be
wrong. This check reached the same `L` through `_MASS_VOLUME_LENGTH` and failed
it regardless, so `Net Content: 1L (905 g)` on an Amul ghee tin was a finding
in spite of the rule against it being switched off. `disputed_symbols_ref`
names the same decision so it is made once.

Severity `low` and `advisory: true`. These are formatting defects, and a tool
that reports `250 ML` at the same severity as a missing MRP is a tool an
officer stops trusting.

Most teams will read the Packaged Commodities Rules. The rules that say how a
unit symbol must actually be PRINTED are in the National Standards Rules,
Third Schedule — a 79-page gazette about national measurement standards that
looks entirely irrelevant to package labels, and is where five of our checks
come from.
"""

from __future__ import annotations

import re

from contracts import DeclarationSet, PackageContext
from rules.checks._common import category_blocks, field_text, strict_text
from rules.models import CheckOutcome, Rule, Rulepack
from rules.quantity import normalise_digits

_SYMBOL_AFTER_NUMBER = re.compile(r"(?<=[\d\s])(?P<sym>[A-Za-z]{1,3})(?![A-Za-z])")
"""Candidate unit symbols: a short alphabetic run following a digit or a space.
Deliberately narrow — we are not parsing the whole label, only looking at the
token sitting where a unit symbol belongs."""

_MASS_VOLUME_LENGTH = frozenset({"mg", "g", "kg", "t", "ml", "l", "cm", "mm", "m"})
"""Symbols that must be lower case. Restricting to these means a stray capital
word after a number is never reported as a mis-cased unit."""

_ALL_KNOWN = _MASS_VOLUME_LENGTH | {
    "n", "pa", "a", "k", "w", "j", "v", "hz", "c", "t", "wb", "s", "f", "bq", "gy", "sv",
}


def check(rule: Rule, ds: DeclarationSet, ctx: PackageContext, pack: Rulepack) -> CheckOutcome:
    if (blocked := category_blocks(rule, ctx)) is not None:
        return CheckOutcome.not_applicable(blocked)

    exceptions = set(pack.table(rule.opt("proper_name_exceptions_ref")) or [])

    # Symbols this pack has already decided not to report on. `L` is the whole
    # of it today: `LMPC.UNIT.LITRE_SYMBOL` ships disabled because BIPM accepts
    # the capital, and this rule was reaching the same symbol by another route
    # and failing `Net Content: 1L (905 g)` anyway. A rulepack that disables a
    # finding in one rule and raises it in the next is not one an officer can
    # be asked to defend, so the decision is read from the pack rather than
    # duplicated here.
    disputed = set(pack.table(rule.opt("disputed_symbols_ref")) or [])
    fields = rule.target_fields()
    primary = fields[0] if fields else None

    # The declaration, not the label. Same reasoning as `regex_absent`, and the
    # same measurement found it: over 40 corpus frames this rule raised four
    # findings -- a bare `G` and three bare `M`s -- on frames where no net
    # quantity had been classified at all, because `strict_text` fell back to
    # the whole label's raw text. `_SYMBOL_AFTER_NUMBER` is deliberately narrow
    # and it is still not narrow enough to survive being pointed at a nutrition
    # panel, a batch code and a brand name at once.
    #
    # `scope: label` is the opt-in, matching `regex_absent`. No shipped rule
    # sets it.
    source = strict_text(ds, fields) if rule.opt("scope") == "label" else field_text(ds, fields)
    if not source.strip():
        return CheckOutcome.no_data(
            "This declaration was not read, so nothing can be said about how its "
            "unit symbol is printed. Its absence is reported separately."
        )
    text = normalise_digits(source)
    if not text.strip():
        return CheckOutcome.no_data("No text was read for this field.")

    offenders: list[str] = []
    for match in _SYMBOL_AFTER_NUMBER.finditer(text):
        symbol = match.group("sym")
        lowered = symbol.lower()

        if lowered not in _ALL_KNOWN:
            continue
        if symbol in exceptions:  # named after a person: the capital is correct
            continue
        if symbol in disputed:  # the pack declines to report on this one
            continue
        if symbol != lowered and lowered in _MASS_VOLUME_LENGTH:
            offenders.append(symbol)

    if offenders:
        unique = sorted(set(offenders))
        return CheckOutcome(
            status="FAIL",
            found=", ".join(unique[:5]),
            expected="lower case, e.g. " + ", ".join(s.lower() for s in unique[:5]),
            field_name=primary,
        )

    return CheckOutcome(
        status="PASS",
        expected="unit symbols in lower case unless named after a person",
        field_name=primary,
    )
