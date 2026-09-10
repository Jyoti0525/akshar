"""M1 and M2 — rectification, scale tiers, and measurement.

These are the tests behind the two acceptance criteria in section 17 that can
be checked without the ruler corpus:

    M1  "printed lines deviate under 2 degrees from horizontal after warping"
    M2  "tier A mean absolute error <= 0.15 mm against ruler ground truth"

M1's criterion is met here in full, on synthetic photographs with a known
applied homography. M2's number still cannot be met here — a printed marker
photographed on a real shelf is not a marker composited into a clean canvas —
but the fixture is markedly stronger than the coin one it replaced. `draw_coin`
painted something coin-*like* and the test then asserted that a circle detector
found a circle, which is close to asserting that `HoughCircles` works.
`draw_marker` generates its bits from the same OpenCV dictionary the detector
decodes against, so the marker either decodes to its id or it does not, and the
fixture has no way to be charitable to the code under test.

What these still prove is everything *around* the number: that tier C is an
answer rather than a failure, that the recovered scale matches the drawn one,
that a marker too small to defend is refused rather than believed, and that
tolerance widens when the measurement gets worse instead of staying a
decorative constant.

The distinction matters and is worth stating in the viva: **these tests prove
the arithmetic is right; only the ruler proves the answer is right.**
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.unit.synthetic import blank_label, draw_marker, draw_text, on_canvas, photograph
from vision.measure import (
    character_boxes,
    contrast_ratio,
    measure_cap_height,
    measure_numeral_height,
    numeral_box,
    to_mm,
)
from vision.measure.to_mm import GLYPH_SIGMA_PX, resolvable_threshold_mm
from vision.rectify import estimate_skew, find_label_quad, rectify
from vision.scale import tier_a, tier_c
from vision.scale.resolve import resolve_scale
from vision.types import Box, ScaleEstimate


def _label_with_declarations() -> tuple[np.ndarray, dict[str, object]]:
    label = blank_label()
    truth = {
        "mrp": draw_text(label, "MRP Rs. 45.00", baseline=(60, 120), cap_px=34),
        "qty": draw_text(label, "NET WT 250 g", baseline=(60, 230), cap_px=26),
        "mfg": draw_text(label, "MFG 03/2026", baseline=(60, 330), cap_px=18),
    }
    return label, truth


# ---------------------------------------------------------------------------
# M1 — rectify
# ---------------------------------------------------------------------------


def test_finds_the_label_outline_in_a_photograph():
    label, _ = _label_with_declarations()
    canvas = on_canvas(label)
    shot, _ = photograph(canvas)

    quad = find_label_quad(shot)
    assert quad is not None, "the label outline was not found in an off-axis photo"
    assert len(quad) == 4


def test_a_box_printed_on_the_label_does_not_become_the_label():
    """A close-up of a panel, with a barcode box printed on it. AKSHAR.md §8.

    `rectify` prefers a quad over every other method except a marker, so a quad
    accepted here becomes the whole scan and everything outside it is discarded
    before a region is proposed. On the declaration-block set that cost an
    entire photograph: `papad.jpg` has an octagonal label, which never matches
    as a quad, and the nutrition table printed inside it does — 13% of the
    frame, one legible line recovered, the scan degraded to L4.

    The frame here is the label, as it is in a close-up, so the only findable
    rectangle is one printed on it. Rectifying to that is strictly worse than
    not rectifying at all.
    """
    label = blank_label(width=900, height=700)
    draw_text(label, "MRP Rs. 45.00", baseline=(60, 90), cap_px=34)
    draw_text(label, "NET WT 250 g", baseline=(60, 170), cap_px=26)

    # A barcode block: a hard-edged dark rectangle over about 13% of the frame,
    # the same fraction the two junk quads in the delivered set came in at.
    x, y, w, h = 300, 380, 390, 210
    assert (w * h) / (900 * 700) == pytest.approx(0.13, abs=0.01)
    label[y : y + h, x : x + w] = 30

    assert find_label_quad(label) is None, "a box printed on the panel was taken for the panel"
    assert rectify(label).method != "quad"


@pytest.mark.parametrize(
    ("tilt", "yaw"),
    [(0.0, 0.0), (0.06, 0.04), (0.10, 0.06), (0.14, 0.09)],
)
def test_rectified_baselines_are_within_two_degrees(tilt: float, yaw: float):
    """M1's acceptance criterion, on a photograph whose distortion we chose."""
    label, _ = _label_with_declarations()
    shot, _ = photograph(on_canvas(label), tilt=tilt, yaw=yaw)

    result = rectify(shot)
    assert result.method == "quad", f"fell back to {result.method}"

    skew = estimate_skew(result.image)
    assert skew is not None, "no text lines found after rectification"
    assert abs(skew) < 2.0, f"residual skew {skew:.2f} deg exceeds M1's 2 deg budget"


