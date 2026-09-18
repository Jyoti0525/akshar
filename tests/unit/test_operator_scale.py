"""Scale from a height the officer measured with a ruler and typed in.

    "see we can make it like this like whenever someone gives something there
     will be a place for entering the height of that product so the user enters
     based on that we can then go for character measurements right ???"

This is the tier that makes the system usable, and it is worth being precise
about why it is not the thing it superficially resembles.

A guessed pack size and a measured one produce identical arithmetic. They are
not identical evidence. The number here comes off a ruler and is recorded in
the scan, so a manufacturer disputing a measurement is disputing a **stated
premise they can re-check**. A premise that turns out wrong is an error
somebody can find. An assumed one is an error nobody can.

The other half of this file is the typo. `95` and `9.5` are one keystroke apart
and the second is a factor of ten, with no visible symptom: every letter simply
measures ten times too small and every height rule fails a compliant pack. That
is the exact false accusation this project exists to prevent, so it gets three
guards and all three are tested here.
"""

from __future__ import annotations

import numpy as np
import pytest

from vision.scale import operator
from vision.scale.resolve import resolve_scale
from vision.types import ScaleEstimate

RECTIFIED = np.zeros((600, 400, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------


def test_a_typed_height_measures_the_photograph():
    estimate = operator.estimate(RECTIFIED, height_mm=120.0)
    assert estimate is not None
    assert estimate.tier == "A"
    assert estimate.method == "operator_height"
    assert estimate.mm_per_px == pytest.approx(0.2)
    assert "120.0 mm" in estimate.detail


def test_it_is_tier_a_because_it_is_a_length_in_this_photograph():
    """Not tier B. Tier B is an inference from *other* photographs of the SKU;
    this is a physical dimension of the object in front of the camera, which is
    the same kind of evidence as the marker card and ranks with it in
    `rules.checks._common._SCALE_RANK`."""
    assert operator.estimate(RECTIFIED, height_mm=120.0).tier == "A"  # type: ignore[union-attr]


def test_no_height_entered_is_an_ordinary_absence():
    assert operator.estimate(RECTIFIED, height_mm=None) is None


def test_a_decimal_slip_is_refused_rather_than_measured():
    """`9.5` typed for `95`, and the reverse. Neither has a visible symptom."""
    low, high = operator.PLAUSIBLE_HEIGHT_MM
    assert operator.estimate(RECTIFIED, height_mm=low - 1) is None
    assert operator.estimate(RECTIFIED, height_mm=high + 1) is None
    # ...and a real sachet and a real cement sack both stay inside the band,
    # because this catches decimal points and does not second-guess officers.
    assert operator.estimate(RECTIFIED, height_mm=8.0) is not None
    assert operator.estimate(RECTIFIED, height_mm=900.0) is not None


def test_a_padded_crop_reports_a_wider_band_than_a_clean_quad():
    """The detector box is larger than the face the ruler was held against, so
    the entered height and the pixel height describe different rectangles."""
    clean = operator.estimate(RECTIFIED, height_mm=120.0, rectify_method="quad")
    padded = operator.estimate(RECTIFIED, height_mm=120.0, rectify_method="detector_box")
    assert clean is not None and padded is not None
    assert clean.mm_per_px == pytest.approx(padded.mm_per_px)
    assert padded.tolerance > clean.tolerance  # type: ignore[operator]


def test_a_small_pack_is_measured_less_precisely_than_a_large_one():
    """Half a millimetre of ruler error is 5% of a 10 mm sachet and 0.4% of a
    120 mm carton. The tolerance has to say so, or a REVIEW band computed on a
    sachet would claim a precision the ruler never had."""
    sachet = operator.estimate(RECTIFIED, height_mm=10.0)
    carton = operator.estimate(RECTIFIED, height_mm=120.0)
    assert sachet is not None and carton is not None
    relative = lambda e: e.tolerance / e.mm_per_px  # noqa: E731
    assert relative(sachet) > relative(carton)


# ---------------------------------------------------------------------------
# Where it sits in the ladder
# ---------------------------------------------------------------------------


def test_the_marker_is_looked_for_first_even_when_a_height_was_typed():
    """Order matters: the marker is measured from the image, the height is typed
    by a person, and when both are available the measured one wins. A blank
    frame contains no marker, so here the typed height is what answers -- which
    is itself the point, because the search happened and cost nothing."""
    scale = resolve_scale(
        RECTIFIED,
        RECTIFIED,
        operator_height_mm=120.0,
        allow_tier_a=True,
    )
    assert scale.method == "operator_height"


def test_a_typed_height_answers_where_there_is_no_marker():
    """Which, on the 231 millimetre-grade frames in this corpus, is all of them:
    zero contain an ArUco marker. Before this tier existed every one of them
    fell to tier C and the three height rules went dark."""
    scale = resolve_scale(RECTIFIED, RECTIFIED, operator_height_mm=150.0)
    assert scale.tier == "A"
    assert scale.mm_per_px == pytest.approx(0.25)


def test_no_height_and_no_marker_is_still_tier_c_and_never_an_error():
    scale = resolve_scale(RECTIFIED, RECTIFIED, operator_height_mm=None)
    assert scale.tier == "C"
    assert scale.mm_per_px is None


def test_an_implausible_entry_falls_through_and_says_so():
    """It does not fail the scan. Tier C is a real answer and 28 of the 31
    rules still run against it."""
    scale = resolve_scale(RECTIFIED, RECTIFIED, operator_height_mm=3.0)
    assert scale.tier == "C"
    assert "3 mm" in scale.detail


# ---------------------------------------------------------------------------
# The cross-check, which is the guard that catches the keystroke
# ---------------------------------------------------------------------------


def marker_at(mm_per_px: float) -> ScaleEstimate:
    return ScaleEstimate(
        tier="A", mm_per_px=mm_per_px, tolerance=mm_per_px * 0.01, method="aruco",
        detail="ArUco DICT_4X4_50 id 7",
    )


def test_two_measurements_that_agree_change_nothing():
    from vision.scale.resolve import _cross_checked

    marker = marker_at(0.2)
    typed = operator.estimate(RECTIFIED, height_mm=120.0)  # also 0.2
    assert _cross_checked(marker, typed) is marker


def test_a_factor_of_ten_disagreement_widens_the_band_and_is_printed():
    """The keystroke. `12.0` typed instead of `120.0`.

    The marker still wins -- it is measured rather than typed -- but a scan that
    saw both numbers and said nothing would be hiding evidence it already had.
    So the disagreement becomes the tolerance, and the sentence an officer reads
    names both suspects: the entered height, and a card lying at a different
    distance from the camera than the label.
    """
    from vision.scale.resolve import _cross_checked

    marker = marker_at(0.2)
    typed = operator.estimate(RECTIFIED, height_mm=12.0)
    checked = _cross_checked(marker, typed)

    assert checked.mm_per_px == pytest.approx(0.2), "the marker must still win"
    assert checked.tolerance > (marker.tolerance or 0.0)
    assert "disagrees by 90%" in checked.detail
    assert "entered height" in checked.detail


def test_the_cross_check_never_fails_the_scan():
    from vision.scale.resolve import _cross_checked

    assert _cross_checked(marker_at(0.2), None).mm_per_px == pytest.approx(0.2)


def test_every_detail_string_is_ascii():
    """These are printed on the annotated exhibit by `cv2.putText`, which
    renders one black lozenge per non-ASCII character -- on a legal document,
    in the line that explains where the measurement came from."""
    from vision.scale.resolve import _cross_checked

    for estimate in (
        operator.estimate(RECTIFIED, height_mm=120.0),
        _cross_checked(marker_at(0.2), operator.estimate(RECTIFIED, height_mm=12.0)),
        resolve_scale(RECTIFIED, RECTIFIED, operator_height_mm=3.0),
    ):
        assert estimate is not None and estimate.detail.isascii(), estimate.detail
