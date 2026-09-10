"""Character segmentation — the input `min_width_ratio` needs.

Rule 7(3)'s proviso is *"the width of the letter or numeral shall not be less
than one third of its height"*. Per letter. So the check needs a box per
character, and `rules/checks/min_width_ratio.py` consumes them positionally:

    for ch, box in zip(decl.text, decl.char_boxes, strict=False):

That zip is the contract this module has to satisfy — `char_boxes[i]` must
describe `text[i]`, **spaces included**, or every character's width is compared
against the wrong glyph's height and the rule fires at random.

**Where the work is divided.** This module produces geometry only. Whether a
ratio is lawful, which characters are exempt (`1`, `i`, `I`, `l`) and what
verdict follows are all in the rulepack, because section 3's second principle
says rules decide and models never. The same division applies to clear space:
vision supplies `numeral_box`, and `rules/checks/clear_space.py` decides whether
the surrounding area is lawfully clear.

**When alignment cannot be established, we return nothing.** The check then
reports NO_DATA, which is honest and costs one rule out of thirty-one. Emitting
mis-aligned boxes would cost a false violation on someone's product.
"""

from __future__ import annotations

import cv2
import numpy as np

from vision.measure.cap_height import binarise, measure_cap_height
from vision.types import Box, Image

_BAND_MARGIN_FRAC = 0.35
"""How far past the cap line and the baseline the text band reaches, as a
fraction of cap height.

It has to clear a descender and an accent without reaching the next line.
Ordinary typographic proportions put a descender at roughly a quarter of cap
height below the baseline and leading at rather more than a third above the
cap line, so this catches the glyph and stops short of its neighbour."""

_MAX_HEIGHT_OVER_CAP = 1.5
"""How far the typical segmented character may exceed the line's own cap height
before the whole segmentation is disbelieved.

A column run's vertical extent is whatever ink sits in those columns, and on a
real crop that includes the neighbouring line the padding caught, the printer's
rule under the declaration, and the dark ground behind light type. On `449.00`
from `bodywash_bottle_300ml` the six runs came back [52, 41, 52, 52, 41, 42] px
tall on a 52 px crop, for digits 19 px tall: the segmentation had found the crop
rather than the figures, and every one of those runs was a character-sized
*width* paired with a crop-sized *height*.

Descenders and the odd tall bracket push the median a little above cap height,
which is why this is 1.5 and not 1.0. Beyond that the boxes are not describing
a line of type, and Rule 7(3) divides width by exactly this height -- so an
inflated height makes a lawful character look too narrow and fires a violation
against a compliant pack. The count check alone did not catch it: the runs
agreed with the text length, because the *columns* were right and only the rows
were wrong."""

_INK_THRESHOLD = 0
"""A column counts as ink if any pixel in it is ink. Packaging type is small in
our crops — often 8-15 px tall — so requiring two ink pixels merges the stem of
an `i` into its neighbour."""


def _column_runs(binary: Image) -> list[tuple[int, int]]:
    """Contiguous column ranges containing ink, as (start, end_exclusive)."""
    ink_per_column = (binary > 0).sum(axis=0)
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for x, count in enumerate(ink_per_column):
        if count > _INK_THRESHOLD:
            if start is None:
                start = x
        elif start is not None:
            runs.append((start, x))
            start = None
    if start is not None:
        runs.append((start, len(ink_per_column)))
    return runs


def _split_wide_runs(
    runs: list[tuple[int, int]], expected: int, median_width: float
) -> list[tuple[int, int]]:
    """Split runs that clearly contain several touching glyphs.

    Small print and JPEG blur make adjacent characters touch, which is the
    single commonest reason segmentation count disagrees with the text length.
    A run about twice the median width is two characters, and cutting it at the
    midpoint recovers alignment far more often than it breaks it.
    """
    if len(runs) >= expected or median_width <= 0:
        return runs
    out: list[tuple[int, int]] = []
    for start, end in runs:
        width = end - start
        parts = round(width / median_width)
        if parts >= 2 and len(runs) + len(out) < expected * 2:
            step = width / parts
            out.extend((int(start + i * step), int(start + (i + 1) * step)) for i in range(parts))
        else:
            out.append((start, end))
    return out


