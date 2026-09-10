"""`value_in_range` — Rule 13(2)-(3) with National Standards Third Schedule item 10.

"the multiple or sub-multiple shall be so chosen that the numerical value falls
between 0.1 and 1000."

So `0.5 kg` should be `500 g`, and `1500 g` should be `1.5 kg`. Trivial to
check, invisible to the eye, and no human inspector remembers to do it.

This is a check rather than a regex because it needs the PARSED number: a
pattern can tell you the digits are there but not that their magnitude is wrong.

Section 13a: this rule is also what we built INSTEAD of the comma-separator
check. Both the Numeration Rules and the National Standards Rules prohibit
comma grouping, but enforcing it would fire on every product in India, and a
four-digit quantity that would need grouping is already a violation of item 10.
Flagging the comma would be flagging a symptom. A team that can explain why it
declined to ship a finding reads better than one that ships it.
"""

from __future__ import annotations

from contracts import DeclarationSet, PackageContext
from rules.checks._common import category_blocks, measured_for
from rules.models import CheckOutcome, Rule, Rulepack
from rules.quantity import parse_quantity


def check(rule: Rule, ds: DeclarationSet, ctx: PackageContext, pack: Rulepack) -> CheckOutcome:
    if (blocked := category_blocks(rule, ctx)) is not None:
        return CheckOutcome.not_applicable(blocked)

    fields = rule.target_fields()
    primary = fields[0] if fields else None

    declarations = measured_for(ds, fields)
    text = declarations[0].text if declarations else (ds.raw_text or "")
    parsed = parse_quantity(text)

    if parsed is not None:
        value, unit, base = parsed.value, parsed.unit, parsed.base_g_ml
    elif ctx.net_quantity is not None:
        value = ctx.net_quantity.value
        unit = ctx.net_quantity.unit
        base = ctx.net_quantity.base_g_ml
    else:
        return CheckOutcome.no_data("No numerical quantity could be parsed.")

    low = float(rule.opt("min_value", 0.1))
    high = float(rule.opt("max_value", 1000))

    # Arm 1 — National Standards Third Schedule item 10: the numerical value
    # itself must fall in [0.1, 1000). This is what catches `1500 g`, and it is
    # the upper bound the rule was missing before.
    if not (low <= value < high):
        suggestion = "a larger multiple" if value >= high else "a smaller sub-multiple"
        return CheckOutcome(
            status="FAIL",
            found=f"{value:g} {unit}",
            expected=f"numerical value in [{low:g}, {high:g}) — use {suggestion}",
            measured=value,
            threshold=high if value >= high else low,
            field_name=primary,
        )

    # Arm 2 — LMPC Rule 13(2)-(3): unit SELECTION by magnitude. Under one
    # kilogram must be expressed in grams; under one litre in millilitres.
    # This is what catches `0.5 kg`, which passes arm 1 perfectly happily and
    # is still non-compliant.
    prescribed = _prescribed_unit(unit, base)
    if prescribed is not None and prescribed != unit:
        return CheckOutcome(
            status="FAIL",
            found=f"{value:g} {unit}",
            expected=f"the quantity expressed in {prescribed}",
            measured=value,
            detail=(
                "Rule 13(2)-(3): a quantity below one kilogram is declared in grams, "
                "and below one litre in millilitres."
            ),
            field_name=primary,
        )

    return CheckOutcome(
        status="PASS",
        found=f"{value:g} {unit}",
        expected=f"numerical value in [{low:g}, {high:g}) in the prescribed unit",
        measured=value,
        field_name=primary,
    )


_SUB_UNIT = {"kg": "g", "l": "ml"}
"""The unit that must be used below the multiple's own threshold."""


def _prescribed_unit(unit: str, base_g_ml: float | None) -> str | None:
    """Which unit Rule 13(2)-(3) requires for this magnitude, if it says.

    Returns None where the rule is silent — counts, lengths, and quantities in
    milligrams, which the sub-rule does not reach.
    """
    if base_g_ml is None:
        return None
    if unit in _SUB_UNIT and base_g_ml < 1000:
        return _SUB_UNIT[unit]
    if unit == "g" and base_g_ml >= 1000:
        return "kg"
    if unit == "ml" and base_g_ml >= 1000:
        return "l"
    return None