def test_rectification_restores_the_label_aspect_ratio():
    """A warp that flattens the label must also restore its proportions.

    If it does not, `mm_per_px` is different horizontally and vertically, and a
    single scalar — which is what `LabelGeometry` stores — is a lie.
    """
    label, _ = _label_with_declarations()
    true_aspect = label.shape[1] / label.shape[0]
    shot, _ = photograph(on_canvas(label), tilt=0.12, yaw=0.07)

    result = rectify(shot)
    recovered = result.image.shape[1] / result.image.shape[0]
    assert abs(recovered - true_aspect) / true_aspect < 0.10


def test_rectify_falls_back_to_the_detector_box():
    """Section 17, M1: "falls back to the detector box when no clean quad"."""
    # A label with no findable outline: same tone as its surroundings.
    label, _ = _label_with_declarations()
    canvas = on_canvas(label, background=245)

    result = rectify(canvas, package_box=(230, 190, 760, 520))
    assert result.method == "detector_box"
    assert result.image.shape[0] < canvas.shape[0]


def test_rectify_never_raises_when_it_finds_nothing():
    """The system degrades; it does not fail. Section 5's whole premise."""
    noise = np.full((300, 400, 3), 128, dtype=np.uint8)
    result = rectify(noise)
    assert result.method in {"quad", "identity"}
    assert result.image is not None


# ---------------------------------------------------------------------------
# M2 — scale tier C, which must be built first and must always work
# ---------------------------------------------------------------------------


def test_tier_c_is_an_answer_not_a_failure():
    estimate = tier_c.estimate()
    assert estimate.tier == "C"
    assert estimate.mm_per_px is None
    assert not estimate.is_measurable
    assert "NO_DATA" in estimate.detail


def test_a_label_with_no_marker_yields_no_scale():
    """A frame full of print must not produce a scale from somewhere.

    This replaces `test_a_printed_zero_is_not_a_coin`, and the regression it
    guarded is worth remembering: `HoughCircles` returned the counter of the
    `0` in `MRP Rs. 45.00` as a Rs 5 coin, scaling every height on the pack by
    the ratio of a glyph to a coin — an order of magnitude of confident
    nonsense.

    **A marker cannot fail that way**, because it is not detected by shape but
    decoded: a run of black cells either satisfies the dictionary's error
    correction or it does not, and printed text does not accidentally spell a
    valid 4x4 codeword. That is why the failure mode disappeared rather than
    being patched. The test stays because the *consequence* still matters —
    inventing a scale is the worst thing this module can do.
    """
    label, _ = _label_with_declarations()
    shot, _ = photograph(on_canvas(label))

    assert tier_a.detect_markers(shot) == []

    result = rectify(shot)
    estimate = resolve_scale(
        shot, result.image, homography=result.homography, rectify_method=result.method
    )
    assert estimate.tier == "C", f"invented a scale from {estimate.detail}"


def test_tier_a_recovers_the_scale_it_was_given():
    """Draw a 25 mm marker at a known pixel size; the recovered mm/px must match.

    This is the arithmetic half of M2, and the bar is far higher than the coin
    fixture could support. Sub-pixel corners mapped through the homography
    should land within a fraction of a percent, not within eight.
    """
    label, _ = _label_with_declarations()
    canvas = on_canvas(label)
    edge_px = draw_marker(canvas, centre=(1010, 700), edge_px=110)

    marker = tier_a.marker_quad(canvas)
    assert marker is not None, "a cleanly drawn marker was not detected"

    result = rectify(canvas, marker=marker)
    estimate = tier_a.estimate(canvas, homography=result.homography, rectify_method=result.method)

    assert estimate is not None
    assert estimate.tier == "A"
    assert estimate.method == "aruco"
    assert estimate.mm_per_px is not None

    # Rectifying against the marker maps it to a square of its own mean edge
    # length, so the truth carries through unchanged.
    expected_mm_per_px = tier_a.MARKER_EDGE_MM / edge_px
    error = abs(estimate.mm_per_px - expected_mm_per_px) / expected_mm_per_px
    assert error < 0.01, f"scale off by {error:.2%}"


