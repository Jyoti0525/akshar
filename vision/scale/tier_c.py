"""Scale tier C — no scale at all, and that is a real answer.

    "Tier C returns no `mm_per_px` at all — and the two `scale_free: true`
     rules still run, along with every presence, format, placement and
     unit-symbol check. Only the three `min_height_mm` rules go dark."
                                                    -- section 17, M2

**Build C first.** It needs no props, so it validates rectification, detection,
OCR, classification and the whole rules path before anyone has to print a card
steady. It is also the tier that runs most often in the field, because most
photographs will not have a marker in them.

**Why this is not a failure path.** A system that says "no marker, cannot help"
has thrown away 28 of the 31 rules over a missing prop. At tier C we still
answer: is the MRP there, is it in the prescribed form, is the net quantity on
the principal display panel, is the unit symbol lawful, is the character width
at least a third of its height, is there clear space around the quantity. What
we cannot answer is the three absolute-height questions, and for those the
engine returns NO_DATA — never FAIL, because absence of a measurement is not
evidence of a short one.
"""

from __future__ import annotations

from vision.types import ScaleEstimate

_REASON = (
    "No reference object in frame and no known dimensions for this SKU. "
    "Absolute height rules return NO_DATA; ratio and placement rules are "
    "unaffected."
)


def estimate(detail: str = "") -> ScaleEstimate:
    """The honest no-scale answer.

    `detail` lets the caller record *why* the better tiers declined — "marker
    detected but rejected: edge fit 0.31" is far more useful in a report than
    silence, and it is what tells an officer to retake the photo.
    """
    return ScaleEstimate(
        tier="C",
        mm_per_px=None,
        tolerance=None,
        method="none",
        detail=f"{_REASON} {detail}".strip(),
    )


__all__ = ["estimate"]
