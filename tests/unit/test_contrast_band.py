"""A legibility verdict must be about the pack, not about the photograph.

---------------------------------------------------------------------------
THE FALSE ACCUSATION
---------------------------------------------------------------------------
A face serum carton, scanned live on 2026-09-19:

    Numeral contrast   FAIL   1.888  +/-0.20   required 3.000
    Rule 9(1)(b) - MRP - medium severity - answerable: manufacturer

Two things were wrong with that line and only one of them was the number.

**The number came from the net quantity, not the MRP.** The rule covers
`[mrp, net_quantity]` and keeps the worst reading, but reported `fields[0]`
whatever produced it. `Net Qty: 30 ml` measured 1.888; the price measured 3.34
and was perfectly legible — and the price is what the exhibit drew a box round.

**And 1.888 was an honest measurement of a blurred photograph.** Cropping that
line out of the frame settles it: the region is out of focus, and the median
ink pixel is a muddy teal-grey rather than the white the printer laid down.
The flat +/-0.20 tolerance asserted a precision the crop did not have.

So this file pins two properties: the verdict names the declaration it was
computed from, and the error bar is measured on the crop rather than assumed.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from rules.checks import REGISTRY
from tests.unit.test_check_sweep import CONTEXT, PACK, declaration, declaration_set, rule
from vision.measure.contrast import _relative_luminance, contrast_band, contrast_ratio

PIL = pytest.importorskip("PIL", reason="Pillow renders the known-contrast pairs")
from PIL import Image as PILImage  # noqa: E402
from PIL import ImageDraw, ImageFont  # noqa: E402

FACES = [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf"]
TEXT = "Net Qty: 30 ml"


def _font(size: int):
    from pathlib import Path

    for path in FACES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    pytest.skip("no TrueType face available to render a known-contrast pair")


def true_ratio(ink: tuple[int, int, int], paper: tuple[int, int, int]) -> float:
    """The WCAG ratio of two RGB colours, computed exactly. The answer key."""

    def lum(rgb):
        return float(_relative_luminance(np.array([[list(reversed(rgb))]], dtype=np.uint8))[0, 0])

    hi, lo = max(lum(ink), lum(paper)), min(lum(ink), lum(paper))
    return (hi + 0.05) / (lo + 0.05)


def render(ink, paper, size: int = 44) -> np.ndarray:
    font = _font(size)
    pad = max(6, size // 2)
    box = font.getbbox(TEXT)
    image = PILImage.new("RGB", (box[2] + 2 * pad, box[3] + 2 * pad), paper)
    ImageDraw.Draw(image).text((pad, pad), TEXT, font=font, fill=ink)
    return np.array(image)[:, :, ::-1].copy()


def photographed(ink, paper, size=44, *, blur=1.6, quality=82, noise=4.0) -> np.ndarray:
    """The same pair, put through something like a phone camera."""
    crop = render(ink, paper, size)
    if blur > 0:
        k = int(blur * 4) | 1
        crop = cv2.GaussianBlur(crop, (k, k), blur)
    if noise > 0:
        rng = np.random.default_rng(7)
        crop = np.clip(
            crop.astype(np.float64) + rng.normal(0, noise, crop.shape), 0, 255
        ).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR) if ok else crop


BLACK_ON_WHITE = ((0, 0, 0), (255, 255, 255))
PILGRIM_TEAL = ((255, 255, 255), (13, 125, 138))
PALE_ON_WHITE = ((205, 205, 205), (255, 255, 255))


# ---------------------------------------------------------------------------
# The estimate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pair",
    [BLACK_ON_WHITE, PILGRIM_TEAL, ((34, 30, 26), (198, 168, 122)), ((119, 119, 119), (255, 255, 255))],
)
@pytest.mark.parametrize("size", [20, 44, 80])
def test_a_sharp_crop_returns_the_exact_wcag_ratio(pair, size) -> None:
    """The answer key is arithmetic, not a previous run of this code. On a
    clean render there is no transition to exclude and no excuse available."""
    ink, paper = pair
    got = contrast_ratio(render(ink, paper, size))
    assert got == pytest.approx(true_ratio(ink, paper), rel=0.02)


def test_a_sharp_crop_reports_almost_no_uncertainty() -> None:
    band = contrast_band(render(*BLACK_ON_WHITE))
    assert band is not None
    assert band[1] < 0.5


def test_a_blurred_crop_reports_a_wide_one() -> None:
    """Same ink, same paper, same type size. Only the camera changed, and the
    error bar is the only thing that may move because of a camera."""
    sharp = contrast_band(render(*PILGRIM_TEAL))
    soft = contrast_band(photographed(*PILGRIM_TEAL, blur=2.6, quality=72, noise=6.0))
    assert sharp is not None and soft is not None
    assert soft[1] > sharp[1] * 3


# ---------------------------------------------------------------------------
# What the check does with it
# ---------------------------------------------------------------------------


def contrast(*declarations, **options):
    options.setdefault("min_ratio", 3.0)
    options.setdefault("fields", ["mrp", "net_quantity"])
    options.setdefault("requires_numerals", True)
    return REGISTRY["min_contrast"](
        rule("min_contrast", **options), declaration_set(*declarations), CONTEXT, PACK
    )


def test_a_legible_pack_photographed_badly_is_referred_not_convicted() -> None:
    """The serum carton's net quantity, to the numbers measured off the real
    photograph. Below the threshold, but by less than the crop can resolve."""
    outcome = contrast(
        declaration(
            field="net_quantity",
            text="Net Qty: 30 ml",
            contrast_ratio=2.59,
            contrast_ratio_tolerance=1.15,
        )
    )
    assert outcome.status == "REVIEW"


def test_an_illegible_pack_photographed_well_still_fails() -> None:
    """The whole point of the band is that it opens for a soft crop and stays
    shut for a sharp one. A sharp crop of genuinely pale print is a finding."""
    outcome = contrast(
        declaration(
            field="mrp",
            text="MRP Rs. 45.00",
            contrast_ratio=1.59,
            contrast_ratio_tolerance=0.2,
        )
    )
    assert outcome.status == "FAIL"


def test_a_declaration_with_no_measured_tolerance_keeps_the_old_band() -> None:
    """`contrast_ratio_tolerance` is additive on the contract, so anything
    stored before this existed reads as `None` — and must behave exactly as it
    did, not become unfalsifiable."""
    outcome = contrast(
        declaration(field="mrp", text="MRP Rs. 45.00", contrast_ratio=1.50),
    )
    assert outcome.status == "FAIL"
    assert outcome.tolerance == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# The verdict names what it measured
# ---------------------------------------------------------------------------


def test_the_verdict_names_the_declaration_the_number_came_from() -> None:
    """`fields[0]` is `mrp`, and reporting that against a net-quantity
    measurement sent the officer to look at a price that was fine."""
    outcome = contrast(
        declaration(field="mrp", text="MRP Rs. 645.00", contrast_ratio=8.20),
        declaration(field="net_quantity", text="Net Qty: 30 ml", contrast_ratio=1.60),
    )
    assert outcome.status == "FAIL"
    assert outcome.field_name == "net_quantity"
    assert outcome.measured == pytest.approx(1.60)


def test_the_error_bar_reported_belongs_to_that_same_declaration() -> None:
    outcome = contrast(
        declaration(
            field="mrp", text="MRP Rs. 645.00", contrast_ratio=8.20, contrast_ratio_tolerance=0.1
        ),
        declaration(
            field="net_quantity",
            text="Net Qty: 30 ml",
            contrast_ratio=2.59,
            contrast_ratio_tolerance=1.15,
        ),
    )
    assert outcome.field_name == "net_quantity"
    assert outcome.tolerance == pytest.approx(1.15)


def test_one_declaration_keeps_naming_its_own_field() -> None:
    outcome = contrast(declaration(field="mrp", text="MRP Rs. 45.00", contrast_ratio=1.0))
    assert outcome.field_name == "mrp"


# ---------------------------------------------------------------------------
# End to end, on rendered pairs whose answer is known
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("size", [30, 44, 80])
@pytest.mark.parametrize("blur", [0.0, 1.6, 2.6])
def test_a_legible_pair_is_never_convicted_however_it_was_photographed(size, blur) -> None:
    ink, paper = PILGRIM_TEAL
    assert true_ratio(ink, paper) >= 3.0, "the pair must be legible for this to mean anything"

    crop = render(ink, paper, size) if blur == 0 else photographed(
        ink, paper, size, blur=blur, quality=72, noise=6.0
    )
    band = contrast_band(crop)
    assert band is not None
    estimate, tolerance = band
    assert estimate + max(tolerance, 0.2) >= 3.0


@pytest.mark.parametrize("size", [30, 44, 80])
@pytest.mark.parametrize("blur", [0.0, 1.6, 2.6])
def test_an_illegible_pair_is_always_convicted(size, blur) -> None:
    ink, paper = PALE_ON_WHITE
    assert true_ratio(ink, paper) < 3.0

    crop = render(ink, paper, size) if blur == 0 else photographed(
        ink, paper, size, blur=blur, quality=72, noise=6.0
    )
    band = contrast_band(crop)
    assert band is not None
    estimate, tolerance = band
    assert estimate + max(tolerance, 0.2) < 3.0


# ---------------------------------------------------------------------------
# Nothing that had no answer before has one now
# ---------------------------------------------------------------------------


def test_a_blank_crop_still_measures_nothing() -> None:
    assert contrast_band(np.full((80, 300, 3), 240, dtype=np.uint8)) is None
    assert contrast_ratio(np.full((80, 300, 3), 240, dtype=np.uint8)) is None


def test_a_crop_too_small_to_hold_a_glyph_measures_nothing() -> None:
    assert contrast_band(np.zeros((2, 2, 3), dtype=np.uint8)) is None


def test_light_on_dark_is_measured_the_same_way_as_dark_on_light() -> None:
    """About a third of Indian packaging prints light on dark, and the serum
    carton is one of them."""
    ink, paper = PILGRIM_TEAL
    assert contrast_ratio(render(ink, paper)) == pytest.approx(true_ratio(ink, paper), rel=0.02)
    assert contrast_ratio(render(paper, ink)) == pytest.approx(true_ratio(ink, paper), rel=0.02)
