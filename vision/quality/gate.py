"""Is this image usable at all? AKSHAR.md section 8 (B1), section 17 (M0).

Four measurements, no model, and the whole thing runs on a downscaled copy so
the cost does not grow with the camera.

**Every threshold in here is provisional and the module says so out loud.**
Section 17's done-criterion for M0 is *"rejects the deliberately-bad subset of
the corpus (motion blur, foil glare, underexposed) at >=90% recall while passing
>=98% of usable photos"*, and that subset does not exist yet — it is part of the
400-photograph corpus that has to come from the field. The numbers below are
derived from the physics of each measurement and from the frames we do have; they
are not fitted to a labelled set, and `RESULTS.md` does not report a recall
figure for B1 because there is nothing honest to report one against.

That is why the gate is **deliberately permissive**. A false reject costs an
officer one retake. A false accept costs a wrong millimetre measurement on an
enforcement record, and section 8 names that as the worst failure available to
this project — but a gate tuned tight on guessed thresholds converts *every*
difficult-but-readable frame into a retake, and an officer who is sent back four
times stops using the tool. Until the bad subset arrives, the gate catches the
frames that are unarguably unusable and lets the pipeline's own degradation
tiers handle the rest, which is what they are for.

**Why not run the pipeline and check the confidence afterwards.** Because the
failure this gate exists to prevent is a *confident* wrong answer. A motion-blurred
`8` read as a `3` comes back with a high recogniser score; blur destroys the
evidence before the confidence is computed, so the confidence cannot see it.
The only place to catch it is in the pixels, before anything reads them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import cv2
import numpy as np

from contracts import ADVICE, CaptureQuality, QualityFault

if TYPE_CHECKING:  # pragma: no cover - typing only
    from vision.types import Image


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Where each check draws its line. Provisional — see the module docstring."""

    min_side: int = 640
    """Shortest side, in pixels. Below this a 1 mm letter on a 100 mm pack is
    about six pixels tall, and section 18b's own capture note puts the working
    range at 5-12 px/mm. Six pixels is not a measurement, it is a guess with an
    error bar wide enough to cover both verdicts."""

    min_blur_score: float = 0.18
    """Normalised variance-of-Laplacian. Set low on purpose: the raw statistic
    scales with local contrast, so matte kraft paper photographed perfectly
    sharp scores several times lower than glossy print photographed the same
    way. A threshold tight enough to catch every soft frame on glossy stock
    rejects most cement bags."""

    max_glare_ratio: float = 0.12
    """Fraction of the frame that is blown specular highlight. Foil and shrink
    wrap routinely show a few percent and stay readable; above roughly an eighth
    of the frame the highlight is across the label rather than beside it."""

    max_highlight_clip: float = 0.30
    """Fraction of the frame pinned at the top of the range.

    **Not the mean.** A white packet filling the frame is legitimately bright —
    a well-exposed photograph of a salt packet has a mean luminance around 235
    — so a mean-based test rejects exactly the packaging that is easiest to
    read. What actually destroys a declaration is *clipping*: pixels at 255
    carry no detail, and once a third of the frame is pinned there the label is
    gone whatever the mean says."""

    max_shadow_clip: float = 0.45
    """The same test at the bottom of the range. Set looser than the highlight
    limit because a dark background behind a well-lit pack is common and
    harmless, while a blown highlight is almost always *on* the label."""

    dark_mean: float = 38.0
    """Mean luminance below which there is not enough signal anywhere in the
    frame. A separate test from shadow clipping: an evenly under-exposed
    photograph clips nothing and is still unreadable."""

    work_side: int = 512
    """Longest side of the working copy. Every statistic here is a ratio or a
    normalised variance, so it is scale-stable — and a fixed working size is
    what keeps the gate under section 4's 15 ms budget on a 48-megapixel phone
    photograph as well as on a 2-megapixel one."""


THRESHOLDS = Thresholds()

# Second-derivative variance at which an image is considered half sharp. The
# statistic is unbounded, so it is squashed rather than clipped: `v / (v + K)`
# maps [0, inf) onto [0, 1) smoothly and has no cliff for a frame that lands
# near the threshold. K is the half-way point.
#
# Higher than a Laplacian's would be, because a single-axis Sobel of order 2
# carries roughly four times the magnitude of the corresponding Laplacian term.
_BLUR_HALF = 1100.0

# A pixel counts as specular glare when it is at the very top of the value range
# AND almost colourless. Both conditions are needed: white packaging is bright
# and colourless too, so brightness alone flags every packet of salt, and high
# saturation alone flags every red wrapper.
# Tightened deliberately. The load-bearing test for "is this label destroyed by
# light" is the blur score, not this one: a blown region has no local contrast,
# so the second-derivative variance collapses there too. This check exists to
# catch the case blur cannot — a specular highlight lying across part of the
# label while the rest stays sharp — so it counts only pixels that are actually
# pinned. At 245 it flagged a well-exposed photograph of a white salt packet.
_GLARE_VALUE = 251
_GLARE_SATURATION = 24

# Histogram bins at each end treated as clipped, out of 256. Three bins is
# values 0-2 and 253-255: detail that is gone, rather than merely dark or
# bright. Six was too generous — it counted 250 as clipped, and a white packet
# photographed well sits right there.
_CLIP_BINS = 3


