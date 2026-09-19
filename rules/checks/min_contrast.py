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

import re

from contracts import DeclarationSet, PackageContext, VerdictStatus
from rules.checks._common import category_blocks, condition_blocks, measured_for
from rules.models import CheckOutcome, Rule, Rulepack

_TOLERANCE = 0.2
"""Contrast is estimated from pixel statistics under shop lighting. A result
this close to the threshold is REVIEW, not FAIL."""

_NUMERAL = re.compile(r"\d")
"""Any decimal digit in any script.

Python's `\\d` is Unicode-aware on a `str`, so the Devanagari digits are digits
here without a second pattern. A pack that prints its price in them has printed
its price, and a script-shaped hole in Rule 9(1)(b) is not something this
project ships."""


def _has_numerals(text: str | None) -> bool:
    return bool(text) and _NUMERAL.search(text or "") is not None


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

    if rule.opt("requires_numerals", False):
        # ---------------------------------------------------------------------
        # THE FALSE ACCUSATION THIS PREVENTS
        # ---------------------------------------------------------------------
        # A face serum carton, scanned live on 2026-09-19, was failed under
        # Rule 9(1)(b) at 1.888:1 against a threshold of 3.000:1. The crop that
        # number was computed on read `MRP: ₹` -- the caption, and nothing else.
        # The figures were printed on an inkjet-coded label to its right, came
        # back from the detector as one 385 px block, and were never read at
        # all (see `vision/ocr/rows.py`).
        #
        # So the pack was told its price was illegible on the evidence of a
        # measurement taken somewhere the price is not. Both rules that use this
        # check are about the FIGURES -- 9(1)(b) says so in the gazette, and
        # 18(5) is about a price obliterated or altered -- and a caption is not
        # a figure. Where the digits were not read, there is nothing here to
        # measure and the honest answer is that we have no data, which is also
        # the answer that cannot convict anybody of our own OCR failure.
        #
        # The declaration's ABSENCE is a separate finding under the presence
        # rules, and it still fires. Only the legibility verdict is withdrawn.
        with_numerals = [d for d in declarations if _has_numerals(d.text)]
        if not with_numerals:
            return CheckOutcome.no_data(
                "Only the caption of this declaration was read, not its figures, so there "
                "are no numerals to measure the contrast of. Photograph the panel again "
                "with the printed value filling more of the frame."
            )
        declarations = with_numerals

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
