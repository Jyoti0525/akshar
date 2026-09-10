"""`min_contrast` — Rule 9(1)(b) legibility, and Rule 18(5) defacement.

Two rules share this check because they measure the same thing and differ only
in threshold, respondent and precondition:

    LMPC.CONTRAST.NUMERALS   Rule 9(1)(b)   ratio 3.0   respondent: manufacturer
    LMPC.MRP.DEFACED         Rule 18(5)     ratio 2.0   respondent: DEALER

The second is the retailer's offence, not the manufacturer's — a different
person is named on the notice — and it `suppresses:` the first, so one
measurement yields one verdict rather than two.

Rule 9(1)(b) is skipped on blown, moulded, glass and formed-plastic surfaces,
where the declaration is part of the container and has no ink contrast to
measure. Flagging those would be flagging physics.

This check is also one of the three "misleading" cases the problem statement
asks for: the law treats an illegible declaration as a violation, so low
contrast is a deception finding as much as a readability one.
"""

from __future__ import annotations

from contracts import DeclarationSet, PackageContext, VerdictStatus
from rules.checks._common import category_blocks, condition_blocks, measured_for
from rules.models import CheckOutcome, Rule, Rulepack

_TOLERANCE = 0.2
"""Contrast is estimated from pixel statistics under shop lighting. A result
this close to the threshold is REVIEW, not FAIL."""


def check(rule: Rule, ds: DeclarationSet, ctx: PackageContext, pack: Rulepack) -> CheckOutcome:
    for blocker in (category_blocks(rule, ctx), condition_blocks(rule, ctx)):
        if blocker is not None:
            return CheckOutcome.not_applicable(blocker)

    skip = rule.opt("skip_if") or {}
    if ctx.surface in (skip.get("surface_in") or []):
        return CheckOutcome.not_applicable(
            f"The declaration is formed in the {ctx.surface} container itself, "
            f"so there is no printed contrast to measure."
        )

    if not ds.has_pixels():
        return CheckOutcome.no_data("A text listing has no pixels to measure contrast on.")

    threshold = float(rule.opt("min_ratio", 3.0))
    fields = rule.target_fields()
    primary = fields[0] if fields else None

    declarations = measured_for(ds, fields)
    if not declarations:
        return CheckOutcome.no_data("Declaration not read; its absence is reported separately.")

    measured = [d.contrast_ratio for d in declarations if d.contrast_ratio is not None]
    if not measured:
        return CheckOutcome.no_data("Contrast was not measured for this declaration.")

    worst = min(measured)
    status: VerdictStatus
    if worst >= threshold:
        status = "PASS"
    elif worst + _TOLERANCE >= threshold:
        status = "REVIEW"
    else:
        status = "FAIL"

    return CheckOutcome(
        status=status,
        found=f"{worst:.2f}:1",
        expected=f">= {threshold:g}:1",
        measured=worst,
        threshold=threshold,
        unit="ratio",
        tolerance=_TOLERANCE,
        field_name=primary,
    )
