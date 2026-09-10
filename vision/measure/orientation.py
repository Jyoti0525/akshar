"""Which way the text runs — decided once, for everything downstream.

**The assumption this module exists to delete.** Every measurement in `vision/`
was written as though packaging text runs left to right. It does not: 37% of
the regions our detector proposes are taller than wide, because net quantity,
batch code and MRP are very often set down the side of a pack. The assumption
was load-bearing in five separate places and it failed silently in all of them:

    cap_height     baseline = the modal component *bottom*; vertical glyphs
                   share a side, not a bottom, so there is no baseline to find
                   and `Glyph.h` is the glyph's width
    characters     segments by *columns*; vertical text puts every glyph in the
                   same columns, so one run comes back, the count disagrees
                   with the text, and both `char_boxes` and `numeral_box` are
                   dropped -- Rule 7(3) and clear space go NO_DATA
    contrast       ring thickness scaled by `shape[0]`, the *long* axis on a
                   vertical crop, so the background ring swallowed neighbours
    recognise      resizes to a fixed height, flattening a 58x508 crop to 48x48
    assemble       falls back to `box.h` for the glyph height

Fixing five modules independently is five chances to disagree. So the crop is
rotated to horizontal **once**, in `vision.ocr.roi`, before any of them sees it,
and this module owns both halves of that: the decision, and the inverse
transform that carries the resulting boxes back to where they were found.

Nothing downstream of the rotation knows it happened. That is the point.
"""

from __future__ import annotations

import numpy as np

from vision.types import Box, Image

ROTATE_ASPECT = 1.5
"""A crop this many times taller than wide is treated as rotated text.

PP-OCR's own pipeline uses this ratio before recognition. Below it, a crop is a
short wide word -- `50 g` is 1.2:1 -- and rotating it would break what already
works.
"""


def is_portrait(crop: Image) -> bool:
    h, w = crop.shape[:2]
    return h >= w * ROTATE_ASPECT


def orientations(crop: Image) -> tuple[tuple[int, Image], ...]:
    """`(k, rotated)` pairs to try, where `k` is quarter-turns anticlockwise.

    Both directions are offered for a portrait crop because we have no angle
    classifier. PP-OCR ships a `cls` head that decides 0 vs 180 after rotating;
    the plan does not bundle it, and guessing one direction would silently halve
    recall on the packs whose text runs the other way. Recognition confidence
    picks the winner, which costs a second pass on the 37% of crops that are
    portrait and nothing at all on the rest.
    """
    if not is_portrait(crop):
        return ((0, crop),)
    return ((1, np.rot90(crop, 1)), (3, np.rot90(crop, 3)))


def unrotate_box(box: Box, k: int, *, crop_h: int, crop_w: int) -> Box:
    """Carry a box measured on `np.rot90(crop, k)` back into `crop`'s frame.

    `crop_h` and `crop_w` are the *unrotated* crop's shape. Derived from the
    definition of `np.rot90` rather than guessed:

        k=1   rot[r][c] == crop[c][W-1-r]     so (x, y) -> (W-1-y, x)
        k=3   rot[r][c] == crop[H-1-c][r]     so (x, y) -> (y, H-1-x)

    which, taken over a box's extent rather than a point, swaps the axes and
    reflects the one that the rotation reversed. A rotated box's width is the
    original's height, always -- so a digit that is tall and narrow on the pack
    comes back tall and narrow, which is what `min_width_ratio` has to measure.
    """
    if k % 4 == 0:
        return box
    if k % 4 == 1:
        x, y = crop_w - box.y - box.h, box.x
    elif k % 4 == 3:
        x, y = box.y, crop_h - box.x - box.w
    else:  # pragma: no cover - 180 is never produced by `orientations`
        x, y = crop_w - box.x - box.w, crop_h - box.y - box.h
        return Box(x=x, y=y, w=box.w, h=box.h, panel_id=box.panel_id)
    return Box(x=x, y=y, w=box.h, h=box.w, panel_id=box.panel_id)


def glyph_axis(box: Box, k: int) -> float:
    """The side of `box` that carries glyph *height*, given the rotation used.

    For upright text that is the box's height. For text running down the side
    of a pack it is the box's width, and the height is how far the line runs.
    A `min(w, h)` would get the common cases right and a single upright digit
    wrong -- `5` is narrower than it is tall -- so the rotation is consulted
    rather than inferred from the shape.
    """
    return box.w if k % 4 in (1, 3) else box.h


__all__ = ["ROTATE_ASPECT", "glyph_axis", "is_portrait", "orientations", "unrotate_box"]
