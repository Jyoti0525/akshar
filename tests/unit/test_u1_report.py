"""Scoring the ruler set — AKSHAR.md sections 18b (U1) and 19.

These test the arithmetic, not the measurement: `summarise` is a pure function
over `(truth, measured, tolerance)` triples, so the go/no-go rule can be
asserted without a camera, a card or a model.

The three things worth guarding are the three ways this number could flatter us:
dropping the frames we could not read, reporting a mean that hides an outlier,
and reporting an error bar narrower than the error it describes.
"""

from __future__ import annotations

import pytest

from scripts.u1_report import (
    COVERAGE_TARGET,
    MAE_TARGET_MM,
    Reading,
    summarise,
)


def _readings(pairs, *, tolerance=0.2):
    return [
        Reading(filename=f"f{i}.jpg", truth_mm=t, measured_mm=m, tolerance_mm=tolerance)
        for i, (t, m) in enumerate(pairs)
    ]


def test_a_frame_we_could_not_read_stays_in_the_denominator():
    """The dashboard's NO_DATA rule, applied to the accuracy claim.

    Averaging over the frames that worked and calling it the U1 result is the
    same mistake as excluding an unreadable scan from a compliance rate: the
    number improves precisely because the system did worse.
    """
    readings = [
        *_readings([(1.8, 1.82), (2.0, 2.01)]),
        Reading(filename="dark.jpg", truth_mm=1.5, note="nothing legible (L4)"),
    ]

    report = summarise(readings)

    assert report.total == 3
    assert report.measured == 2
    assert report.measured_share == pytest.approx(2 / 3)
    met, problems = report.verdict()
    assert not met
    assert "easy half" in problems[0]


def test_the_mean_alone_cannot_carry_the_verdict():
    """A good MAE must not survive a scatter of bad frames.

    The outliers here are 0.6 mm rather than wild: big enough to lose a case on,
    small enough that averaging them into eighteen perfect frames still yields a
    respectable 0.06 mm mean. That is the case p95 exists for — a gross blunder
    would fail MAE as well and prove nothing about the second criterion.
    """
    # Two bad frames in twenty puts the 19th value — what nearest-rank p95 reads
    # at n=20 — onto a bad one.
    pairs = [(1.80, 1.80) for _ in range(18)] + [(1.80, 2.40), (1.80, 2.40)]
    report = summarise(_readings(pairs, tolerance=0.2))

    assert report.mae_mm is not None and report.mae_mm <= MAE_TARGET_MM
    met, problems = report.verdict()
    assert not met, "a passing mean must not carry a failing p95"
    assert any("p95" in problem for problem in problems)


def test_a_single_blunder_is_below_p95s_resolution_and_is_named_instead():
    """The honest limit of this scoring, asserted rather than hoped away.

    One bad frame in twenty is the 5th percentile of failures, so nearest-rank
    p95 reads a clean value and coverage stays at 95% — above the 90% target.
    Every threshold passes, and that is arithmetically correct rather than a
    bug: a percentile cannot resolve a single sample.

    The response is not to invent a fourth gate the plan never set. It is to
    **name the frame**, so the person reading the report looks at it. Silently
    passing it while knowing this is what would make the number dishonest.
    """
    pairs = [(1.80, 1.80) for _ in range(19)] + [(1.80, 3.90)]
    report = summarise(_readings(pairs, tolerance=0.2))

    met, _ = report.verdict()
    assert met, "one outlier in twenty genuinely does clear MAE, p95 and coverage"
    assert report.uncovered == ("f19.jpg",)
    assert report.worst_mm == pytest.approx(2.10)


def test_p95_is_an_observation_not_an_interpolation():
    """Nearest-rank: with 20 samples p95 is the 19th, a height something really was."""
    errors = [0.01 * i for i in range(1, 21)]
    report = summarise(_readings([(1.0, 1.0 + e) for e in errors], tolerance=1.0))

    assert report.p95_mm == pytest.approx(0.19)
    assert report.worst_mm == pytest.approx(0.20)