def character_boxes(crop: Image, text: str, origin: Box) -> list[Box]:
    """Boxes aligned one-to-one with `text`, in the coordinate frame of `origin`.

    `origin` is the line's box in rectified space; the returned boxes are
    offset into that same space so they can be compared with other
    declarations without a second transform.

    Returns `[]` when segmentation and text disagree on how many characters
    there are. That is deliberate — see the module docstring.
    """
    if crop is None or crop.size == 0 or not text:
        return []
    gray = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if min(gray.shape[:2]) < 4:
        return []

    binary, _ = binarise(gray)

    # Everything below happens inside the *text band*, not inside the crop.
    #
    # The crop is padded so that recognition has context and `contrast_ratio`
    # has a background to compare against, and that padding routinely catches
    # the line above, the line below, and the printer's rule under the
    # declaration. Scanning the whole crop for ink columns then finds ink in
    # columns where this line has none, which merges glyphs into one run, and
    # gives every run the vertical extent of whatever else was in frame. The
    # only check on any of that was "does the run count match the text length",
    # which looks along one axis and cannot see it.
    #
    # `measure_cap_height` has already found where this line's glyphs sit --
    # its baseline is a modal agreement among components, so it is not moved by
    # a neighbouring line the way a row profile would be. Working inside that
    # band is the same move `vision.measure.orientation` makes for rotation:
    # establish the frame once, and let everything downstream work in it rather
    # than each stage rediscovering it.
    reference = measure_cap_height(crop)
    if reference is None:
        return []

    band_top = int(max(0, np.floor(reference.cap_top_y - _BAND_MARGIN_FRAC * reference.cap_height_px)))
    band_bottom = int(
        min(gray.shape[0], np.ceil(reference.baseline_y + _BAND_MARGIN_FRAC * reference.cap_height_px))
    )
    if band_bottom - band_top < 3:
        return []
    band = binary[band_top:band_bottom, :]

    runs = _column_runs(band)
    if not runs:
        return []

    glyph_chars = [ch for ch in text if not ch.isspace()]
    if not glyph_chars:
        return []

    widths = np.array([end - start for start, end in runs], dtype=np.float64)
    runs = _split_wide_runs(runs, len(glyph_chars), float(np.median(widths)))

    if len(runs) != len(glyph_chars):
        return []

    # Per-run vertical extent: a character's height is its own ink extent, not
    # the line's. `min_width_ratio` divides width by height per character, so
    # using the line height would make every short character look compliant.
    boxes: list[Box] = []
    run_iter = iter(runs)
    previous_end = 0

    for ch in text:
        if ch.isspace():
            # A real box for the gap, so positional alignment holds. The check
            # skips spaces, so its dimensions are never compared against a
            # threshold; they must merely be positive.
            start, end = previous_end, previous_end + 1
            top, bottom = band_top, band_bottom
        else:
            start, end = next(run_iter)
            column = band[:, start:end]
            rows = np.flatnonzero((column > 0).any(axis=1))
            if rows.size == 0:  # pragma: no cover - run had ink by construction
                return []
            top, bottom = band_top + int(rows[0]), band_top + int(rows[-1]) + 1
            previous_end = end

        width = max(float(end - start), 1.0)
        height = max(float(bottom - top), 1.0)
        boxes.append(
            Box(
                x=origin.x + float(start),
                y=origin.y + float(top),
                w=width,
                h=height,
                panel_id=origin.panel_id,
            )
        )

    glyph_heights = [
        box.h for ch, box in zip(text, boxes, strict=True) if not ch.isspace()
    ]
    if float(np.median(glyph_heights)) > reference.cap_height_px * _MAX_HEIGHT_OVER_CAP:
        return []

    return boxes


def numerals_of(text: str, boxes: list[Box]) -> Box | None:
    """The sub-box covering just the numerals of an already-segmented line.

    Takes the boxes rather than the crop so a caller that has segmented once
    does not segment again -- and, more importantly, so a caller that had to
    rotate the crop to read it can pass the boxes it has already carried back
    into the frame the rest of the record is written in.
    """
    if not boxes:
        return None
    digits = [box for ch, box in zip(text, boxes, strict=False) if ch.isdigit()]
    if not digits:
        return None

    x0 = min(b.x for b in digits)
    y0 = min(b.y for b in digits)
    x1 = max(b.x2 for b in digits)
    y1 = max(b.y2 for b in digits)
    return Box(x=x0, y=y0, w=max(x1 - x0, 1.0), h=max(y1 - y0, 1.0), panel_id=digits[0].panel_id)


def numeral_box(crop: Image, text: str, origin: Box) -> Box | None:
    """The sub-box covering just the numerals.

    Feeds two things: the Table I height lookup, which measures the numerals of
    the net quantity, and `clear_space`, whose exclusion zone is expressed in
    multiples of the *numeral* height rather than the declaration's.
    """
    return numerals_of(text, character_boxes(crop, text, origin))


__all__ = ["character_boxes", "numeral_box", "numerals_of"]