def test_rectifying_against_the_marker_beats_a_contour_quad():
    """Section 8b: four corners give the scale *and* the homography.

    A square is square by construction; a label outline is only assumed to be a
    rectangle. When a marker is supplied, `rectify` must use it — and the marker
    must then measure square afterwards, which is the self-check a coin can
    never offer, because a foreshortened circle and a smaller circle are the
    same picture.
    """
    label, _ = _label_with_declarations()
    canvas = on_canvas(label)
    draw_marker(canvas, centre=(1010, 700), edge_px=110)
    shot, _ = photograph(canvas, tilt=0.09, yaw=0.06)

    marker = tier_a.marker_quad(shot)
    assert marker is not None

    result = rectify(shot, marker=marker)
    assert result.method == "marker"

    estimate = tier_a.estimate(shot, homography=result.homography, rectify_method=result.method)
    assert estimate is not None
    # The "squareness" figure in the detail string is the residual perspective.
    assert "squareness 0.00" in estimate.detail, estimate.detail


def test_a_marker_too_small_to_defend_is_refused():
    """Decodable is not the same as measurable.

    A marker spanning a handful of pixels often decodes perfectly, and would
    give a scale we could not defend to 0.15 mm. `_MIN_EDGE_PX` refuses it and
    the scan falls to a lower tier, rather than reporting a number nobody can
    stand behind.
    """
    label, _ = _label_with_declarations()
    canvas = on_canvas(label)
    draw_marker(canvas, centre=(1010, 700), edge_px=16)

    assert tier_a.detect_markers(canvas) == []
    assert tier_a.estimate(canvas) is None


def test_resolve_prefers_a_measurement_over_an_inference():
    """Tier A beats tier B even when tier B has more history behind it.

    Tier B cannot notice that this packet is the 100 g pack of a SKU whose
    stored dimensions came from the 200 g one.
    """
    from vision.scale.tier_b import SkuDimensions

    label, _ = _label_with_declarations()
    canvas = on_canvas(label)
    draw_marker(canvas, centre=(1010, 700), edge_px=110)
    result = rectify(canvas, marker=tier_a.marker_quad(canvas))

    estimate = resolve_scale(
        canvas,
        result.image,
        homography=result.homography,
        rectify_method=result.method,
        cache_key="phash:deadbeef",
        lookup=lambda _key: SkuDimensions(
            sku_id="X", label_width_mm=120.0, observations=99, stddev_mm=0.1
        ),
    )
    assert estimate.tier == "A"


def test_tier_b_is_used_when_there_is_no_marker():
    from vision.scale.tier_b import SkuDimensions

    label, _ = _label_with_declarations()
    canvas = on_canvas(label)
    result = rectify(canvas)

    estimate = resolve_scale(
        canvas,
        result.image,
        homography=result.homography,
        rectify_method=result.method,
        cache_key="phash:deadbeef",
        lookup=lambda _key: SkuDimensions(
            sku_id="PARLE-G-100", label_width_mm=118.0, observations=7, stddev_mm=0.9
        ),
    )
    assert estimate.tier == "B"
    assert estimate.mm_per_px == pytest.approx(118.0 / result.image.shape[1], rel=1e-6)


def test_tier_b_refuses_a_single_observation():
    """One prior scan could be one bad marker fit, propagated forever."""
    from vision.scale.tier_b import SkuDimensions, estimate

    canvas = on_canvas(blank_label())
    assert (
        estimate(
            canvas,
            cache_key="phash:1",
            lookup=lambda _k: SkuDimensions(sku_id="X", label_width_mm=100.0, observations=1),
        )
        is None
    )


