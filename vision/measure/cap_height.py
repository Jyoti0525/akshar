"""Cap height — the measurement the whole project rests on.

    "Cap height in rectified pixels — top of a capital letter to the baseline,
     excluding descenders (section 16, annotation rules). For the two
     numeral-height rules this is the height of the NUMERALS, not of the whole
     declaration including '(inclusive of all taxes)'."
                                        -- contracts/declarations.py

An OCR line box is not a cap height. It is the bounding box of everything the
engine decided was on that line, so it includes the descender of a `g`, the tail
of a `)`, and often a few pixels of the box border. Feeding that straight into
Rule 7(2) inflates every measurement by 20-30% and turns non-compliant packs
compliant — the error that would quietly make the whole system useless while
every test still passed.

**Method.** Binarise, take connected components, and find the *baseline* as the
modal component bottom. Glyphs sit on a shared baseline; descenders do not, and
they are the minority. Then measure height only among baseline-aligned
components, taking the upper quartile so that lower-case `e` and `o` — which
top out at x-height — do not drag the cap height down.

Nothing here is learned. Section 14: *rectification, scale and measurement —
trained? No, deterministic geometry.*
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from vision.types import Image

_MIN_COMPONENT_PX = 3
_BASELINE_TOLERANCE_FRAC = 0.12
"""How far a component's bottom may sit from the modal baseline and still count
as sitting on it, as a fraction of the crop height. Print is not perfectly
registered and the binarisation adds a pixel of jitter."""

_CAP_PERCENTILE = 75.0
"""Upper quartile of baseline-aligned component heights. The 100th percentile
would latch onto a stray border fragment; the median would return x-height on
any mixed-case string.

Used only where the heights form a single cluster -- see `_tall_cluster`, which
is what a mixed-case line goes through first."""

_BIMODAL_RATIO = 1.15
"""How much taller the tallest glyph must be than the shortest before the line
is treated as having two kinds of letter in it. Below this everything on the
line is one height and there is nothing to separate."""

_MIN_GLYPHS_TO_SPLIT = 4
"""Two clusters cannot be found in three glyphs. `500 g` is a real declaration
and it is not evidence of anything bimodal."""

_MIN_TALL_GLYPHS = 2
"""One glyph is not a class of letter, it is a mark.