def test_an_error_bar_narrower_than_the_error_fails_even_when_accuracy_passes():
    """The check §18b does not make, and the one that decides real cases.

    `min_height_mm` turns the tolerance into the REVIEW band. Claim ±0.02 mm
    while really being out by 0.10 mm and the band is five times too narrow — so
    packs that were inside our own measurement error get FAIL instead of REVIEW.
    MAE says nothing about it: 0.10 mm is a fine MAE.
    """
    pairs = [(1.80, 1.90) for _ in range(20)]
    report = summarise(_readings(pairs, tolerance=0.02))

    assert report.mae_mm == pytest.approx(0.10)
    assert report.mae_mm <= MAE_TARGET_MM
    assert report.coverage == 0.0

    met, problems = report.verdict()
    assert not met
    assert any("REVIEW band" in problem for problem in problems)
    assert len(report.uncovered) == 20


def test_an_honest_error_bar_passes():
    pairs = [(1.80, 1.80 + 0.04 * (-1) ** i) for i in range(20)]
    report = summarise(_readings(pairs, tolerance=0.12))

    assert report.coverage == 1.0
    assert report.coverage >= COVERAGE_TARGET
    met, problems = report.verdict()
    assert met, problems


def test_a_constant_offset_shows_up_as_bias_not_as_noise():
    """The mis-sized card, caught by its signature.

    Printing a 25 mm chessboard square when the code measures the 18.75 mm
    marker inside it made every reading 33% high. Absolute error cannot tell
    that from random scatter; a signed mean can, and the fix is a printer
    setting rather than a better algorithm.
    """
    pairs = [(t, t * 1.333) for t in (1.2, 1.8, 2.4, 3.0)]
    report = summarise(_readings(pairs, tolerance=0.2))

    assert report.bias_mm is not None and report.bias_mm > 0.3
    scattered = summarise(_readings([(1.8, 1.8 + 0.1 * (-1) ** i) for i in range(4)]))
    assert scattered.bias_mm == pytest.approx(0.0, abs=1e-9)


def test_an_empty_set_reports_nothing_rather_than_zero():
    """No frames is not a perfect score."""
    report = summarise([])

    assert report.mae_mm is None
    assert report.coverage is None
    assert not report.verdict()[0]


# ---------------------------------------------------------------------------
# Repeatability — why 20 SKUs x 2 photos, and not 40 SKUs x 1
# ---------------------------------------------------------------------------


def test_two_shots_of_one_packet_measure_our_own_spread():
    """The one figure here that needs no ruler at all.

    The printed digit did not change between the two frames, so whatever the two
    AKSHAR readings disagree by is ours. That is a claim about the system's
    stability under ordinary capture variation, and it is available on every
    pair — including, later, on packets nobody ever measured.
    """
    readings = [
        Reading(filename="a1.jpg", truth_mm=1.8, measured_mm=1.78, product="Parle-G 100 g"),
        Reading(filename="a2.jpg", truth_mm=1.8, measured_mm=1.84, product="Parle-G 100 g"),
        Reading(filename="b1.jpg", truth_mm=2.4, measured_mm=2.40, product="Amul 500 ml"),
        Reading(filename="b2.jpg", truth_mm=2.4, measured_mm=2.42, product="Amul 500 ml"),
    ]

    report = summarise(readings)

    # (0.06 + 0.02) / 2
    assert report.repeatability_mm == pytest.approx(0.04)


def test_one_photo_per_packet_reports_no_repeatability_rather_than_zero():
    """Forty distinct SKUs would leave this blank, which is the argument for pairs.

    Zero would read as "perfectly repeatable", which is the opposite of the
    truth — nothing was repeated, so nothing is known.
    """
    readings = [
        Reading(filename="a.jpg", truth_mm=1.8, measured_mm=1.78, product="Parle-G 100 g"),
        Reading(filename="b.jpg", truth_mm=2.4, measured_mm=2.40, product="Amul 500 ml"),
    ]

    assert summarise(readings).repeatability_mm is None


def test_two_pack_sizes_of_one_brand_are_not_the_same_packet():
    """Section 10's unique constraint, applied to the scoring.

    30 g and 100 g of one product have different height thresholds and different
    printed artwork. Grouping their shots together would report the difference
    between two packets as if it were our own instability.
    """
    readings = [
        Reading(filename="a.jpg", truth_mm=1.2, measured_mm=1.20, product="Parle-G 30 g"),
        Reading(filename="b.jpg", truth_mm=1.8, measured_mm=1.80, product="Parle-G 100 g"),
    ]

    assert summarise(readings).repeatability_mm is None
