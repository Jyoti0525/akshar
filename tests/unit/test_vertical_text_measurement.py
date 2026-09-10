"""The same print, set sideways, must measure and be judged identically.

Net quantity, batch code and MRP are very often set down the *side* of a pack —
37% of the regions our detector proposes are taller than wide. Every
measurement in `vision/` was written as though text runs left to right, and the
assumption failed silently in five modules and two rules at once.

Silently is the important word. Nothing raised. `cap_height` looked for a
baseline among glyphs that share a side rather than a bottom and returned a
number; `characters` segmented by column, found one run where there were nine
glyphs, and dropped the geometry that Rule 7(3) needs; `min_width_ratio`
divided a box's width by its height and got 3.0 where the glyph's true ratio
was 0.33, **passing** a character the proviso exists to fail.

So these tests are written as equivalences rather than as thresholds: rotate
the pixels, and every number that comes out the far end must be the number the
upright pack produced. A threshold test would have passed throughout the period
the bug existed. No model is exercised — the model was never the problem.
"""

from __future__ import annotations

import numpy as np
import pytest

from contracts import Box, PackageContext, ParsedQuantity
from rules.engine import evaluate
from tests.unit.conftest import make_declaration, make_set
from vision.measure.cap_height import measure_cap_height
from vision.measure.characters import character_boxes, numerals_of
from vision.measure.contrast import contrast_ratio
from vision.measure.orientation import orientations, unrotate_box


def _printed_line() -> np.ndarray:
    """Dark glyphs of a known cap height, sitting on a shared baseline."""
    crop = np.full((40, 120, 3), 240, dtype=np.uint8)
    for i in range(6):
        x = 8 + i * 18
        crop[10:28, x : x + 8] = 20  # 18 px tall, 8 px wide, baseline at y=28
    return crop


def _verdict(verdicts, rule_id):
    for v in verdicts:
        if v.rule_id == rule_id:
            return v
    raise AssertionError(f"{rule_id} did not run")


# -- the measurement chain -------------------------------------------------


@pytest.mark.parametrize("k", [1, 3])
def test_cap_height_survives_the_pack_being_printed_sideways(k):
    upright = _printed_line()
    sideways = np.rot90(upright, k)

    # What `roi` now does: the crop is turned back to horizontal before any
    # measurement is taken, so the measurer never learns this happened.
    restored = next(image for turns, image in orientations(sideways) if turns == (4 - k) % 4)

    before = measure_cap_height(upright)
    after = measure_cap_height(restored)
    assert before is not None and after is not None
    assert after.cap_height_px == before.cap_height_px


def test_measuring_a_sideways_crop_without_turning_it_gets_the_wrong_answer():
    """The bug itself, pinned. If this ever passes, the fix has been undone."""
    upright = _printed_line()
    naive = measure_cap_height(np.rot90(upright, 1))
    honest = measure_cap_height(upright)
    assert honest is not None and honest.cap_height_px == 18.0
    # 18 px of type read as 8 px, or refused outright. Either way, not 18.
    assert naive is None or naive.cap_height_px != honest.cap_height_px


@pytest.mark.parametrize("k", [1, 3])
def test_character_boxes_come_home_with_their_glyph_shape_intact(k):
    upright = _printed_line()
    sideways = np.rot90(upright, k)
    turns = (4 - k) % 4
    restored = next(image for t, image in orientations(sideways) if t == turns)

    text = "250 gms"  # six glyphs, one per printed bar
    frame = Box(x=0.0, y=0.0, w=float(restored.shape[1]), h=float(restored.shape[0]))
    in_reading_frame = character_boxes(restored, text, frame)
    assert in_reading_frame, "segmentation should succeed once the crop is horizontal"

    crop_h, crop_w = sideways.shape[:2]
    home = [unrotate_box(b, turns, crop_h=crop_h, crop_w=crop_w) for b in in_reading_frame]

    # Every glyph keeps its dimensions, with the axes swapped -- which is what
    # a sideways declaration genuinely looks like in pack coordinates.
    for read, placed in zip(in_reading_frame, home, strict=True):
        assert (placed.w, placed.h) == (read.h, read.w)
    # And they stay inside the crop they were found in.
    for placed in home:
        assert 0 <= placed.x <= crop_w and 0 <= placed.y <= crop_h


