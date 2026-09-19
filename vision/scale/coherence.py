"""Does the scale survive contact with what it measured?

Every other check on the entered pack height happens *before* the photograph is
read: the plausibility band in `operator.py`, the cross-check against a marker
in `resolve.py`, the cross-check against a stored SKU dimension. All three ask
"is this number believable on its own?" and none of them can catch the failure
that actually happened.

---------------------------------------------------------------------------
WHAT HAPPENED, ON 2026-09-19, TO A GLUCON-D 250 g JAR
---------------------------------------------------------------------------
The officer typed **20** for a jar about 150 mm tall. Twenty millimetres is a
perfectly plausible height — a sachet strip is 20 mm — so the band passed it.
There was no marker card to disagree with and no stored dimension for the SKU,
so nothing else spoke. The frame was 1280 px tall, giving 0.015625 mm per pixel,
and every letter on the pack came back seven and a half times too small:

    reported   0.38 mm        required  1.00 mm       FAIL
    actually   2.85 mm        required  1.00 mm       compliant

That is a contravention notice against a compliant manufacturer, produced by a
system whose entire reason for existing is not to do that. It is worth being
precise about why none of the existing guards fired: **they all check the
number, and the number was fine. What was wrong was the number applied to this
photograph** — and the only evidence of that lives in the result.

---------------------------------------------------------------------------
THE CHECK
---------------------------------------------------------------------------
Retail packaging is printed by offset, flexo or rotogravure. None of them can
lay down legible type below about half a millimetre, and no packaged commodity
carries a *declaration* set at fifteen. So when the measured print comes back
outside that range, the honest conclusion is not "this pack is printed in
impossible type". It is "the scale is wrong", and the answer is tier C: the
three character-height rules return NO_DATA, and the twenty-eight rules that
never needed a millimetre carry on exactly as before.

**Why the floor is 0.5 mm and not 1.0 mm.** One millimetre is the legal
minimum, so a floor there would suppress every genuine short-print violation —
the check would quietly delete the finding it exists to protect. A pack that
actually breaks Rule 7(3) prints at 0.7 or 0.8 mm, comfortably above the floor
and still reported as the contravention it is. Half a millimetre is below
anything a press produces and above anything a violation looks like, and the
gap between those two is what makes this safe.

**Why the median and not the minimum.** One garbled OCR line measuring 0.1 mm
is an ordinary recogniser error on a pack that is otherwise fine. The scale
being wrong moves *everything* at once, which is exactly what a median sees and
an extreme does not.

**Which way it can be wrong.** If it fires when it should not, a scan that
could have answered three rules answers twenty-eight and refers the rest to a
person. If it fails to fire, nothing is worse than before. There is no setting
of it that invents a contravention, which is the only property that had to hold.
"""

from __future__ import annotations

from collections.abc import Sequence
from statistics import median
from typing import Any

PRINTABLE_MM = (0.5, 15.0)
"""What a printing press can actually put on a packaged commodity.

Wide on purpose, in both directions. The point is to catch a scale that is
wrong by a factor, not to adjudicate typography."""

MIN_MEASUREMENTS = 4
"""Below this a median is not a median. A frame with two measured lines on it
is a bad crop, and bad crops are what the framing gate is for."""


def measured_heights(declarations: Sequence[Any]) -> list[float]:
    """Every millimetre height the read actually produced."""
    heights: list[float] = []
    for declaration in declarations:
        height = getattr(declaration, "height_mm", None)
        if height is not None and height > 0.0:
            heights.append(float(height))
    return heights


def implausible(declarations: Sequence[Any]) -> str | None:
    """A sentence when the scale cannot be reconciled with the print it measured.

    `None` means the measurements are consistent with something a press could
    have printed — which is not a claim that the scale is *right*, only that
    nothing in the result contradicts it.
    """
    heights = measured_heights(declarations)
    if len(heights) < MIN_MEASUREMENTS:
        return None

    middle = median(heights)
    floor, ceiling = PRINTABLE_MM

    if middle < floor:
        return (
            f"The scale makes the printing on this pack {middle:.2f} mm tall, and no "
            f"press prints a declaration that small. The entered height is smaller "
            f"than the face actually photographed, so no measurement is reported. "
            f"Check that the height was measured in millimetres and not centimetres, "
            f"and that it is the face in the photograph rather than a smaller part "
            f"of the package."
        )
    if middle > ceiling:
        return (
            f"The scale makes the printing on this pack {middle:.1f} mm tall, which is "
            f"larger than any declaration is set. Check that the height entered was the "
            f"face in the photograph and not a larger dimension of the package."
        )
    return None


__all__ = ["MIN_MEASUREMENTS", "PRINTABLE_MM", "implausible", "measured_heights"]