`MFG 03/2026` in Verdana is nine glyphs 30 px tall and a solidus 37 px tall,
and the solidus alone was the taller class -- a 23% overstatement of the cap
height of a line whose every letter is the same size. A slash, a bracket, an
integral-looking `f`: these stand above the capitals in most faces and they are
not what Rule 7 measures. A lone tall glyph is dropped and the split retried on
what is left."""


@dataclass(frozen=True, slots=True)
class Glyph:
    x: float
    y: float
    w: float
    h: float
    area: int

    @property
    def bottom(self) -> float:
        return self.y + self.h


@dataclass(frozen=True, slots=True)
class CapHeightResult:
    cap_height_px: float
    baseline_y: float
    cap_top_y: float
    glyphs: list[Glyph] = field(default_factory=list)
    confidence: float = 0.0
    """Fraction of components that agreed on the baseline. Low confidence means
    a multi-line or badly segmented crop, and the caller should widen tolerance
    rather than assert a height."""

    ink_is_dark: bool = True


def binarise(gray: Image) -> tuple[Image, bool]:
    """Otsu, oriented so ink is white. Returns (binary, ink_was_dark).

    Auto-orientation matters: about a third of Indian packaging prints light
    text on a dark or saturated ground, and a fixed polarity would find the
    background's components instead of the glyphs'.
    """
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Ink is the minority of a text crop. If the "white" class dominates, we
    # thresholded the background, so flip.
    if float(np.count_nonzero(binary)) > 0.5 * binary.size:
        binary = cv2.bitwise_not(binary)
        return binary, True
    return binary, False


def _components(binary: Image) -> list[Glyph]:
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    h, w = binary.shape[:2]
    glyphs: list[Glyph] = []
    for i in range(1, count):  # 0 is background
        x, y, cw, ch, area = (int(v) for v in stats[i])
        if ch < _MIN_COMPONENT_PX or cw < 1 or area < _MIN_COMPONENT_PX:
            continue
        # Reject anything spanning almost the whole crop: a box border, an
        # underline, or a rule the label printer drew under the declaration.
        if ch >= h * 0.97 or cw >= w * 0.95:
            continue
        glyphs.append(Glyph(float(x), float(y), float(cw), float(ch), area))
    return glyphs


def _tall_cluster(heights: np.ndarray) -> np.ndarray | None:
    """Split baseline-aligned glyph heights into x-height and cap/ascender.

    Returns the taller group, or None where the line is one height throughout
    and there is nothing to separate.

    The split is Otsu's, done on the heights themselves rather than on a
    histogram: try every cut of the sorted list and keep the one that maximises
    between-class variance. A text line has at most a couple of dozen glyphs, so
    the exhaustive search is cheaper than binning them.
    """
    remaining = np.sort(heights)
    dropped = False
    while remaining.size >= _MIN_GLYPHS_TO_SPLIT:
        if remaining[-1] / max(remaining[0], 1.0) < _BIMODAL_RATIO:
            # One height throughout. That is an answer where a mark has just
            # been dropped, and nothing at all where none has.
            return remaining if dropped else None

        best_cut, best_score = remaining.size, -1.0
        for cut in range(1, remaining.size):
            short, tall = remaining[:cut], remaining[cut:]
            score = short.size * tall.size * float(tall.mean() - short.mean()) ** 2
            if score > best_score:
                best_score, best_cut = score, cut

        tall = remaining[best_cut:]
        if tall.size >= _MIN_TALL_GLYPHS:
            return tall
        remaining, dropped = remaining[:best_cut], True

    return None


def _cap_from(heights: np.ndarray) -> float:
    """Cap height from the heights of the glyphs sitting on the baseline.

    **A percentile is the wrong instrument on a mixed-case line, and this was
    measured rather than argued.** Rendered at six sizes in six fonts and
    measured against the font's own `H`, the upper quartile read *"Maximum
    Retail Price"* 1.97 px short on average and up to 7 px short, because three
    capitals among seventeen lower-case letters are nowhere near the 75th
    percentile of anything. `packed on` was 2.01 px short for the same reason.

    That error has a direction, which is why it could not stay. Under-measuring
    a letter is how a compliant pack gets accused under Rule 7(3)'s 1 mm
    minimum -- at the 8 px/mm these photographs actually carry, 2 px is a
    quarter of the threshold and 7 px is most of it.

    Separating the two kinds of letter first and taking the median of the taller
    one moves the same 864 cases from -0.37 px mean error to +0.21, and from
    21.9% of readings more than a pixel out to 9.6%.

    Where a line has no capitals at all the tall cluster is its ascenders, which
    in most faces stand a shade above cap height; `packed on` reads +1.01 px.
    That is the honest answer to a question the line cannot answer exactly, and
    it errs towards REVIEW rather than towards an accusation.
    """
    tall = _tall_cluster(heights)
    if tall is None:
        return float(np.percentile(heights, _CAP_PERCENTILE))
    return float(np.median(tall))


def measure_cap_height(crop: Image) -> CapHeightResult | None:
    """Cap height in pixels for one text crop, or None if nothing is legible.

    None is a real answer — the caller emits no `height_px` and the height
    rules return NO_DATA. Returning the crop height as a fallback would be
    a fabricated measurement, and fabricated measurements are what section 14
    refuses to let a model do; we do not get to do it in arithmetic either.
    """
    if crop is None or crop.size == 0:
        return None
    gray = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if min(gray.shape[:2]) < 4:
        return None

    binary, ink_dark = binarise(gray)
    glyphs = _components(binary)
    if not glyphs:
        return None

    height = float(gray.shape[0])
    tolerance = max(1.5, height * _BASELINE_TOLERANCE_FRAC)

    # Baseline = the bottom edge shared by the most components. A simple modal
    # bin rather than a mean, because a single descender would shift a mean.
    bottoms = np.array([g.bottom for g in glyphs], dtype=np.float64)
    best_baseline, best_count = float(bottoms[0]), 0
    for candidate in bottoms:
        agreeing = int(np.count_nonzero(np.abs(bottoms - candidate) <= tolerance))
        if agreeing > best_count:
            best_baseline, best_count = float(candidate), agreeing

    aligned = [g for g in glyphs if abs(g.bottom - best_baseline) <= tolerance]
    if not aligned:  # pragma: no cover - best_baseline came from the list
        return None

    heights = np.array([g.h for g in aligned], dtype=np.float64)
    cap_height = _cap_from(heights)
    if cap_height < _MIN_COMPONENT_PX:
        return None

    baseline_y = float(np.median([g.bottom for g in aligned]))
    return CapHeightResult(
        cap_height_px=cap_height,
        baseline_y=baseline_y,
        cap_top_y=baseline_y - cap_height,
        glyphs=glyphs,
        confidence=best_count / len(glyphs),
        ink_is_dark=ink_dark,
    )


def measure_numeral_height(
    crop: Image,
    text: str,
    *,
    columns: list[tuple[float, float]] | None = None,
) -> float | None:
    """Height of the NUMERALS specifically — what Rule 7(2) Table I measures.

    Rule 7(2) prescribes the height of the numerals of the net quantity, and
    Rule 9's MRP height likewise attaches to the figure. On a pack reading
    `Net Wt. 500 g` the words and the digits are often set at different sizes,
    and measuring the words is measuring the wrong thing.

    **`columns` is what makes that true rather than merely intended.** Without
    it this function fell back to "among baseline-aligned components, take the
    ones whose height clusters at the top", on the reasoning that lining
    figures are full cap height. They are — but so are the capitals of the
    label beside them, and when the label is set *larger* than the figure the
    tall cluster is the label. `match_box` reads `MRP2.00 incl. of all taxes`
    with a 1.00 mm price under a larger `MRP`, and that fallback measured
    1.50 mm: a 50% overstatement, in the direction that turns a non-compliant
    pack compliant.

    So the caller passes the horizontal spans of the digit characters, and only
    components centred inside one of them are considered. Those spans come from
    `characters.character_boxes`, which finds *columns* by scanning for ink and
    is reliable about them; its per-character *heights* are not to be trusted
    and are not used here. Columns from segmentation, heights from connected
    components — each method asked only the question it can answer.

    With no columns the old behaviour remains, because a line that could not be
    segmented still has a measurable figure more often than not, and the
    caller's alternative is no height at all.
    """
    result = measure_cap_height(crop)
    if result is None:
        return None
    if not any(ch.isdigit() for ch in text):
        return None

    height = float(crop.shape[0])
    tolerance = max(1.5, height * _BASELINE_TOLERANCE_FRAC)
    aligned = [g for g in result.glyphs if abs(g.bottom - result.baseline_y) <= tolerance]
    if not aligned:  # pragma: no cover
        return result.cap_height_px

    if columns:
        inside = [
            g
            for g in aligned
            if any(start <= g.x + g.w / 2.0 <= end for start, end in columns)
        ]
        if inside:
            # Every component here is already known to be a digit's ink, so
            # the median is over the figures themselves and there is no taller
            # cluster to separate out.
            return float(np.median([g.h for g in inside]))

    # Digits are full-height; keep the taller cluster and take its median.
    tall = [g.h for g in aligned if g.h >= result.cap_height_px * 0.85]
    if not tall:
        return result.cap_height_px
    return float(np.median(tall))


__all__ = ["CapHeightResult", "Glyph", "binarise", "measure_cap_height", "measure_numeral_height"]
