"""The guard that would have saved the Glucon-D jar. `vision/scale/coherence.py`.

On 2026-09-19 an officer photographed a Glucon-D 250 g jar, typed **20** into
the pack-height box for a jar about 150 mm tall, and the system issued three
contraventions against a compliant pack -- among them `Rule 7(3), minimum letter
height, 0.38 mm against a required 1.00 mm`, for printing that is really 2.85 mm.

What makes it worth a file of its own is that **every guard that existed passed
it, correctly**. 20 mm is a plausible pack height; a sachet strip is 20 mm. The
plausibility band had no reason to object, there was no marker card to disagree
with, and the SKU had no stored dimension. Each guard asked "is this number
believable?" and the number was believable. What was wrong was the number
applied to *this photograph*, and the only evidence of that is in the result.
"""

from __future__ import annotations

import pytest

from contracts.declarations import Box, Declaration
from vision.scale import coherence

# The jar, as the system actually measured it: 0.015625 mm per pixel, because
# 20 mm was divided by a 1280 px frame.
GLUCON_D_MM = [0.25, 0.27, 0.27, 0.27, 0.29, 0.22, 0.38, 0.13, 0.08, 0.14]

# The same pack measured correctly, at 150 mm.
TRUTHFUL_MM = [h * 7.5 for h in GLUCON_D_MM]


def _declarations(heights: list[float | None]) -> list[Declaration]:
    return [
        Declaration(
            field="mrp",
            text="MRP Rs. 419.00",
            script="latin",
            box=Box(x=10.0, y=10.0 + 30 * index, w=200.0, h=24.0),
            height_px=18.0,
            height_mm=height,
            ocr_confidence=0.9,
            field_confidence=0.9,
        )
        for index, height in enumerate(heights)
    ]


# ---------------------------------------------------------------------------
# The incident
# ---------------------------------------------------------------------------


def test_the_glucon_d_jar_is_caught():
    reason = coherence.implausible(_declarations(GLUCON_D_MM))

    assert reason is not None
    assert "no press prints" in reason
    # The sentence has to tell the officer what to do about it, not just that
    # something is wrong.
    assert "centimetres" in reason
    assert "no measurement is reported" in reason


def test_the_same_pack_measured_correctly_is_not_caught():
    """The other half of the claim. A guard that fires on the truthful
    measurement too has not distinguished anything."""
    assert coherence.implausible(_declarations(TRUTHFUL_MM)) is None


# ---------------------------------------------------------------------------
# The one way this guard could do harm
# ---------------------------------------------------------------------------


def test_a_genuine_short_print_violation_is_never_suppressed():
    """The floor is 0.5 mm and the legal minimum is 1.0 mm, and the whole
    safety of this check lives in that gap.

    A pack that really does breach Rule 7(3) prints at 0.7 or 0.8 mm. Put the
    floor at the legal minimum instead and this check would quietly delete
    every genuine short-print finding -- it would protect the offender it was
    written to catch.
    """
    for offending in (0.6, 0.7, 0.8, 0.9):
        heights = [offending] * 8
        assert coherence.implausible(_declarations(heights)) is None, offending


def test_nothing_this_check_does_can_invent_a_contravention():
    """It only ever removes measurements. The three height rules then return
    NO_DATA, and NO_DATA is never FAIL -- absence of a measurement is not
    evidence of a short one."""
    caught = coherence.implausible(_declarations(GLUCON_D_MM))
    assert isinstance(caught, str)
    # There is no code path that returns a *tighter* measurement, only None or
    # a sentence. The type is the proof.
    assert coherence.implausible(_declarations(TRUTHFUL_MM)) is None


# ---------------------------------------------------------------------------
# Why a median
# ---------------------------------------------------------------------------


def test_one_garbled_line_does_not_condemn_a_good_scale():
    """A recogniser error on a single line measures small. The scale being
    wrong moves everything at once, which is what a median sees."""
    heights = [2.4, 2.1, 2.6, 2.2, 0.08, 2.3, 2.5]
    assert coherence.implausible(_declarations(heights)) is None


def test_too_few_measurements_is_not_evidence_of_anything():
    assert coherence.implausible(_declarations([0.2, 0.2, 0.2])) is None
    assert coherence.MIN_MEASUREMENTS == 4


def test_declarations_with_no_measurement_are_ignored_not_counted_as_zero():
    """Tier C measured nothing. Counting a `None` as 0.0 mm would make every
    scale-free scan look impossible."""
    assert coherence.measured_heights(_declarations([None, None, 2.1, 2.2])) == [2.1, 2.2]
    assert coherence.implausible(_declarations([None] * 10)) is None


# ---------------------------------------------------------------------------
# The other direction
# ---------------------------------------------------------------------------


def test_a_height_entered_far_too_large_is_caught_too():
    """1500 typed for 150. No declaration on a packaged commodity is set at
    twenty millimetres."""
    reason = coherence.implausible(_declarations([21.0, 24.0, 22.0, 26.0, 23.0]))

    assert reason is not None
    assert "larger than any declaration" in reason


@pytest.mark.parametrize("height", [0.5, 1.0, 2.85, 14.9])
def test_the_whole_printable_range_passes(height):
    assert coherence.implausible(_declarations([height] * 8)) is None


def test_every_sentence_an_officer_reads_is_ascii():
    """These reach `ScaleEstimate.detail`, which `cv2.putText` prints on the
    annotated exhibit one black lozenge per character it cannot render."""
    for heights in (GLUCON_D_MM, [21.0] * 6):
        reason = coherence.implausible(_declarations(heights))
        assert reason is not None and reason.isascii(), reason
