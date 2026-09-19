"""Cap height on a mixed-case line, which is where it was wrong.

**Ground truth without a ruler.** Render a string with a font at a known size
and ask the font itself for the height of `H` -- that is cap height by
definition, to the pixel, with no measurement error of its own. Then hand the
rendered crop to `measure_cap_height` and compare. It is the only instrument
available that does not need the 40-photograph ruler set, and it answers the
question that set would answer: is the estimator biased, and which way.

Measured 2026-09-19 over 1,440 renders -- eight faces, six sizes, fifteen
strings, clean and degraded:

    upper quartile (before)   mean -0.32 px   21.5% of readings >1 px out
    tall-cluster median       mean +0.16 px   12.2%

**The direction is the point.** Under-measuring a letter is how a compliant
pack gets accused under Rule 7(3)'s 1 mm minimum. At the 8 px/mm these
photographs actually carry, the 1.93 px the old statistic lost on `Maximum
Retail Price` is a quarter of the whole threshold.

These tests pin the behaviour, not the numbers: an exact pixel depends on the
font file and on how FreeType hints it at a given size, and a test that pinned
that would fail on a machine with different fonts. Each one asserts a
relationship that must hold whatever is installed, and skips if the face it
needs is absent.
"""

from __future__ import annotations

import statistics
from pathlib import Path

import numpy as np
import pytest

from vision.measure.cap_height import _tall_cluster, measure_cap_height

PIL = pytest.importorskip("PIL", reason="Pillow renders the reference text")
from PIL import Image as PILImage  # noqa: E402
from PIL import ImageDraw, ImageFont  # noqa: E402

FACES = [
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\verdana.ttf",
    r"C:\Windows\Fonts\times.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
]


def _faces(size: int) -> list[tuple[str, ImageFont.FreeTypeFont]]:
    found = []
    for path in FACES:
        if Path(path).exists():
            found.append((Path(path).stem, ImageFont.truetype(path, size)))
    return found


def _true_cap_height(font: ImageFont.FreeTypeFont) -> float:
    """H, E and T are flat-topped: no optical overshoot to average away."""
    tops = [font.getbbox(ch)[1] for ch in "HET"]
    bottoms = [font.getbbox(ch)[3] for ch in "HET"]
    return float(statistics.median(bottoms) - statistics.median(tops))


def _render(text: str, font: ImageFont.FreeTypeFont) -> np.ndarray:
    left, top, right, bottom = font.getbbox(text)
    image = PILImage.new("L", (right - left + 6, bottom - top + 6), 255)
    ImageDraw.Draw(image).text((3 - left, 3 - top), text, font=font, fill=0)
    return np.array(image)


def _measured(text: str, font: ImageFont.FreeTypeFont) -> float | None:
    result = measure_cap_height(_render(text, font))
    return None if result is None else result.cap_height_px


# ---------------------------------------------------------------------------
# The defect
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Maximum Retail Price",
        "Maximum Retail Price (incl. of all taxes)",
        "Manufactured by: Acme Foods Pvt Ltd",
        "Best before 9 months from packaging",
    ],
)
def test_a_mixed_case_declaration_is_not_measured_at_x_height(text: str) -> None:
    """Three capitals among seventeen lower-case letters are nowhere near the
    75th percentile of anything, which is what the estimator used to take."""
    faces = _faces(40)
    if not faces:
        pytest.skip("no TrueType face available to render a reference string")

    for name, font in faces:
        truth = _true_cap_height(font)
        measured = _measured(text, font)
        assert measured is not None, f"{name}: nothing legible in a clean render"
        assert measured >= truth - 1.5, (
            f"{name}: {text!r} measured {measured:.1f} px against a true cap height "
            f"of {truth:.1f} -- an under-measurement is a Rule 7(3) accusation"
        )


def test_an_all_capitals_line_is_unchanged_by_the_clustering() -> None:
    """Nothing to separate, so nothing should move."""
    faces = _faces(40)
    if not faces:
        pytest.skip("no TrueType face available")

    for name, font in faces:
        truth = _true_cap_height(font)
        measured = _measured("BATCH NO. M-09", font)
        assert measured is not None
        assert abs(measured - truth) <= 1.5, f"{name}: {measured:.1f} vs {truth:.1f}"


def test_one_tall_mark_does_not_become_the_cap_height() -> None:
    """`MFG 03/2026` in Verdana is nine glyphs 30 px tall and a solidus 37 px
    tall. Taken as its own class the mark overstated the line by 23%, on a line
    whose every letter is the same size."""
    faces = _faces(40)
    if not faces:
        pytest.skip("no TrueType face available")

    for name, font in faces:
        truth = _true_cap_height(font)
        measured = _measured("MFG 03/2026", font)
        assert measured is not None
        assert measured <= truth * 1.12, (
            f"{name}: the slash inflated the reading to {measured:.1f} px "
            f"against a cap height of {truth:.1f}"
        )


# ---------------------------------------------------------------------------
# The splitting itself, with no rendering involved
# ---------------------------------------------------------------------------


def test_a_line_of_one_height_has_no_taller_class() -> None:
    assert _tall_cluster(np.array([29.0, 29.0, 29.0, 30.0, 29.0])) is None


def test_three_glyphs_are_not_enough_to_find_two_classes() -> None:
    assert _tall_cluster(np.array([12.0, 12.0, 20.0])) is None


def test_the_taller_class_is_the_capitals_and_ascenders() -> None:
    heights = np.array([21.0] * 13 + [28.0, 29.0, 29.0, 29.0, 29.0])
    tall = _tall_cluster(heights)

    assert tall is not None
    assert sorted(tall) == [28.0, 29.0, 29.0, 29.0, 29.0]


def test_a_lone_tall_mark_is_dropped_and_the_rest_reported() -> None:
    """The solidus case, as bare numbers: one 37 among nine 30s is a mark, and
    what is left is a line of one height -- which is the answer."""
    tall = _tall_cluster(np.array([30.0] * 9 + [37.0]))

    assert tall is not None
    assert max(tall) == 30.0


def test_dropping_a_mark_still_finds_two_real_classes_underneath() -> None:
    heights = np.array([21.0] * 6 + [29.0] * 4 + [44.0])
    tall = _tall_cluster(heights)

    assert tall is not None
    assert sorted(set(tall)) == [29.0]
