"""Contrast ratio — Rule 9(1)(b) legibility and Rule 18(5) defacement.

Both rules ask the same physical question — can this be read — so both consume
`Declaration.contrast_ratio` and differ only in threshold, respondent and
precondition. This module supplies the number; `rules/checks/min_contrast.py`
decides what it means.

**Why WCAG.** The gazette says a declaration must be *"conspicuous and legible"*
without defining a number, so the threshold in the rulepack is a reasoned
choice rather than a quoted one, and it needs a defensible definition behind
it. WCAG 2.1's relative-luminance contrast ratio is an international standard,
published, and computed the same way by everyone — which is exactly what you
want when the alternative is explaining your own invented formula in a
courtroom. The rulepack cites the rule; the report states the method.

**Why the local background and not the label's.** A dark MRP printed over a
photograph of the product may sit on light ground in one place and dark in
another. Legibility is a property of the glyph against what is immediately
behind it, so the background is sampled from a ring around the text, not from
the pack as a whole.
"""

from __future__ import annotations

import cv2
import numpy as np

from vision.measure.cap_height import binarise
from vision.types import Image

_RING_FRAC = 0.6
"""Background ring thickness as a fraction of the crop height. Wide enough to
escape the glyph's anti-aliased edge, narrow enough to stay on the same
printed ground."""

_MIN_INK_PIXELS = 12
"""Below this the "ink" is noise, and a ratio computed from it would be a
number with no measurement behind it."""


def _relative_luminance(bgr: np.ndarray) -> np.ndarray:
    """WCAG 2.1 relative luminance from sRGB, per pixel.

    The gamma expansion matters: averaging raw 8-bit values instead would
    overstate contrast on mid-greys, which is precisely the range low-contrast
    kraft-paper printing lives in — the case we most need to get right.
    """
    srgb = bgr.astype(np.float64) / 255.0
    linear = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    blue, green, red = linear[..., 0], linear[..., 1], linear[..., 2]
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(crop: Image, *, pad: int | None = None) -> float | None:
    """WCAG contrast ratio of glyph against local background, or None.

    `crop` should be the text region **with a little margin around it**, so the
    background ring lands on the pack rather than on neighbouring type. The ROI
    OCR stage pads its crops for exactly this reason.
    """
    if crop is None or crop.size == 0:
        return None
    colour = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR) if crop.ndim == 2 else crop
    if min(colour.shape[:2]) < 4:
        return None

    gray = cv2.cvtColor(colour, cv2.COLOR_BGR2GRAY)
    ink_mask, _ = binarise(gray)
    if int(np.count_nonzero(ink_mask)) < _MIN_INK_PIXELS:
        return None

    # Background = dilate the ink and take what the dilation added. That ring
    # hugs every glyph, including the counters of an `o`, which a rectangular
    # margin would miss.
    # The *minor* axis, not `shape[0]`. On text running down the side of a
    # pack the taller axis is the length of the line, and scaling the ring by
    # it dilated the glyphs far enough to swallow whatever was printed next
    # to them -- so the background being compared against was neighbouring
    # type rather than the pack. For upright text the minor axis is
    # `shape[0]`, so nothing about the common case changes.
    minor = min(colour.shape[:2])
    thickness = pad if pad is not None else max(2, int(minor * _RING_FRAC * 0.25))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (thickness * 2 + 1,) * 2)
    dilated = cv2.dilate(ink_mask, kernel, iterations=1)
    ring = cv2.subtract(dilated, ink_mask)
    if int(np.count_nonzero(ring)) < _MIN_INK_PIXELS:
        return None

    luminance = _relative_luminance(colour)
    ink_values = luminance[ink_mask > 0]
    ring_values = luminance[ring > 0]

    # The COLOUR of the ink against the COLOUR of the paper -- which is what
    # WCAG's ratio is defined between -- and not the average of either sample.
    #
    # Both samples are contaminated in the same direction, and it is not a
    # small effect. A 1 mm character photographed in a shop is a few pixels
    # wide, so a large share of the glyph is anti-aliased edge: half ink, half
    # paper. Those pixels sit in `ink_mask` and pull its mean towards the
    # paper. The ring hugs the glyph by construction, so it collects the outer
    # half of the same soft edge and its mean is pulled towards the ink. The
    # two estimates walk towards each other and the ratio collapses.
    #
    # Measured against known values on 2026-09-10: black on white, whose true
    # ratio is 21.0, came back as 13.66 -- a 35% understatement, and the bias
    # ran from 11% to 35% across the range. On 1178 declarations from the field
    # corpus the estimator never once exceeded 10.35, and 68% of them fell
    # below the 3.0 threshold and were reported as illegible under Rule 9(1)(b)
    # -- against retail packaging, which is legible by design. That is a
    # miscalibrated instrument issuing findings, not a finding.
    #
    # Percentiles rather than the extremes: a single dust speck or JPEG ring
    # would otherwise set the result. The 20th and 80th are far enough into
    # each population to be the real colour and far enough from the tails to be
    # stable.
    ink_is_darker = float(np.median(ink_values)) < float(np.median(ring_values))
    ink_l = float(np.percentile(ink_values, 20.0 if ink_is_darker else 80.0))
    bg_l = float(np.percentile(ring_values, 80.0 if ink_is_darker else 20.0))

    lighter, darker = max(ink_l, bg_l), min(ink_l, bg_l)
    return (lighter + 0.05) / (darker + 0.05)


__all__ = ["contrast_ratio"]