def test_the_numeral_box_is_built_from_boxes_already_carried_home():
    text = "250 g"
    boxes = [Box(x=10 + i * 8, y=10, w=6, h=18, panel_id="pdp") for i in range(len(text))]
    box = numerals_of(text, boxes)
    assert box is not None and box.panel_id == "pdp"
    assert numerals_of(text, []) is None


def test_the_contrast_ring_is_scaled_by_the_minor_axis():
    """A tall crop must not dilate its ink by half the length of the line."""
    upright = _printed_line()
    sideways = np.rot90(upright, 1)
    assert contrast_ratio(upright) == pytest.approx(contrast_ratio(sideways), rel=0.2)


# -- what the rules then do with it ----------------------------------------


def _narrow_pack(*, rotation_k: int):
    """A pack whose `2` is 2 px wide and 16 px tall — a real Rule 7(3) failure.

    Set upright, the glyph boxes are 2x16. Set sideways they are 16x2 in pack
    coordinates, and the declaration records which.
    """
    if rotation_k:
        char_boxes = [Box(x=10, y=10 + i * 8, w=16, h=2) for i in range(6)]
        numeral = Box(x=10, y=10, w=16, h=24, panel_id="pdp")
    else:
        char_boxes = [Box(x=10 + i * 8, y=10, w=2, h=16) for i in range(6)]
        numeral = Box(x=10, y=10, w=24, h=16, panel_id="pdp")
    return make_set(
        [
            make_declaration(
                "net_quantity",
                "250 g",
                char_boxes=char_boxes,
                numeral_box=numeral,
                rotation_k=rotation_k,
            )
        ],
        mm_per_px=None,
    )


@pytest.mark.parametrize("k", [0, 1, 3])
def test_rule_seven_three_fails_the_same_narrow_glyph_whichever_way_it_is_set(k, pack):
    ctx = PackageContext(
        category="unknown", net_quantity=ParsedQuantity(value=250, unit="g", base_g_ml=250.0)
    )
    v = _verdict(evaluate(_narrow_pack(rotation_k=k), ctx, pack), "LMPC.CHAR.WIDTH_RATIO")
    assert v.status == "FAIL"
    assert v.measured is not None and v.measured == pytest.approx(0.125)


def test_ignoring_the_rotation_would_pass_the_character_it_should_fail():
    """Why the rotation is on the contract rather than inferred from the box.

    The sideways glyph is 16x2 in pack coordinates. Divide those directly and
    the ratio is 8.0 — comfortably above one third, and a violation reported as
    compliant. This is the failure mode the field exists to prevent.
    """
    sideways = _narrow_pack(rotation_k=1).declarations[0]
    naive = sideways.char_boxes[0].w / sideways.char_boxes[0].h
    assert naive == pytest.approx(8.0)
    assert sideways.glyph_size(sideways.char_boxes[0]) == (2.0, 16.0)


def test_the_numeral_height_is_a_scalar_and_so_cannot_be_read_sideways():
    """The rotation-proof answer is to stop measuring a box at all.

    `numeral_box` is a position in pack coordinates and its height depends on
    which way the text ran. `numeral_height_px` is measured on the crop the
    text was *read* from, where the glyphs are already upright, so the same
    figure yields the same number whichever way it was printed -- there is no
    axis left to pick wrongly.
    """
    upright = make_declaration("net_quantity", "250 g", numeral_height_px=16.0, rotation_k=0)
    sideways = make_declaration("net_quantity", "250 g", numeral_height_px=16.0, rotation_k=1)
    assert upright.height_for_rules_px == 16.0
    assert sideways.height_for_rules_px == 16.0


def test_the_numeral_box_height_is_never_used_as_a_measurement():
    """It was, and on real crops it returned the height of the crop.

    Column-run segmentation is right about where a character starts and stops
    and wrong about how tall it is: the run's vertical extent is whatever ink
    sits in those columns, padding and neighbouring lines included. A box like
    this one is what that failure looks like -- plausible, and three times the
    figure it claims to describe.
    """
    decl = make_declaration(
        "mrp", "449.00", numeral_box=Box(x=0, y=0, w=145, h=52, panel_id="pdp")
    )
    assert decl.numeral_height_px is None
    assert decl.height_for_rules_px == decl.height_px
    assert decl.height_for_rules_px != 52.0
