"""`clear_space` — Rule 8(1) proviso, the net quantity exclusion zone. SCALE-FREE.

"the area surrounding the net quantity declaration shall be free of printed
information" -- at least one numeral height above and below, and two numeral
heights to the left and right.

Like `min_width_ratio`, this compares gaps in pixels against a numeral height
in pixels, so it needs no marker and no millimetres. It is the second of the two
rules that survive total failure of scale recovery.

Nobody else builds this, because nobody else has panel geometry to build it on.
"""

from __future__ import annotations

import re

from contracts import Box, Declaration, DeclarationSet, PackageContext
from rules.checks._common import category_blocks, measured_for
from rules.models import CheckOutcome, Rule, Rulepack

_SUBSTANTIVE = re.compile(r"[A-Za-zऀ-ॿ]{3,}|\d{2,}")
"""What counts as printed information intruding on the clear space.

The proviso is about *printed information* crowding the declaration, and this
check can only see what the detector proposed. B2 ships with no trained weights
today -- every scan logs `geometry-only region proposal` -- so a good number of
those proposals are one or two characters of nothing. Measured on the field
corpus 2026-09-10, the intrusions being reported read:

    13 intrusion(s): 14; s; a

An `s` is not printed information. Reporting a manufacturer for crowding their
net quantity with it is a finding about our segmentation wearing the clothes of
a finding about their pack. A fragment has to look like a word or a number
before it can be said to occupy the space.
"""


def _zone(box: Box, vertical: float, horizontal: float) -> tuple[float, float, float, float]:
    """The rectangle that must be clear, as (x1, y1, x2, y2).

    Multiples are of the NUMERAL height, per the proviso.
    """
    dy = vertical * box.h
    dx = horizontal * box.h
    return (box.x - dx, box.y - dy, box.x2 + dx, box.y2 + dy)


def _intrudes(zone: tuple[float, float, float, float], other: Box) -> bool:
    x1, y1, x2, y2 = zone
    return not (other.x2 <= x1 or other.x >= x2 or other.y2 <= y1 or other.y >= y2)


def check(rule: Rule, ds: DeclarationSet, ctx: PackageContext, pack: Rulepack) -> CheckOutcome:
    if (blocked := category_blocks(rule, ctx)) is not None:
        return CheckOutcome.not_applicable(blocked)

    if not ds.has_pixels():
        return CheckOutcome.no_data("A text listing has no layout geometry.")

    fields = rule.target_fields()
    primary = fields[0] if fields else None
    subjects: list[Declaration] = measured_for(ds, fields)
    if not subjects:
        return CheckOutcome.no_data("Declaration not read; its absence is reported separately.")

    vertical = float(rule.opt("vertical_multiple", 1.0))
    horizontal = float(rule.opt("horizontal_multiple", 2.0))

    worst: CheckOutcome | None = None

    for subject in subjects:
        # The proviso measures from the NUMERALS, not from the whole
        # declaration including any qualifier text.
        anchor = subject.numeral_box or subject.box
        zone = _zone(anchor, vertical, horizontal)

        intruders: list[str] = []
        for other in ds.declarations:
            if other is subject:
                continue
            # Printed information intrudes on a clear space by being printed
            # NEXT TO IT. A line read from a different photograph is not next to
            # anything here: `Box` lives in rectified label space and each
            # photograph has its own, so two boxes from two frames overlap or
            # miss by coincidence. Without this filter a second shot of the pack
            # would invent intrusions, and this rule is already 40% of the
            # blocking FAILs on the field corpus. Same reasoning as the
            # `panel_id` test below, one level up.
            if other.frame_id != subject.frame_id:
                continue
            # The declaration's own label, printed beside its figure and
            # demoted to `other` by `vision.classify.associate`, sits inside
            # the subject's box and a numeral-box anchor does not exclude it.
            # "Net Wt." is not information intruding on `500 g`; it is part of
            # the same declaration.
            if other.box.intersects(subject.box):
                continue
            if not _SUBSTANTIVE.search(other.text):
                continue  # not printed information -- see `_SUBSTANTIVE`
            # Text on another panel cannot intrude on this panel's clear space.
            if (
                anchor.panel_id
                and other.box.panel_id
                and anchor.panel_id != other.box.panel_id
            ):
                continue
            if other.box.intersects(anchor):
                continue  # overlapping boxes are the same declaration read twice
            if _intrudes(zone, other.box):
                intruders.append(other.text[:30])

        if intruders:
            outcome = CheckOutcome(
                status="FAIL",
                found=f"{len(intruders)} intrusion(s): " + "; ".join(intruders[:3]),
                expected=(
                    f">= {vertical:g}x numeral height clear above and below, "
                    f"{horizontal:g}x to the left and right"
                ),
                measured=float(len(intruders)),
                threshold=0.0,
                field_name=primary,
                detail="Compared in pixels; this check needs no scale recovery.",
            )
        else:
            outcome = CheckOutcome(
                status="PASS",
                expected=(
                    f">= {vertical:g}x numeral height clear above and below, "
                    f"{horizontal:g}x to the left and right"
                ),
                measured=0.0,
                threshold=0.0,
                field_name=primary,
                detail="Compared in pixels; this check needs no scale recovery.",
            )

        rank = {"FAIL": 0, "REVIEW": 1, "NO_DATA": 2, "PASS": 3}
        if worst is None or rank[outcome.status] < rank[worst.status]:
            worst = outcome

    return worst or CheckOutcome.no_data("No declaration to measure.")
