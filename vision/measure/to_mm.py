"""Pixels to millimetres, with the uncertainty carried along.

This is a two-line calculation and a great deal of care, because the REVIEW
status depends entirely on it:

    "At 1.9 mm +/- 0.2 against a 2.0 mm threshold we do not assert a violation,
     we flag it for the officer. Convicting on a 0.1 mm margin would be
     dismantled in court."             -- contracts/declarations.py

That sentence is only true if the `+/- 0.2` is a real number. If tolerance were
a hardcoded constant, the REVIEW band would be theatre: wide enough to look
careful on a slide, and unrelated to how well this particular photograph was
actually measured. So tolerance is *propagated* from two independent sources —
how well the scale was recovered, and how well the glyph was resolved — and it
widens on a blurry photograph exactly as it should.

**The arithmetic.** With `mm = px * s`, and independent errors on both factors,

    sigma_mm = sqrt( (px * sigma_s)^2 + (s * sigma_px)^2 )

The first term dominates when the marker fit was poor; the second when the text
is tiny. On a 2 mm glyph photographed at 8 px, the second term alone is 0.25 mm
— which is the honest reason a low-resolution photo cannot settle a 2 mm
threshold, and why the officer is asked to step closer rather than handed a
verdict.
"""

from __future__ import annotations

import math

from vision.types import ScaleEstimate

GLYPH_SIGMA_PX = 0.75
"""Uncertainty on a cap-height measurement, in pixels. Binarisation places each
edge to within about half a pixel and there are two edges, so 0.75 px is the
quadrature sum rounded up. Measured against ruler ground truth in week 2; if
the observed spread is wider, this constant moves and `RESULTS.md` records it."""

_UNRECTIFIED_SIGMA_MULTIPLIER = 2.0
"""A glyph measured on an unrectified crop carries residual foreshortening on
top of the edge uncertainty."""


MIN_SEGMENTATION_CONFIDENCE = 0.2
"""Floor on the divisor below, so a pathological crop widens the tolerance by
five rather than by infinity. A crop this badly segmented should be producing
no height at all; the floor exists so that an arithmetic edge case cannot turn
a measurement into `inf` and a verdict into nonsense."""


def to_mm(
    height_px: float | None,
    scale: ScaleEstimate,
    *,
    rectified: bool = True,
    glyph_sigma_px: float = GLYPH_SIGMA_PX,
    segmentation_confidence: float | None = None,
) -> tuple[float | None, float | None]:
    """Convert a pixel height to millimetres. Returns (height_mm, tolerance_mm).

    Returns `(None, None)` at scale tier C — the honest answer, which makes the
    three `min_height_mm` rules return NO_DATA while the other twenty-eight
    carry on. Never substitutes a default scale.

    **`segmentation_confidence` is how well the crop agreed with itself**, from
    `CapHeightResult.confidence`: the share of the ink that shared the baseline
    the cap height was measured from. `GLYPH_SIGMA_PX` models a clean single
    line, where the only question is where the edge of a glyph falls to within
    half a pixel. It does not model the case that actually goes wrong — a crop
    holding two printed lines, or a caption and a value at different sizes,
    where the measurement is not imprecise but measuring the wrong thing.

    The reciprocal is the widening `CapHeightResult.confidence` was documented
    to want, and it is a ratio rather than a picked constant: a crop where half
    the ink agreed carries twice the uncertainty of one where all of it did,
    and a crop where everything agreed is unchanged. `None` leaves the
    behaviour exactly as it was.
    """
    if height_px is None or height_px <= 0 or scale.mm_per_px is None:
        return None, None

    mm_per_px = scale.mm_per_px
    height_mm = height_px * mm_per_px

    sigma_scale = scale.tolerance if scale.tolerance is not None else mm_per_px * 0.05
    sigma_px = glyph_sigma_px * (1.0 if rectified else _UNRECTIFIED_SIGMA_MULTIPLIER)
    if segmentation_confidence is not None:
        sigma_px /= max(min(segmentation_confidence, 1.0), MIN_SEGMENTATION_CONFIDENCE)

    tolerance = math.sqrt((height_px * sigma_scale) ** 2 + (mm_per_px * sigma_px) ** 2)
    return height_mm, tolerance


def resolvable_threshold_mm(
    scale: ScaleEstimate, *, glyph_sigma_px: float = GLYPH_SIGMA_PX
) -> float | None:
    """Smallest height difference this photograph can actually distinguish.

    Useful on the scan screen: if the finest distinction a photo supports is
    0.6 mm, telling an officer that a 1 mm threshold was met is overclaiming.
    The UI uses this to say "move closer" instead of showing a verdict.
    """
    if scale.mm_per_px is None:
        return None
    return 2.0 * scale.mm_per_px * glyph_sigma_px


__all__ = ["GLYPH_SIGMA_PX", "resolvable_threshold_mm", "to_mm"]