def test_implausible_scale_is_rejected_rather_than_reported():
    """A scale of 40 mm per pixel would make every glyph pass every rule."""
    from vision.scale.tier_b import SkuDimensions

    canvas = on_canvas(blank_label())
    result = rectify(canvas)
    estimate = resolve_scale(
        canvas,
        result.image,
        homography=result.homography,
        rectify_method=result.method,
        allow_tier_a=False,
        cache_key="phash:1",
        lookup=lambda _k: SkuDimensions(
            sku_id="X", label_width_mm=900_000.0, observations=9, stddev_mm=1.0
        ),
    )
    assert estimate.tier == "C"


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


def test_cap_height_matches_the_height_that_was_drawn():
    label = blank_label(600, 200)
    truth = draw_text(label, "MRP 45.00", baseline=(40, 140), cap_px=40)

    crop = label[int(truth.y) - 8 : int(truth.baseline_y) + 8, 20:580]
    measured = measure_cap_height(crop)

    assert measured is not None
    error = abs(measured.cap_height_px - truth.cap_height_px) / truth.cap_height_px
    assert error < 0.10, f"cap height {measured.cap_height_px:.1f} vs drawn {truth.cap_height_px}"


def test_cap_height_excludes_descenders():
    """The bug that would inflate every measurement by a quarter.

    `Net wt 250 g` has a descending `g`. If the descender is included, the
    measured height is roughly 1.3x the truth — enough to turn a 1.5 mm
    violation into a 2.0 mm pass on every pack in the country.
    """
    label = blank_label(700, 220)
    truth = draw_text(label, "Net wt 250 g", baseline=(40, 150), cap_px=40)
    crop = label[40:210, 20:680]

    measured = measure_cap_height(crop)
    assert measured is not None
    assert measured.cap_height_px < truth.cap_height_px * 1.15, (
        f"{measured.cap_height_px:.1f} px measured against a drawn cap height of "
        f"{truth.cap_height_px} px — the descender was counted"
    )


def test_no_measurement_is_returned_for_a_blank_crop():
    """Returning the crop height as a fallback would be a fabricated number."""
    assert measure_cap_height(np.full((40, 200, 3), 250, np.uint8)) is None


def test_numeral_height_is_measured_not_the_words():
    """Rule 7(2) prescribes the height of the NUMERALS.

    Words set smaller than the figures are extremely common — `Net Wt.` in
    8 pt beside `500 g` in 14 pt — and measuring the words understates the
    declaration, producing a violation that is not there.
    """
    label = blank_label(760, 240)
    draw_text(label, "Net Wt.", baseline=(40, 160), cap_px=16)
    draw_text(label, "500", baseline=(300, 160), cap_px=44)
    crop = label[60:200, 20:740]

    numerals = measure_numeral_height(crop, "Net Wt. 500")
    whole = measure_cap_height(crop)

    assert numerals is not None and whole is not None
    assert numerals > whole.cap_height_px * 0.95
    assert numerals == pytest.approx(44, rel=0.15)


def test_character_boxes_align_positionally_with_the_text():
    """`min_width_ratio` zips text against boxes; misalignment fires at random."""
    label = blank_label(560, 160)
    draw_text(label, "250 g", baseline=(30, 110), cap_px=44, thickness=3)
    crop = label[40:130, 20:400]
    origin = Box(x=20, y=40, w=380, h=90, panel_id="pdp")

    boxes = character_boxes(crop, "250 g", origin)
    assert len(boxes) in (0, len("250 g"))
    if boxes:
        # Boxes must run left to right in the same order as the characters.
        xs = [b.x for ch, b in zip("250 g", boxes, strict=True) if not ch.isspace()]
        assert xs == sorted(xs)


def test_character_boxes_are_empty_rather_than_wrong():
    """When segmentation disagrees with the text, emit nothing."""
    noise = np.random.default_rng(0).integers(0, 255, (60, 200, 3), dtype=np.uint8)
    origin = Box(x=0, y=0, w=200, h=60)
    boxes = character_boxes(noise, "MRP 45.00", origin)
    assert boxes == [] or len(boxes) == len("MRP 45.00")


def test_numeral_box_covers_only_the_digits():
    label = blank_label(640, 170)
    draw_text(label, "250 g", baseline=(30, 120), cap_px=48, thickness=3)
    crop = label[45:140, 20:420]
    origin = Box(x=20, y=45, w=400, h=95, panel_id="pdp")

    box = numeral_box(crop, "250 g", origin)
    if box is not None:
        assert box.w < origin.w, "the numeral box spans the whole declaration"
        assert box.panel_id == "pdp"