def _working_copy(image: Image, longest: int) -> np.ndarray:
    """Greyscale, downscaled, contiguous — computed once and shared."""
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image

    height, width = grey.shape[:2]
    scale = longest / float(max(height, width))
    if scale < 1.0:
        # INTER_AREA, not INTER_LINEAR. Area averaging is the correct filter for
        # shrinking, and it is also the one that does not itself introduce the
        # high-frequency aliasing the blur statistic would then read as sharpness
        # — downscaling with a linear filter makes blurry photographs measure
        # sharper, in exactly the direction that lets a bad frame through.
        grey = cv2.resize(
            grey,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    return np.ascontiguousarray(grey)


def _blur_score(grey: np.ndarray) -> float:
    """Sharpness along the *worse* of the two axes, normalised to 0..1.

    Not the variance of the Laplacian, which is what everyone reaches for and
    which is isotropic. Camera shake in a shop is directional: a hand moving
    sideways smears the vertical strokes of the digits and leaves the horizontal
    ones intact, so a Laplacian — the sum of both second derivatives — still
    sees plenty of edge energy and scores the frame sharp. On a synthetic
    35-pixel horizontal smear it scored 0.32 against a 0.18 threshold and passed.

    Taking the second derivative along each axis separately and keeping the
    smaller collapses on exactly that case, and is unchanged on an evenly soft
    frame, where both axes are equally bad.
    """
    dxx = float(cv2.Sobel(grey, cv2.CV_64F, 2, 0, ksize=3).var())
    dyy = float(cv2.Sobel(grey, cv2.CV_64F, 0, 2, ksize=3).var())
    variance = min(dxx, dyy)
    return variance / (variance + _BLUR_HALF)


def _glare_ratio(image: Image, grey: np.ndarray) -> float:
    if image.ndim != 3:
        # A greyscale source has no saturation to test, so the specular
        # condition collapses to "very bright". That over-counts white
        # packaging, and the honest response is to say so rather than to
        # silently apply a different rule under the same name.
        return float(np.count_nonzero(grey >= _GLARE_VALUE)) / grey.size

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    if hsv.shape[:2] != grey.shape[:2]:
        hsv = cv2.resize(hsv, (grey.shape[1], grey.shape[0]), interpolation=cv2.INTER_AREA)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    blown = (value >= _GLARE_VALUE) & (saturation <= _GLARE_SATURATION)
    return float(np.count_nonzero(blown)) / blown.size


@dataclass(frozen=True, slots=True)
class _Exposure:
    """How the histogram is distributed, in the three numbers that matter."""

    score: float
    """1.0 when nothing is clipped at either end."""
    shadow_clip: float
    highlight_clip: float
    mean: float


def _exposure(grey: np.ndarray) -> _Exposure:
    histogram = cv2.calcHist([grey], [0], None, [256], [0, 256]).ravel()
    total = float(histogram.sum()) or 1.0
    shadow = float(histogram[:_CLIP_BINS].sum()) / total
    highlight = float(histogram[-_CLIP_BINS:].sum()) / total
    return _Exposure(
        score=1.0 - shadow - highlight,
        shadow_clip=shadow,
        highlight_clip=highlight,
        mean=float(grey.mean()),
    )


def assess(image: Image, thresholds: Thresholds = THRESHOLDS) -> CaptureQuality:
    """Measure the frame. Never decides compliance — see `contracts/quality.py`.

    Returns every fault it finds rather than the first, because a photograph
    taken into the sun is usually both over-exposed and glare-blown and telling
    the officer one of the two sends them back for a second attempt that fails
    the same way.
    """
    started = time.perf_counter()

    height, width = int(image.shape[0]), int(image.shape[1])
    grey = _working_copy(image, thresholds.work_side)

    blur = _blur_score(grey)
    glare = _glare_ratio(image, grey)
    exposure = _exposure(grey)

    faults: list[QualityFault] = []
    # Resolution first: it is the cheapest to fix and it explains the others. A
    # frame taken from across the aisle is blurry *because* it is small, and
    # "move closer" is better advice than "hold still".
    if min(height, width) < thresholds.min_side:
        faults.append("resolution")
    if blur < thresholds.min_blur_score:
        faults.append("blur")
    if glare > thresholds.max_glare_ratio:
        faults.append("glare")
    # Under and over are separate tests on opposite ends of the histogram, so
    # both can fire — a photograph taken against a shop window really is both.
    if exposure.mean < thresholds.dark_mean or exposure.shadow_clip > thresholds.max_shadow_clip:
        faults.append("underexposed")
    if exposure.highlight_clip > thresholds.max_highlight_clip:
        faults.append("overexposed")

    elapsed_ms = (time.perf_counter() - started) * 1000.0

    return CaptureQuality(
        usable=not faults,
        blur_score=round(min(blur, 1.0), 4),
        glare_ratio=round(min(glare, 1.0), 4),
        exposure_score=round(max(0.0, min(exposure.score, 1.0)), 4),
        width=width,
        height=height,
        faults=tuple(faults),
        reason=ADVICE[faults[0]] if faults else None,
        elapsed_ms=round(elapsed_ms, 3),
    )


__all__ = ["THRESHOLDS", "Thresholds", "assess"]
