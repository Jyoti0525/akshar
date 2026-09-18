"""Scale from a dimension the officer measured with a ruler and typed in.

    "see we can make it like this like whenever someone gives something there
     will be a place for entering the height of that product so the user enters
     based on that we can then go for character measurements right ???"

Yes — and it is the strongest scale source in this project, which is worth
saying plainly because it looks like the least sophisticated one.

**Why it beats the marker card.** Tier A measures a printed square lying
*beside* the pack and assumes the card and the label were the same distance
from the lens. They usually are. When they are not — the card flat on a counter
and the packet held up, which is how people actually hold things — that
assumption is a silent scale error with nothing to reveal it. A dimension of
the pack itself has no such assumption: the thing measured and the thing being
measured are the same object. It also needs no prop, no printing, and no
history, which is what every other tier needs.

**Why it is not a guess.** A guessed pack size and a measured one produce the
same arithmetic and are not the same evidence. This number comes off a ruler
and is recorded in the scan, so a manufacturer who disputes a measurement is
disputing a stated premise they can re-check with their own ruler. A stated
premise that turns out wrong is an error somebody can find; an assumed one is
an error nobody can.

**The one way it goes badly wrong, and it is not a small one.** `95` and `9.5`
are one keystroke apart and the second is a factor of ten. Nothing about the
resulting image looks wrong — every letter simply comes out ten times too
small, and every height rule returns FAIL against a compliant pack. So there
are three guards: a plausibility band here, a cross-check against the marker
when both are present (`resolve_scale`), and a cross-check against the stored
dimension for a known SKU. A tier that can be wrong by an order of magnitude
without any visible symptom does not get to be trusted quietly.
"""

from __future__ import annotations

from vision.types import Image, RectifyMethod, ScaleEstimate

PLAUSIBLE_HEIGHT_MM = (5.0, 2000.0)
"""A packaged commodity's photographed face is not 2 mm tall and not three
metres. Wide on purpose: a 6 mm sachet strip and a cement sack are both real,
and this band exists to catch a decimal slip, not to second-guess an officer."""

_RULER_READING_MM = 0.5
"""Assumed error in the typed figure. Half a millimetre is a generous reading
error for a steel rule against a carton edge, and it is the right direction to
be generous in: it widens the REVIEW band, and `min_height_mm` turns a result
within tolerance into REVIEW rather than FAIL."""

_EDGE_LOCALISATION_PX = 4.0
"""How well the rectified panel's own top and bottom edges are known. The
rectification corners come from a quad fit, not from a physical measurement, so
a couple of pixels at each end is honest."""

_METHOD_TOLERANCE_MULTIPLIER: dict[RectifyMethod, float] = {
    # A quad fit IS the panel boundary, so the entered height and the pixel
    # height describe the same rectangle.
    "quad": 1.0,
    # The detector box is padded and axis-aligned, so the crop is larger than
    # the face the officer measured. That is a systematic error and it is the
    # reason this tier is worth far less on this path.
    "detector_box": 4.0,
    # No rectification at all: the "height in pixels" is the whole frame.
    "identity": 12.0,
}


def estimate(
    rectified: Image,
    *,
    height_mm: float | None,
    rectify_method: RectifyMethod = "quad",
    height_px: float | None = None,
) -> ScaleEstimate | None:
    """Millimetres per rectified pixel from the officer's own measurement.

    `height_mm` is the height of **the face in the photograph**, not the tallest
    side of the carton. Those differ on most boxes, and the difference is the
    one mistake a careful person can make in good faith — which is why the
    scanner shows the derived scale back rather than silently using it.
    """
    if height_mm is None:
        return None
    low, high = PLAUSIBLE_HEIGHT_MM
    if not (low <= height_mm <= high):
        return None

    px = height_px if height_px is not None else float(rectified.shape[0])
    if px <= 1.0:  # pragma: no cover - degenerate crop
        return None

    mm_per_px = height_mm / px

    # Two independent errors, added in quadrature because they are unrelated:
    # how well the officer read the ruler, and how well we found the edges the
    # ruler was held against.
    reading = _RULER_READING_MM / height_mm
    edges = _EDGE_LOCALISATION_PX / px
    relative = (reading**2 + edges**2) ** 0.5
    tolerance = mm_per_px * relative * _METHOD_TOLERANCE_MULTIPLIER.get(rectify_method, 12.0)

    return ScaleEstimate(
        tier="A",
        mm_per_px=mm_per_px,
        tolerance=tolerance,
        method="operator_height",
        detail=(
            f"Officer-entered pack height {height_mm:.1f} mm, measured here at "
            f"{px:.0f} px (rectify={rectify_method})"
        ),
    )


__all__ = ["PLAUSIBLE_HEIGHT_MM", "estimate"]