def test_contrast_ratio_ranks_legibility_correctly():
    def crop_with(ink: int) -> np.ndarray:
        image = blank_label(420, 120, bg=250)
        draw_text(image, "MRP 45", baseline=(30, 85), cap_px=40, colour=(ink, ink, ink))
        return image

    strong = contrast_ratio(crop_with(15))
    weak = contrast_ratio(crop_with(200))

    assert strong is not None and weak is not None
    assert strong > weak
    assert strong > 3.0, "black on white must clear the Rule 9(1)(b) threshold"
    assert weak < 3.0, "pale grey on white must not"


def test_contrast_is_none_when_there_is_nothing_to_measure():
    assert contrast_ratio(np.full((40, 120, 3), 250, np.uint8)) is None


# ---------------------------------------------------------------------------
# Tolerance propagation — what makes REVIEW mean something
# ---------------------------------------------------------------------------


def test_tier_c_yields_no_millimetres():
    height_mm, tolerance = to_mm(24.0, tier_c.estimate())
    assert height_mm is None and tolerance is None


def test_tolerance_grows_with_scale_uncertainty():
    """A worse marker fit must widen the band — but only down to the glyph floor.

    The two error terms add in quadrature, so tolerance cannot fall below the
    contribution of glyph-edge uncertainty however perfect the marker fit is.
    That floor is real: a flawless scale on an 8-pixel glyph is still an
    8-pixel glyph. Asserting an unbounded ratio here would be asserting that we
    can measure better than the photograph allows.
    """
    tight = ScaleEstimate(tier="A", mm_per_px=0.1, tolerance=0.001, method="aruco")
    loose = ScaleEstimate(tier="A", mm_per_px=0.1, tolerance=0.010, method="aruco")

    _, tolerance_tight = to_mm(24.0, tight)
    _, tolerance_loose = to_mm(24.0, loose)

    assert tolerance_tight is not None and tolerance_loose is not None
    assert tolerance_loose > tolerance_tight

    # The floor: mm_per_px * GLYPH_SIGMA_PX, reached when the scale is perfect.
    _, floor = to_mm(24.0, ScaleEstimate(tier="A", mm_per_px=0.1, tolerance=0.0, method="aruco"))
    assert floor == pytest.approx(0.1 * GLYPH_SIGMA_PX, rel=1e-6)
    assert tolerance_tight > floor

    # And when the scale is the dominant error, it is the term that shows.
    assert tolerance_loose == pytest.approx(24.0 * 0.010, rel=0.10)


def test_tolerance_grows_when_the_glyph_is_barely_resolved():
    """A 2 mm glyph photographed at 8 px cannot settle a 2 mm threshold.

    The tolerance must say so, which is what sends the verdict to REVIEW
    instead of asserting a violation an officer would have to withdraw.
    """
    scale = ScaleEstimate(tier="A", mm_per_px=0.25, tolerance=0.002, method="aruco")
    _, coarse = to_mm(8.0, scale)

    fine_scale = ScaleEstimate(tier="A", mm_per_px=0.05, tolerance=0.0004, method="aruco")
    _, fine = to_mm(40.0, fine_scale)

    assert coarse is not None and fine is not None
    assert coarse > fine, "a coarser photograph must report a wider tolerance"
    assert coarse > 0.1


def test_unrectified_measurements_are_less_certain():
    scale = ScaleEstimate(tier="A", mm_per_px=0.1, tolerance=0.001, method="aruco")
    _, rectified = to_mm(24.0, scale, rectified=True)
    _, raw = to_mm(24.0, scale, rectified=False)
    assert rectified is not None and raw is not None
    assert raw > rectified


def test_resolvable_threshold_reports_the_limit_of_the_photograph():
    scale = ScaleEstimate(tier="A", mm_per_px=0.25, tolerance=0.002, method="aruco")
    limit = resolvable_threshold_mm(scale)
    assert limit is not None and limit > 0.3
    assert resolvable_threshold_mm(tier_c.estimate()) is None


# ---------------------------------------------------------------------------
# The printed inspection card — §8b B3, and the thing U1 is shot against
# ---------------------------------------------------------------------------


