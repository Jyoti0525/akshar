"""`regex_absent` — a prohibited word, unit or spelling must not appear IN A DECLARATION.

Carries Rule 12(6) banned qualifiers, Rule 13(4) banned number units,
Rule 11(4) "when packed", the four National Standards unit-symbol printing
defects, and the Numeration Rules digit form.

The five unit-symbol rules are severity `low` and `advisory: true`. They are
formatting defects, not consumer deception, and a tool that reports `250 ML`
at the same severity as a missing MRP is a tool an officer stops trusting.

---------------------------------------------------------------------------
IT SEARCHES THE DECLARATION, NEVER THE WHOLE LABEL
---------------------------------------------------------------------------
This check used to fall back to `ds.raw_text` when the classifier had not
identified the field it targets, via `strict_text`. That fallback is right for
`regex` — a *format* rule still wants to judge whatever MRP-shaped text is on
the pack — and it is wrong here, because every one of these eight rules asks
"does this forbidden thing appear **in this declaration**", and a label is
covered in text that is not that declaration.

Measured on 2026-09-09 over 40 corpus frames
(`scripts/advisory_false_positives.py`): 13 advisory findings were raised, and
**11 of them had no classified net quantity at all**. `SYMBOL_CASE` fired on a
bare `'G'` and three bare `'M'`s lifted out of unrelated words. `SYMBOL_SPACE`
fired on `'16g'` from a nutrition panel's serving size and on `'0g'` fragments.
`DIGIT_FORM` fired on Devanagari numerals printed somewhere in the Hindi text,
which is lawful and was never in a net quantity declaration.

The non-advisory rules had the same defect and it matters more there:
`LMPC.QTY.WHEN_PACKED` would report a packet as declaring its quantity at the
time of packing because the words "when packed" appeared anywhere on the
label — a real allegation, from a string in the wrong place.

So when the target field was not read, this check now returns **NO_DATA**.
Section 8b: absence of evidence is not evidence of a violation. We did not read
the net quantity declaration; we therefore cannot say what is or is not printed
inside it.

`scope: label` restores the old behaviour for any future rule that genuinely
means "nowhere on the pack". Nothing sets it today, and a rule that does should
say so in the YAML where a reviewer can see it.
"""

from __future__ import annotations

from contracts import DeclarationSet, PackageContext
from rules.checks._common import (
    category_blocks,
    condition_blocks,
    field_text,
    source_blocks,
    strict_text,
)
from rules.models import CheckOutcome, Rule, Rulepack


def check(rule: Rule, ds: DeclarationSet, ctx: PackageContext, pack: Rulepack) -> CheckOutcome:
    for blocker in (
        category_blocks(rule, ctx),
        source_blocks(rule, ds),
        condition_blocks(rule, ctx),
    ):
        if blocker is not None:
            return CheckOutcome.not_applicable(blocker)

    pattern = pack.pattern(rule.opt("pattern_ref"))
    if pattern is None:
        return CheckOutcome.no_data("Rule defines no pattern.")

    fields = rule.target_fields()
    primary = fields[0] if fields else None

    # `scope: label` is the opt-in for the old whole-label search. See the
    # module docstring for the false positives that made it opt-in.
    if rule.opt("scope") == "label":
        text = strict_text(ds, fields)
    else:
        text = field_text(ds, fields)
        if not text.strip():
            return CheckOutcome.no_data(
                "This declaration was not read, so nothing can be said about what is "
                "printed inside it. Its absence is reported separately."
            )

    if not text.strip():
        return CheckOutcome.no_data("No text was read for this field.")

    hits = sorted(set(pattern.findall(text)))
    if hits:
        return CheckOutcome(
            status="FAIL",
            found=", ".join(hits[:5])[:120],
            expected=f"absent, per {rule.rule_ref}",
            field_name=primary,
        )

    return CheckOutcome(
        status="PASS",
        expected=f"absent, per {rule.rule_ref}",
        field_name=primary,
    )
