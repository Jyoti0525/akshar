"""`min_height_mm` — Rule 7(2) Tables I and II, Rule 7(3).

This is the check the whole project exists to make possible. Nobody else
measures printed character height from a photograph; every commercial tool
reads it out of an artwork file where it is already a stored number.

Three rules use it, and they are the ONLY three that go dark at scale tier C.
The other twenty-eight run with no scale recovery at all.

Two behaviours here are legally load-bearing:

*   When `mm_per_px` is absent the answer is NO_DATA, never FAIL. Absence of
    evidence is not evidence of a violation.
*   A measurement within tolerance of the threshold is REVIEW, not FAIL.
    Convicting on a 0.1 mm margin would be dismantled in court, and a sharp
    judge will ask about exactly this.
"""

from __future__ import annotations

from contracts import Declaration, DeclarationSet, PackageContext, VerdictStatus
from rules.checks._common import bilingual_group, category_blocks, measured_for
from rules.models import CheckOutcome, Rule, Rulepack
from rules.quantity import parse_quantity

_DEFAULT_TOLERANCE_MM = 0.15
"""Used when the extractor did not propagate a per-declaration tolerance.
Matches the tier A acceptance criterion of M2 (mean absolute error <= 0.15 mm),
so the REVIEW band is never narrower than our own measurement error."""


def _threshold_from_table(
    rule: Rule, ds: DeclarationSet, ctx: PackageContext, pack: Rulepack
) -> tuple[float | None, str]:
    """Resolve the required height in millimetres.

    Rule 7(2)(i) Table I is keyed on NET QUANTITY, not on label area. Getting
    that backwards is the most consequential error available in this project.
    Table II (PDP area) applies only where quantity is declared by length,
    area or number, so there is no gram or millilitre figure to band on.
    """
    variant = "embossed" if ctx.declaration_style == "embossed" else "normal"

    # Rule 7(3): a flat 1 mm floor for the ordinary declarations.
    fixed = rule.opt("fixed_mm")
    if fixed:
        return float(fixed[variant]), f"{rule.rule_ref} ({variant})"

    qty = ctx.net_quantity
    if qty is None:
        decl = ds.first("net_quantity")
        match = parse_quantity(decl.text) if decl else None
        qty = match.to_parsed() if match else None

    # Table I — banded on net quantity in g/ml.
    if qty is not None and qty.base_g_ml is not None:
        table = pack.table(rule.opt("table")) or []
        for band in table:
            ceiling = band.get("max_g_ml")
            if ceiling is None or qty.base_g_ml <= ceiling:
                key = "embossed_mm" if variant == "embossed" else "normal_mm"
                return float(band[key]), f"{rule.rule_ref}, {qty.base_g_ml:g} g/ml band"
        return None, "no band matched"

    # Table II — banded on principal display panel area.
    fallback = pack.table(rule.opt("fallback_table")) or []
    area = ds.geometry.label_area_cm2
    if fallback and area is not None:
        for band in fallback:
            ceiling = band.get("max_area_cm2")
            if ceiling is None or area <= ceiling:
                key = "embossed_mm" if variant == "embossed" else "normal_mm"
                return float(band[key]), f"Rule 7(2), Table II, {area:g} cm2 band"

    return None, "neither net quantity nor panel area is known"


def _tallest(group: list[Declaration]) -> Declaration:
    """Rule 9(4): on a bilingual pack either script may satisfy the height.

    So we take the maximum rather than flagging the smaller instance -- the
    same declaration printed twice at two sizes is compliant if the larger one
    clears the bar.
    """
    return max(group, key=lambda d: (d.height_mm or 0.0, d.height_for_rules_px))


def check(rule: Rule, ds: DeclarationSet, ctx: PackageContext, pack: Rulepack) -> CheckOutcome:
    if (blocked := category_blocks(rule, ctx)) is not None:
        return CheckOutcome.not_applicable(blocked)

    fields = rule.target_fields()
    primary = fields[0] if fields else None

    # Rule 7(4): where another statute mandates the same information, the
    # height rules of these rules do not apply to it.
    if primary and primary in ctx.other_law_mandates:
        return CheckOutcome.not_applicable(
            "Rule 7(4): another statute mandates this information, so these height rules do not apply."
        )

    if not ds.has_pixels():
        return CheckOutcome.no_data(
            "A text listing has no pixels; height cannot be measured from it."
        )

    if not ds.has_scale():
        # See `DeclarationSet.has_scale`. Each declaration was converted to
        # millimetres at the scale of the frame it was read from, so what
        # decides whether this rule can run is whether ANY frame recovered one.
        return CheckOutcome.no_data(
            "No scale was recovered (tier C): height in millimetres is unknown. "
            "The scale-free geometric checks still ran."
        )

    threshold, basis = _threshold_from_table(rule, ds, ctx, pack)
    if threshold is None:
        return CheckOutcome.no_data(f"Required height could not be resolved: {basis}.")

    declarations = measured_for(ds, fields)
    if not declarations:
        return CheckOutcome.no_data("Declaration not read; its absence is reported separately.")

    worst: CheckOutcome | None = None
    for group in bilingual_group(declarations, rule.opt("bilingual")):
        best = _tallest(group)
        measured = best.height_mm
        if measured is None:
            outcome = CheckOutcome.no_data("Height was not converted to millimetres.")
        else:
            tol = best.height_mm_tolerance or _DEFAULT_TOLERANCE_MM
            status: VerdictStatus
            if measured >= threshold:
                status = "PASS"
            elif measured + tol >= threshold:
                # Inside our own measurement error. Flag it; do not assert it.
                status = "REVIEW"
            else:
                status = "FAIL"
            outcome = CheckOutcome(
                status=status,
                found=f"{measured:.2f} mm",
                expected=f">= {threshold:g} mm ({basis})",
                measured=measured,
                threshold=threshold,
                tolerance=tol,
                field_name=best.field,
            )

        rank = {"FAIL": 0, "REVIEW": 1, "NO_DATA": 2, "PASS": 3}
        if worst is None or rank[outcome.status] < rank[worst.status]:
            worst = outcome

    return worst or CheckOutcome.no_data("No measurable declaration.")
