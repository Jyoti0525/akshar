"""B1, the capture-quality gate. AKSHAR.md section 8, section 17 (M0).

**These are not the acceptance tests.** Section 17's criterion for M0 is a
recall figure against the deliberately-bad subset of the field corpus, and that
subset does not exist yet. What is asserted here is the behaviour the gate must
have for any threshold at all to be meaningful: that each fault is detected on
a frame constructed to have exactly that fault, that a good frame survives all
four checks, and that the whole thing fits the 15 ms budget.

The one test worth reading is
`test_a_well_exposed_white_packet_is_not_mistaken_for_glare`. Salt, sugar, flour
and most pharmaceutical cartons are near-white, they are the easiest labels in
the country to read, and an exposure test written against the mean rejects all
of them.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from contracts import ADVICE, CaptureQuality
from vision.quality import THRESHOLDS, assess


def _label(background: int = 232, width: int = 1600, height: int = 1200) -> np.ndarray:
    """A synthetic packet: dark print on a light ground, unevenly lit.

    The vignette is not decoration. A perfectly flat synthetic ground is the one
    input real photographs never produce, and writing the thresholds against it
    tunes the gate for an image that cannot occur.
    """
    image = np.full((height, width, 3), background, np.uint8)
    lines = (
        "MRP Rs. 45.00 (incl. of all taxes)",
        "Net Wt. 250 g",
        "Mfd by Example Foods Pvt Ltd",
        "Consumer care 1800-266-3456",
    )
    for index, text in enumerate(lines):
        cv2.putText(
            image, text, (60, 220 + index * 230), cv2.FONT_HERSHEY_SIMPLEX, 3.0, (18, 18, 18), 9
        )

    ys, xs = np.mgrid[0:height, 0:width]
    radius = np.sqrt(((xs - width / 2) / (width / 2)) ** 2 + ((ys - height / 2) / (height / 2)) ** 2)
    image = (image.astype(np.float32) * (1.0 - 0.22 * np.clip(radius, 0, 1))[..., None]).astype(
        np.uint8
    )

    rng = np.random.default_rng(20260909)
    return np.clip(image.astype(np.int16) + rng.integers(-6, 6, image.shape), 0, 255).astype(
        np.uint8
    )


# ---------------------------------------------------------------------------
# The good case
# ---------------------------------------------------------------------------


def test_a_sharp_well_lit_label_passes_every_check() -> None:
    quality = assess(_label())

    assert quality.usable
    assert quality.faults == ()
    assert quality.reason is None
    assert quality.blur_score > THRESHOLDS.min_blur_score
    assert quality.glare_ratio < THRESHOLDS.max_glare_ratio


def test_a_well_exposed_white_packet_is_not_mistaken_for_glare() -> None:
    """The false-positive that matters, because it is the commonest packaging.

    A near-white pack filling the frame has a mean luminance around 245. An
    exposure test written against the mean — which is the obvious way to write
    one — rejects every packet of salt, sugar and flour in the country while
    passing a grey pack photographed in a dark shop, which is backwards.
    """
    quality = assess(_label(background=250))

    assert quality.usable, f"rejected a readable white pack: {quality.faults}"
    assert "overexposed" not in quality.faults
    assert "glare" not in quality.faults


# ---------------------------------------------------------------------------
# One test per fault
# ---------------------------------------------------------------------------


def test_out_of_focus_blur_is_rejected() -> None:
    quality = assess(cv2.GaussianBlur(_label(), (0, 0), 9))

    assert not quality.usable
    assert "blur" in quality.faults
    assert quality.reason == ADVICE["blur"]


@pytest.mark.parametrize("kernel", [(1, 35), (35, 1)])
def test_directional_motion_blur_is_rejected_on_either_axis(kernel: tuple[int, int]) -> None:
    """The case a variance-of-Laplacian gate silently passes.

    Hand-shake in a shop is directional. A sideways smear destroys the vertical
    strokes of the digits and leaves the horizontal ones, so the Laplacian —
    which sums both second derivatives — still finds plenty of edge energy and
    calls the frame sharp. The gate measures each axis and keeps the worse one;
    without that, this frame scored 0.32 against a 0.18 threshold and a
    motion-blurred `8` went on to be read, confidently, as a `3`.
    """
    smear = np.ones(kernel, np.float32) / float(kernel[0] * kernel[1])
    quality = assess(cv2.filter2D(_label(), -1, smear))

    assert not quality.usable
    assert "blur" in quality.faults


def test_a_specular_highlight_across_the_label_is_rejected() -> None:
    image = _label()
    cv2.ellipse(image, (800, 600), (620, 430), 20, 0, 360, (255, 255, 255), -1)

    quality = assess(image)

    assert not quality.usable
    assert "glare" in quality.faults
    assert quality.glare_ratio > THRESHOLDS.max_glare_ratio


def test_an_underexposed_frame_is_rejected() -> None:
    quality = assess((_label() * 0.09).astype(np.uint8))

    assert not quality.usable
    assert "underexposed" in quality.faults


def test_an_overexposed_frame_is_rejected() -> None:
    washed = np.clip(_label().astype(np.int16) + 120, 0, 255).astype(np.uint8)

    quality = assess(washed)

    assert not quality.usable
    assert "overexposed" in quality.faults


def test_a_frame_too_small_to_measure_is_rejected_before_anything_else() -> None:
    """And the advice is "move closer", not "hold still".

    A pack photographed from across the aisle is blurry *because* it is small.
    Reporting the blur first sends the officer back to hold the camera steadier,
    which will not help.
    """
    small = cv2.resize(_label(), (420, 315))

    quality = assess(small)

    assert not quality.usable
    assert quality.faults[0] == "resolution"
    assert quality.reason == ADVICE["resolution"]


# ---------------------------------------------------------------------------
# Contract and budget
# ---------------------------------------------------------------------------


def test_every_fault_has_advice_for_the_person_holding_the_phone() -> None:
    from typing import get_args

    from contracts.quality import QualityFault

    assert set(ADVICE) == set(get_args(QualityFault))
    for text in ADVICE.values():
        assert text.endswith("."), text


def test_it_reports_every_fault_not_only_the_first() -> None:
    """A photograph taken into the sun is both blown and over-exposed.

    Telling the officer one of the two sends them back for a second attempt
    that fails in exactly the same way.
    """
    into_the_sun = np.clip(_label().astype(np.int16) + 120, 0, 255).astype(np.uint8)

    quality = assess(into_the_sun)

    assert len(quality.faults) >= 2
    assert len(quality.advice()) == len(quality.faults)


def test_the_gate_costs_less_than_the_work_it_saves() -> None:
    """Section 4 budgets B1 at under 15 ms. A gate slower than that is a tax.

    Measured on a downscaled working copy, so this holds for a 48-megapixel
    phone photograph as well as for the 2-megapixel frame here. The margin is
    generous because CI machines are not fast and a flaky timing test gets
    deleted, which would remove the only check on a real budget.

    **The fastest of several runs, not one.** A single sample measures the gate
    plus whatever else the machine was doing, and on 2026-09-10 this failed
    inside a full-suite run while `bench/` measured B1 at 10.2 ms mean in the
    same session — a six-fold margin lost to a scheduler stall, not to the code.
    The minimum is the honest estimate of what the work costs; the maximum is a
    measurement of the load. Taking the best of five keeps the 60 ms bar meaning
    what it says instead of quietly becoming a machine-quietness test.
    """
    image = _label(width=3200, height=2400)
    assess(image)  # warm OpenCV's own lazy initialisation

    fastest = min(assess(image).elapsed_ms for _ in range(5))

    assert fastest < 60.0, f"B1 took {fastest:.1f} ms at best over five runs"


def test_scores_all_run_in_the_same_direction() -> None:
    """Higher is better, for every score including glare's inverse.

    A scoreboard where one column runs the other way is how a threshold ends up
    applied backwards, and backwards here means accepting the blurred frames.
    """
    good = assess(_label())
    bad = assess(cv2.GaussianBlur(_label(), (0, 0), 9))

    assert good.blur_score > bad.blur_score
    assert good.glare_score == pytest.approx(1.0 - good.glare_ratio)
    assert isinstance(good, CaptureQuality)


def test_it_never_returns_a_verdict() -> None:
    """B1 measures. Only the rulepack decides — sections 3 and 8.

    Guarded by a test because "usable: false" is one careless refactor away from
    becoming "this package fails", and the two mean opposite things: the first
    is a statement about our photograph, the second an accusation against a
    manufacturer.
    """
    fields = set(CaptureQuality.model_fields)

    assert not fields & {"status", "verdict", "compliant", "rule_id", "severity"}
