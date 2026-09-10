"""`in_table` — Rule 5 (Second Schedule) and Rule 12(2) (Fourth Schedule).

Two schedule lookups share this check:

    LMPC.PACK.STANDARD_SIZE      Rule 5, Second Schedule   -> standard_pack_sizes
    LMPC.QTY.UNIT_BY_COMMODITY   Rule 12(2), Fourth Sch.   -> unit_by_commodity

Both are keyed on the commodity category, and both are violations no human
inspector remembers to check — curd must be declared by weight, ready-made
garments by number, tyres by number.

Two safety behaviours, because both schedules are transcribed from gazette
extracts rather than read page by page:

*   A commodity that is not listed returns NOT_APPLICABLE, never FAIL. The
    schedules govern named commodities; silence is not prohibition.
*   Where the rulepack marks a table or an entry as `pending_gazette` /
    `confirmed: false`, a mismatch returns REVIEW rather than FAIL. We do not
    accuse a manufacturer on a value nobody on the team has read in the gazette.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from contracts import DeclarationSet, PackageContext
from rules.checks._common import category_blocks, measured_for
from rules.models import CheckOutcome, Rule, Rulepack
from rules.quantity import parse_quantity

_DIMENSION_OF_UNIT: dict[str, str] = {
    "mg": "weight",
    "g": "weight",
    "kg": "weight",
    "t": "weight",
    "ml": "volume",
    "l": "volume",
    "cm": "length",
    "mm": "length",
    "m": "length",
    "U": "number",
    "N": "number",
}


@dataclass(frozen=True, slots=True)
class _SizeRules:
    """The Second Schedule for one commodity, expanded into decidable parts."""

    literals: set[float]
    steps: list[float]
    """Open-ended "and thereafter in multiples of N" clauses."""
    free_below: float | None = None
    """"Below 50 g no restriction"."""
    step_below: tuple[float, float] | None = None
    """"Below 50 g in multiples of 10 g" -> (ceiling, step)."""
    free_above: float | None = None
    """"No restriction above 4 litre"."""


def _expand_sizes(entries: list[Any]) -> _SizeRules:
    """Expand the Second Schedule grammar.

    Grammar (documented in the rulepack, transcribed from GSR 202(E) pp. 29-32):
        "+100 to 1000"  -> steps of 100, from the last literal up to 1000
        "+1000"         -> any positive multiple of 1000 above the last literal
        "<50 free"      -> below 50, no restriction
        "<50 step 10"   -> below 50, any multiple of 10
        ">4000 free"    -> above 4000, no restriction
    """
    literals: set[float] = set()
    steps: list[float] = []
    free_below: float | None = None
    step_below: tuple[float, float] | None = None
    free_above: float | None = None
    last_literal = 0.0

    for entry in entries:
        if isinstance(entry, (int, float)):
            literals.add(float(entry))
            last_literal = max(last_literal, float(entry))
            continue
        if not isinstance(entry, str):
            continue

        if entry.startswith("+"):
            body = entry[1:].strip()
            if " to " in body:
                step_s, ceil_s = body.split(" to ", 1)
                step, ceiling = float(step_s), float(ceil_s)
                value = last_literal + step
                while value <= ceiling:
                    literals.add(value)
                    value += step
                last_literal = max(last_literal, ceiling)
            else:
                steps.append(float(body))

        elif entry.startswith("<"):
            body = entry[1:].strip()
            if body.endswith("free"):
                free_below = float(body.removesuffix("free").strip())
            elif " step " in body:
                ceil_s, step_s = body.split(" step ", 1)
                step_below = (float(ceil_s), float(step_s))

        elif entry.startswith(">") and entry.endswith("free"):
            free_above = float(entry[1:].removesuffix("free").strip())

    return _SizeRules(
        literals=literals,
        steps=steps,
        free_below=free_below,
        step_below=step_below,
        free_above=free_above,
    )


def _check_pack_size(
    rule: Rule, entry: Any, qty_base: float | None, pending: bool
) -> CheckOutcome:
    if qty_base is None:
        return CheckOutcome.no_data("Net quantity could not be reduced to a comparable value.")

    sizes = _expand_sizes(list(entry))
    literals = sizes.literals

    def _passes() -> bool:
        if qty_base in literals:
            return True
        # "Below 50 g no restriction"
        if sizes.free_below is not None and qty_base < sizes.free_below:
            return True
        # "Below 50 g in multiples of 10 g"
        if sizes.step_below is not None:
            ceiling, step = sizes.step_below
            if qty_base < ceiling and abs(qty_base % step) < 1e-9:
                return True
        # "No restriction above 4 litre"
        if sizes.free_above is not None and qty_base > sizes.free_above:
            return True
        # "and thereafter in multiples of N"
        base = max(literals) if literals else 0.0
        return any(
            qty_base > base and abs((qty_base - base) % step) < 1e-9 for step in sizes.steps
        )

    if _passes():
        return CheckOutcome(status="PASS", found=f"{qty_base:g}", expected="a standard quantity")

    nearest = min(literals, key=lambda v: abs(v - qty_base)) if literals else None
    return CheckOutcome(
        status="REVIEW" if pending else "FAIL",
        found=f"{qty_base:g}",
        expected="a quantity prescribed by the Second Schedule"
        + (f" (nearest prescribed: {nearest:g})" if nearest is not None else ""),
        measured=qty_base,
        detail=(
            "The Second Schedule in this rulepack is an extract; confirm against "
            "the gazette before issuing a notice."
            if pending
            else None
        ),
    )


def _check_unit(rule: Rule, entry: dict[str, Any], unit: str | None, pending: bool) -> CheckOutcome:
    if unit is None:
        return CheckOutcome.no_data("No unit was parsed from the net quantity declaration.")

    allowed = entry.get("unit")
    allowed_list = [allowed] if isinstance(allowed, str) else list(allowed or [])
    actual = _DIMENSION_OF_UNIT.get(unit)

    if actual is None:
        return CheckOutcome.no_data(f"Unit '{unit}' has no known dimension.")

    unconfirmed = pending or not entry.get("confirmed", False)

    if actual in allowed_list:
        return CheckOutcome(
            status="PASS",
            found=f"{actual} ({unit})",
            expected=" or ".join(allowed_list),
        )

    return CheckOutcome(
        status="REVIEW" if unconfirmed else "FAIL",
        found=f"{actual} ({unit})",
        expected=" or ".join(allowed_list),
        detail=(
            "This Fourth Schedule entry has not been confirmed against the gazette; "
            "flagged for review rather than asserted."
            if unconfirmed
            else None
        ),
    )


def check(rule: Rule, ds: DeclarationSet, ctx: PackageContext, pack: Rulepack) -> CheckOutcome:
    if (blocked := category_blocks(rule, ctx)) is not None:
        return CheckOutcome.not_applicable(blocked)

    table = pack.table(rule.opt("table"))
    if not isinstance(table, dict):
        return CheckOutcome.no_data("Rule references no usable table.")

    pending = table.get("verification") != "gazette_verified"
    entries = table.get("entries", table)

    key = ctx.category
    if key not in entries:
        # The schedules govern named commodities. Silence is not prohibition.
        return CheckOutcome.not_applicable(
            f"Commodity '{key}' is not listed in the schedule this rule applies."
        )

    entry = entries[key]

    fields = rule.target_fields()
    declarations = measured_for(ds, fields)
    text = declarations[0].text if declarations else (ds.raw_text or "")
    parsed = parse_quantity(text)

    if parsed is None and ctx.net_quantity is not None:
        qty_base = ctx.net_quantity.base_g_ml
        unit: str | None = ctx.net_quantity.unit
    elif parsed is not None:
        qty_base, unit = parsed.base_g_ml, parsed.unit
    else:
        return CheckOutcome.no_data("No net quantity could be parsed.")

    outcome = (
        _check_unit(rule, entry, unit, pending)
        if isinstance(entry, dict)
        else _check_pack_size(rule, entry, qty_base, pending)
    )
    return CheckOutcome(
        status=outcome.status,
        found=outcome.found,
        expected=outcome.expected,
        measured=outcome.measured,
        threshold=outcome.threshold,
        tolerance=outcome.tolerance,
        detail=outcome.detail,
        field_name=fields[0] if fields else None,
    )