def test_the_printed_card_is_detectable_at_the_resolution_a_phone_produces():
    """`scripts/make_marker_card.py` prints the card; this reads it back.

    A card that generates cleanly and cannot be found in a photograph is worse
    than no card: the ruler session that produced the U1 ground truth would come
    back with forty frames the pipeline cannot use, and nobody would know until
    day 7. So the board is rendered, downscaled to the long side a WhatsApp-sized
    frame actually has, and put through the same `tier_a.estimate` a scan uses.
    """
    import cv2

    from scripts.make_marker_card import SQUARE_MM, SQUARES_X, SQUARES_Y, build_board
    from vision.scale import tier_a

    board = build_board()
    # 40 px per millimetre when rendered, then downscaled — the printed card is
    # generated at 600 dpi and the phone reads it at rather less.
    rendered = board.generateImage(
        (int(SQUARES_X * SQUARE_MM * 40), int(SQUARES_Y * SQUARE_MM * 40))
    )
    scale = 1200 / rendered.shape[1]
    shot = cv2.resize(rendered, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    estimate = tier_a.estimate(cv2.cvtColor(shot, cv2.COLOR_GRAY2BGR))

    assert estimate is not None, "the printed card was not found in its own photograph"
    assert estimate.tier == "A"
    assert estimate.mm_per_px > 0


def test_the_card_prints_the_marker_at_the_size_the_code_measures():
    """The one number that turns pixels into millimetres, in one place.

    **This test previously asserted the wrong thing**, and the wrong thing was
    the natural reading: it required the ChArUco *square* to equal
    `MARKER_EDGE_MM`. But `tier_a` measures what `detectMarkers` returns, which
    is the black **ArUco marker** inside the square — and with OpenCV's usual
    0.75 ratio that marker is 25% smaller than the square. The printed card was
    therefore telling the code a length 33% larger than the one it was looking
    at, and every millimetre AKSHAR reported was wrong by that factor.

    Nothing about detection revealed it: all ten markers decoded, the scale
    resolved, the estimate looked healthy. It surfaced only when
    `scripts/make_u1_example.py` measured a digit of *known* physical height and
    got 2.45 mm for a 1.80 mm digit. Detection is not correctness.
    """
    from scripts.make_marker_card import MARKER_MM, SQUARE_MM
    from vision.scale.tier_a import MARKER_EDGE_MM

    assert MARKER_MM == MARKER_EDGE_MM, (
        "the printed marker's edge must be the length tier_a divides by"
    )

    # OpenCV refuses a board whose white margin is under 70% of one marker bit
    # cell. A 4x4 dictionary renders as 6x6 cells: 4 data bits plus a one-cell
    # black border on each side.
    cell = MARKER_MM / 6.0
    margin = (SQUARE_MM - MARKER_MM) / 2.0
    assert margin >= 0.7 * cell, (
        f"margin {margin:.2f} mm is under 70% of a {cell:.2f} mm bit cell; "
        f"the board will be unstable to detect"
    )


def test_the_worked_example_recovers_the_height_it_printed():
    """The whole U1 loop, on a scene whose true millimetres we chose.

    This is the regression guard for the card, and it is the only test here that
    can catch a *scale* error rather than a detection error. The scene is built
    in millimetres — the MRP digits really are `MRP_CAP_MM` tall — so measuring
    them back through the card exercises exactly the arithmetic the day-7 go/no-go
    scores, and a mis-sized card fails it immediately.

    Synthetic, so it proves the arithmetic and not the accuracy: a real lens, a
    real print and a real ruler are what U1 actually needs. The budget asserted
    here is deliberately the real one anyway, because a synthetic frame that
    cannot clear it has no chance on a photograph.
    """
    from scripts.make_u1_example import MRP_CAP_MM, build_scene
    from vision.scale import tier_a

    scene, mrp_box = build_scene()
    estimate = tier_a.estimate(scene)

    assert estimate is not None and estimate.tier == "A"
    recovered = mrp_box[3] * estimate.mm_per_px
    assert abs(recovered - MRP_CAP_MM) <= 0.15, (
        f"recovered {recovered:.2f} mm for a {MRP_CAP_MM} mm digit — the printed "
        f"card and vision.scale.tier_a disagree about a physical length"
    )
