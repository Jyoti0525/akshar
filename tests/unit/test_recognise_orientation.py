"""Vertical text, and why it was being destroyed before it reached the model.

Recognition resizes every crop to a fixed height and scales its width by the
aspect ratio. That is correct for a line of print, which is wide, and ruinous
for a column of print, which is tall: a 58x508 crop of text running down the
side of a pack arrived at the recogniser as 48x48 with every glyph gone.

Measured across 86 dev-corpus crops before the fix, the empty-read rate tracked
the aspect ratio and nothing else:

    aspect (w/h)   <0.5    0.5-1    1-3    3-8    >8
    empty reads     52%      43%    31%    25%    0%

and 37% of all detected regions were portrait. These tests pin the geometry of
the fix -- the model itself is not exercised here, because what went wrong was
never the model.
"""

from __future__ import annotations

import numpy as np

from vision.measure.orientation import ROTATE_ASPECT, glyph_axis, orientations, unrotate_box
from vision.ocr.recognise import REC_HEIGHT, _preprocess
from vision.types import Box


def _orientations(crop: np.ndarray) -> tuple[np.ndarray, ...]:
    return tuple(image for _, image in orientations(crop))


def _crop(width: int, height: int) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)


def test_a_line_of_print_is_read_as_it_is():
    """The common case must not pay for the rare one: no rotation, one pass."""
    assert len(_orientations(_crop(400, 40))) == 1


def test_a_column_of_print_is_read_rotated():
    """58x508 is a real region from the corpus -- a pack's side panel."""
    oriented = _orientations(_crop(58, 508))

    assert len(oriented) == 2
    for image in oriented:
        # Rotating swaps the axes, which is the entire point.
        assert image.shape[0] == 58
        assert image.shape[1] == 508


def test_both_rotations_are_tried_because_we_ship_no_angle_classifier():
    """PP-OCR's `cls` head decides 0 vs 180. The plan does not bundle it.

    Guessing one direction would silently halve recall on every pack whose
    text runs the other way, and the failure would look like unreadable print
    rather than like a wrong assumption.
    """
    tall = _crop(50, 400)
    one, two = _orientations(tall)

    assert not np.shares_memory(one, two) or one.shape == two.shape
    # The two candidates are 180 degrees apart, not the same rotation twice.
    assert np.array_equal(one, np.rot90(two, 2))


def test_a_square_crop_is_not_rotated():
    """The threshold has to sit above 1.0 or ordinary short words rotate."""
    assert ROTATE_ASPECT > 1.0
    assert len(_orientations(_crop(100, 100))) == 1


def test_the_threshold_is_where_squashing_starts_to_bite():
    """Just under it, one orientation; just over it, two."""
    height = 300
    just_wide = int(height / ROTATE_ASPECT) + 2
    just_tall = int(height / ROTATE_ASPECT) - 2

    assert len(_orientations(_crop(just_wide, height))) == 1
    assert len(_orientations(_crop(just_tall, height))) == 2


def test_the_squashing_this_prevents_is_real():
    """The bug itself, stated as arithmetic.

    Unrotated, a 58x508 crop preprocesses to the minimum width -- square --
    because the width is scaled by an aspect ratio far below one. Rotated, it
    keeps its glyphs spread across the width the recogniser reads along.
    """
    upright = _preprocess(_crop(58, 508))
    rotated = _preprocess(_orientations(_crop(58, 508))[0])

    assert upright.shape[-2] == REC_HEIGHT
    assert upright.shape[-1] == REC_HEIGHT      # 48x48: the glyphs are gone
    assert rotated.shape[-1] > upright.shape[-1] * 4


# -- the inverse transform -------------------------------------------------
#
# Rotating to read is only half the fix. Every box measured on the rotated
# pixels has to come back to where it was found, or a vertical declaration's
# characters are reported on the wrong side of the pack and `clear_space`
# checks an area nobody printed anything in.


def test_an_unrotated_box_is_left_exactly_alone():
    box = Box(x=3.0, y=7.0, w=11.0, h=5.0)
    assert unrotate_box(box, 0, crop_h=40, crop_w=100) == box


def test_a_rotation_round_trips_a_whole_crop_back_onto_itself():
    for k in (1, 3):
        # The crop's own extent, expressed in the rotated frame, must come back
        # as the crop's own extent. Rotated shape is the transpose.
        whole = Box(x=0.0, y=0.0, w=40.0, h=100.0)
        back = unrotate_box(whole, k, crop_h=40, crop_w=100)
        assert (back.x, back.y, back.w, back.h) == (0.0, 0.0, 100.0, 40.0)


def test_rotating_back_matches_what_numpy_actually_did():
    # Derived from `np.rot90` rather than asserted: mark one pixel, rotate,
    # find it, and check `unrotate_box` sends it home.
    for k in (1, 3):
        crop = np.zeros((40, 100), dtype=np.uint8)
        crop[8, 61] = 255
        rotated = np.rot90(crop, k)
        ys, xs = np.nonzero(rotated)
        found = Box(x=float(xs[0]), y=float(ys[0]), w=1.0, h=1.0)
        home = unrotate_box(found, k, crop_h=40, crop_w=100)
        assert (home.x, home.y) == (61.0, 8.0)


def test_a_rotated_box_keeps_its_glyph_shape():
    # A digit read on rotated pixels is tall and narrow there. Coming home it
    # must still be tall and narrow -- `min_width_ratio` divides one by the
    # other, so swapping them turns a compliant `5` into a violation.
    digit = Box(x=10.0, y=2.0, w=6.0, h=18.0)
    home = unrotate_box(digit, 1, crop_h=40, crop_w=100)
    # Lying on its side in pack coordinates, which is how vertical text is.
    assert (home.w, home.h) == (18.0, 6.0)
    # ...but its glyph height is still 18: the axis moved, the type did not.
    assert glyph_axis(home, 1) == 18.0


def test_the_glyph_axis_is_not_just_the_shorter_side():
    # The distinction the rotation exists to preserve: an upright digit is
    # taller than it is wide, so `min(w, h)` would measure its width.
    upright = Box(x=0.0, y=0.0, w=6.0, h=18.0)
    assert glyph_axis(upright, 0) == 18.0
    assert glyph_axis(upright, 0) != min(upright.w, upright.h)
