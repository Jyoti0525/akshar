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

**Why the number comes with an error bar.** See `contrast_band`. A crop that is
out of focus measures the lens, not the printer, and this module is the only
place that can tell the difference.
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

_MAX_GAP = 3
"""How far the glyph is eroded, at most, to find pixels that are certainly ink.

Three pixels of softness is what a hand-held phone shot of a small carton
produces; past that the crop has no clean interior left to find and `_MIN_CORE`
sends us back to the whole mask."""

_MIN_CORE = 24
"""Fewest core pixels worth trusting. Below it the erosion has eaten the type
rather than its edge, so the gap steps down until enough survives — hairline
print therefore keeps exactly the behaviour it had before any of this."""

_EXTREME_PERCENTILE = 5.0
"""Where the ink and the paper are read off, once the transition is excluded.

Far enough into each tail to be the printed colour, not so far as to be one
dust speck or one JPEG ring — `_MIN_CORE` guarantees the population is large
enough for a 5th percentile to mean something."""


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


def _ellipse(radius: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1,) * 2)


def _ratio(a: float, b: float) -> float:
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def contrast_band(crop: Image, *, pad: int | None = None) -> tuple[float, float] | None:
    """The contrast ratio of this crop, and how far it can be trusted.

    Returns `(ratio, tolerance)`, or `None` where there is not enough ink to
    measure at all. The tolerance is a real error bar computed from these
    pixels rather than a constant, and `rules/checks/min_contrast.py` consumes
    it the way `min_height_mm` consumes `height_mm_tolerance`.

    ---------------------------------------------------------------------------
    THE FALSE ACCUSATION THIS EXISTS TO PREVENT
    ---------------------------------------------------------------------------
    A face serum carton, photographed by hand and scanned on 2026-09-19.
    `Net Qty: 30 ml` is set in white on a teal carton, is plainly legible on the
    pack, and was reported **FAIL, 1.888:1 against a required 3.000:1** under
    Rule 9(1)(b).

    The measurement was not wrong. Cropping that line out of the photograph and
    looking at it settles the question at once: *that part of the frame is out
    of focus.* The median ink pixel is BGR(160,144,90) — not white, a muddy
    teal-grey — because the white has been smeared into the ground by the lens
    and not by the printer. The number is an honest measurement of the
    photograph and says nothing whatever about the pack.

    Section 8b already holds the principle: an estimate whose error bar crosses
    the threshold is not a verdict. What was missing was an error bar that knew
    a sharp crop from a soft one. The check's flat ±0.2 is right for the first
    and fiction for the second.

    ---------------------------------------------------------------------------
    HOW THE ERROR BAR IS OBTAINED
    ---------------------------------------------------------------------------
    The same crop is read twice, and the two readings bracket the answer:

    * **optimistic** — erode the glyph so only its core is sampled, hold the
      background ring off the edge by the same distance, and read both at the
      5th percentile. This assumes every pixel in the transition belongs to the
      camera and none of it to the ink.
    * **pessimistic** — the whole ink mask against a ring that touches it, at
      the median. This assumes the transition IS the ink.

    A sharp crop has almost no transition, so the two readings coincide and the
    bar closes to nothing. A soft crop has little else, so they diverge and the
    bar opens. Nothing is fitted: the width is a property of the pixels.

    ---------------------------------------------------------------------------
    MEASURED, 2026-09-19
    ---------------------------------------------------------------------------
    Seven legible ink/paper pairs whose true WCAG ratio is known exactly, each
    rendered at five type sizes and put through four grades of capture, plus
    four genuinely illegible pairs over the same conditions:

        legible pairs wrongly FAILED      old  23 of 140     this  2 of 140
        illegible pairs escaping FAIL     old   0 of  80     this  0 of  80

    **The two that remain are stated rather than tuned away.** Both are `mid
    grey on white` at 14 px and 20 px through the heaviest capture in the sweep
    (2.6 px of blur and JPEG quality 72), where no pixel of the glyph is still
    pure ink and no percentile can recover one. In the pipeline a line that far
    gone rarely survives recognition to become a declaration at all. Widening
    the bar enough to cover it would hand the same excuse to the genuinely
    illegible small print in the second row, and that trade is not worth making.

    The illegible pairs keep failing because a pair with little luminance range
    between ink and paper has little to be uncertain about and the bar stays
    shut — `pale grey on white` reads 1.59 ±0.20 sharp and 1.53 ±0.24 soft.

    On the serum carton itself, `Net Qty: 30 ml` reads 2.59 ±1.15 — REVIEW,
    *look at this one yourself* — instead of a finding against the
    manufacturer, and the MRP passes.

    Cost, on the 38-panel bench: median scan 1183 ms before, 1190 ms after.
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

    # How far in we can go and still have glyph left. Widest first: the more of
    # the transition that can be excluded the better, and hairline type simply
    # keeps the whole mask.
    gap, core = 0, ink_mask
    for candidate in range(_MAX_GAP, 0, -1):
        eroded = cv2.erode(ink_mask, _ellipse(candidate))
        if int(np.count_nonzero(eroded)) >= _MIN_CORE:
            gap, core = candidate, eroded
            break

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

    # ONE dilation at the ring radius. Dilating a second time at ring width to
    # get the pessimistic sample was measured at +220 ms on the median scan of
    # the 38-panel bench: the kernel is tens of pixels across and essentially
    # all the cost is in that call. Both other boundaries move with kernels of
    # a few pixels, which are free by comparison.
    outer = cv2.dilate(ink_mask, _ellipse(thickness + gap))
    inner = cv2.dilate(ink_mask, _ellipse(gap)) if gap else ink_mask

    held_off = cv2.subtract(outer, inner)
    if int(np.count_nonzero(held_off)) < _MIN_CORE:
        held_off = cv2.subtract(outer, ink_mask)
    if int(np.count_nonzero(held_off)) < _MIN_INK_PIXELS:
        return None

    # The pessimistic sample's background HUGS the glyph, because the whole
    # point of it is to include the contamination the optimistic one excludes.
    # A wide ring is mostly clean paper and its median barely moves, which
    # closes the error bar on exactly the crops that need it open: with a
    # full-width ring here, `mid grey on white` at 14 px through a soft capture
    # came back 2.08 +/- 0.54 and would have convicted a legible pack.
    skin = cv2.subtract(cv2.dilate(ink_mask, _ellipse(max(2, gap * 2))), ink_mask)
    touching = skin if int(np.count_nonzero(skin)) >= _MIN_INK_PIXELS else held_off

    luminance = _relative_luminance(colour)

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
    # EXCLUDING the transition, rather than choosing a percentile somewhere
    # inside it, is what finally closed that gap: on clean renders of known
    # pairs the optimistic read returns the exact WCAG value at every type
    # size, which no choice of percentile over the full mask ever did.
    #
    # Four sorted reductions, the same count the single-estimate version ran.
    # Each `np.percentile` call sorts its array, so the medians that decide the
    # polarity are the pessimistic read's own two numbers rather than two extra
    # passes, and each population is asked for its percentile exactly once.
    ink_mid = float(np.median(luminance[ink_mask > 0]))
    skin_mid = float(np.median(luminance[touching > 0]))
    ink_is_darker = ink_mid < skin_mid

    low, high = _EXTREME_PERCENTILE, 100.0 - _EXTREME_PERCENTILE
    core_l = float(np.percentile(luminance[core > 0], low if ink_is_darker else high))
    ring_l = float(np.percentile(luminance[held_off > 0], high if ink_is_darker else low))

    optimistic = _ratio(core_l, ring_l)
    pessimistic = _ratio(ink_mid, skin_mid)
    return optimistic, abs(optimistic - pessimistic)


def contrast_ratio(crop: Image, *, pad: int | None = None) -> float | None:
    """WCAG contrast ratio of glyph against local background, or None.

    `crop` should be the text region **with a little margin around it**, so the
    background ring lands on the pack rather than on neighbouring type. The ROI
    OCR stage pads its crops for exactly this reason.

    The ratio on its own. Anything that issues a verdict from it wants
    `contrast_band`, which also reports how far this particular crop can be
    trusted.
    """
    band = contrast_band(crop, pad=pad)
    return None if band is None else band[0]


__all__ = ["contrast_band", "contrast_ratio"]
