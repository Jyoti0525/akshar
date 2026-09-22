"""A height measured across two printed lines must not claim single-line precision.

AKSHAR.md sections 7, 18b.

`CapHeightResult.confidence` has always been computed and has always said what
to do with itself:

    "Low confidence means a multi-line or badly segmented crop, and the caller
     should widen tolerance rather than assert a height."

No caller read it. `vision/ocr/roi.py` measured it and passed only
`cap_height_px` on, so a cap height taken across a caption and a value at two
different sizes arrived at `min_height_mm` carrying exactly the same +/- as one
measured off a clean single line.

That band is legally load-bearing. `min_height_mm` returns REVIEW instead of
FAIL when `measured + tolerance >= threshold`, so a tolerance that is too
narrow is the difference between flagging a pack for an officer and asserting
that it breaks Rule 7(3).

The widening is a ratio, not a picked constant, which is why these tests assert
relationships rather than numbers: half the ink agreeing means twice the
uncertainty, all of it agreeing means no change at all.
"""

from __future__ import annotations

import pytest

from vision.measure.to_mm import GLYPH_SIGMA_PX, MIN_SEGMENTATION_CONFIDENCE, to_mm
from vision.types import ScaleEstimate

SCALE = ScaleEstimate(tier="A", mm_per_px=0.1, tolerance=0.0002, method="aruco")


def _tolerance(confidence: float | None) -> float:
    _mm, tol = to_mm(20.0, SCALE, segmentation_confidence=confidence)
    assert tol is not None
    return tol


def test_a_badly_segmented_crop_carries_a_wider_band():
    clean = _tolerance(1.0)
    messy = _tolerance(0.5)
    assert messy > clean, "a crop whose ink disagreed claimed the same precision"


def test_the_widening_is_the_reciprocal_of_the_agreement():
    """Half the ink agreeing is twice the glyph uncertainty.

    Asserted on the glyph term alone: the scale term is independent of how the
    crop segmented and must not move with it.
    """
    mm_per_px = SCALE.mm_per_px
    assert mm_per_px is not None
    glyph_term = mm_per_px * GLYPH_SIGMA_PX

    for confidence in (1.0, 0.8, 0.5, 0.25):
        tol = _tolerance(confidence)
        scale_term = 20.0 * (SCALE.tolerance or 0.0)
        recovered = (tol**2 - scale_term**2) ** 0.5
        assert recovered == pytest.approx(glyph_term / confidence, rel=1e-6)


def test_omitting_the_confidence_changes_nothing():
    """Every caller that has no such measurement must get the old behaviour.

    `None` is not "perfectly segmented" and not "badly segmented" — it is a
    line whose cap height came from somewhere that does not report agreement,
    and inventing either answer for it would be the fabrication this module
    refuses elsewhere.
    """
    assert _tolerance(None) == _tolerance(1.0)


def test_a_pathological_crop_widens_by_a_bounded_amount():
    """Never `inf`, and never a division by zero.

    A crop this badly segmented should be producing no height at all. The floor
    is here so that an arithmetic edge case cannot turn a verdict into nonsense
    while we are still measuring how often it happens.
    """
    floored = _tolerance(0.0)
    assert floored == pytest.approx(_tolerance(MIN_SEGMENTATION_CONFIDENCE))
    assert floored < float("inf")


def test_confidence_above_one_is_not_allowed_to_narrow_the_band():
    """Clamped, so a stray value can never claim more precision than we have."""
    assert _tolerance(2.0) == pytest.approx(_tolerance(1.0))


def test_the_height_itself_is_untouched():
    """This widens the uncertainty. It must not move the measurement."""
    baseline, _ = to_mm(20.0, SCALE)
    for confidence in (1.0, 0.5, 0.2, 0.0):
        value, _tol = to_mm(20.0, SCALE, segmentation_confidence=confidence)
        assert value == baseline


def test_the_measurement_survives_a_line_being_split():
    """`sentences.split` rebuilds an OcrLine; the agreement must travel with it.

    A field dropped on reconstruction restores the old behaviour silently, for
    exactly the crops most likely to need the widening — a crop that had to be
    split is one whose ink did not agree in the first place.
    """
    from vision.types import Box, OcrLine

    line = OcrLine(
        text="MRP 45.00",
        box=Box(x=0.0, y=0.0, w=100.0, h=20.0),
        confidence=0.9,
        script="latin",
        cap_height_px=14.0,
        cap_height_confidence=0.4,
    )
    assert line.cap_height_confidence == 0.4
