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

    min_blur_score: float = 0.55
    """Normalised second-derivative variance, taken **inside the subject**.

    **This moved from 0.18, and the move is a consequence of `_subject_mask`
    rather than a retune.** The statistic used to be computed across the whole
    photograph, where a large featureless backdrop contributes zero variance and
    drags the score down; restricting it to the pack removed that ballast and
    lifted every score. 0.18 against the old statistic and 0.55 against the new
    one are describing the same physical line.

    This is the one threshold in the file that is *not* provisional, because it
    is the one the corpus can answer. Measured over the 38 hand-labelled panels,
    each also smeared with a directional kernel to simulate hand-shake:

        threshold   sharp frames passed   15 px smear rejected
          0.35            38/38                 32/38
          0.50            38/38                 35/38
          0.55            38/38                 36/38
          0.60            38/38                 36/38

    0.55 is the knee — nothing is gained above it and separation is lost below.
    The lowest-scoring real frame (`goodday.jpg`, matte board) sits at 0.6243,
    13% clear of the line."""

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

    severe_factor: float = 1.6
    """How far past its threshold a measurement must go before it *refuses* the
    frame rather than merely flagging it.

    Every number above is provisional — the module docstring says so, and the
    labelled bad-capture subset that would fix them does not exist yet. Treating
    a provisional line as a veto is the mistake: on the 38 hand-labelled panels,
    `usable = not faults` rejected 21 frames the pipeline then read correctly
    with the gate bypassed. Most of those were a few percent over one limit.

    1.6 is chosen from the shape of the measurement rather than fitted: the
    thresholds were each set at the point where the physics starts to bite, and
    half again past that point is where the evidence is actually gone rather
    than merely thinned. It is deliberately a single factor across all five
    checks, because five separately tuned severity lines would be five more
    provisional numbers to defend and no more honest than one."""

    min_subject_ratio: float = 0.04
    """Smallest share of the frame a detected subject may occupy before the
    gate gives up on isolating it and measures the whole photograph.

    Below this the detail mask has almost certainly latched onto noise or a
    price sticker rather than the pack, and measuring inside a 3% island would
    produce a confident number about the wrong pixels. Falling back to the whole
    frame is the conservative answer: it is the behaviour that existed before,
    with its known bias toward rejection."""

    subject_detail: float = 4.0
    """Local contrast, in grey levels, above which a pixel is part of the
    subject rather than the backdrop. A studio sweep, a shop counter or a sheet
    of paper sits near zero; printed packaging does not. Set low on purpose —
    the mask is dilated and hole-filled afterwards, so it has to find *some* of
    the pack, not all of it."""


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

_MASK_SIDE = 128
"""Longest side the subject silhouette is shaped at. See `_subject_mask`."""

_MASK_OCCUPANCY = 0.12
"""Fraction of a coarse cell's fine pixels that must carry detail for the cell
to count as subject. Low, because print is mostly paper: a cell covering a line
of 8-point type is far more background than ink, and requiring half of it to be
ink would erase the text-bearing parts of the pack first."""

_VETO: frozenset[QualityFault] = frozenset({"blur"})
"""Faults that refuse the frame the moment they fail, with no severity grace.

`severe_factor` exists because most of these thresholds are provisional and a
frame a few percent over one of them is usually still readable. Blur is the
exception, and the module docstring already says why: it is the only fault whose
failure mode is a *confident wrong answer*. Glare and clipping destroy contrast
in a way the recogniser sees and reports as low confidence, so the degradation
tiers downstream can act on it. A motion-blurred `8` comes back as a confident
`3`, and nothing after this point can tell.

So the grace that makes the gate kinder on the other four checks is exactly the
grace that would let through the one failure section 8 calls the worst available
to this project. Giving blur the same 1.6x discount passed a 35-pixel directional
smear in the unit tests, which is how this was caught.
"""


def _working_copy(image: Image, longest: int) -> tuple[np.ndarray, np.ndarray]:
    """`(colour, grey)`, downscaled once and shared by every check.

    **Downscaled first, converted after.** The colour copy exists because
    `_glare_ratio` needs saturation, and converting the *original* to HSV was
    measured at 54.8 ms on a 3200x2400 frame — more than three times section 4's
    entire 15 ms budget for B1, spent producing a ratio that is scale-stable.
    Across the 38 hand-labelled panels the glare ratio computed at 512 px
    differs from the full-resolution figure by at most 0.0015 and flips no
    verdict at all, so the full-resolution pass was buying nothing.

    INTER_AREA, not INTER_LINEAR. Area averaging is the correct filter for
    shrinking, and it is also the one that does not itself introduce the
    high-frequency aliasing the blur statistic would then read as sharpness —
    downscaling with a linear filter makes blurry photographs measure sharper,
    in exactly the direction that lets a bad frame through.
    """
    height, width = image.shape[:2]
    scale = longest / float(max(height, width))
    colour = image
    if scale < 1.0:
        colour = cv2.resize(
            image,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    grey = cv2.cvtColor(colour, cv2.COLOR_BGR2GRAY) if colour.ndim == 3 else colour
    return np.ascontiguousarray(colour), np.ascontiguousarray(grey)


def _subject_mask(grey: np.ndarray, thresholds: Thresholds) -> np.ndarray | None:
    """Where the pack is, as a filled mask. `None` when it cannot be isolated.

    **This is the fix for the gate's largest false-reject cause.** Glare, the
    exposure clip fractions and the blur variance were all computed across the
    entire photograph. A pack shot against a white backdrop — which is most of
    the corpus and most of what an officer photographs on a shop counter — is
    mostly backdrop, and a white backdrop is bright, unsaturated and featureless.
    That is, character for character, the definition of specular glare this
    module uses, so the backdrop was being counted as glare *on the label*. One
    agarbati frame measured 81.7% glare frame-wide and 0.8% inside the pack.

    The signal that separates them is local contrast, not brightness. Printed
    packaging has detail everywhere; a sweep, a counter or a sheet of paper has
    none. So:

    1. Local contrast — the mean absolute deviation from a local mean, which is
       a cheap stand-in for a windowed standard deviation and, unlike an edge
       detector, does not fire on the single hard line where pack meets backdrop.
    2. Close and dilate, so the gaps between printed elements join up into one
       region rather than leaving the pack as a constellation of words.
    3. Keep the largest connected component. A price sticker on the counter
       beside the pack is detail too; it is not the subject.
    4. Fill its holes. **This step is what keeps the gate honest**: a specular
       highlight lying across the label is a detail-free island *inside* the
       pack, and filling it puts those pixels back into the denominator and the
       numerator both. Glare on the label still counts as glare. Only glare that
       is actually the room stops counting.
    """
    # Mean absolute deviation from a local mean. Two box filters, both O(n) in
    # pixels regardless of window size, which is what keeps this inside the gate's
    # 15 ms budget.
    local_mean = cv2.blur(grey, (9, 9))
    detail = cv2.blur(cv2.absdiff(grey, local_mean), (15, 15))

    mask = (detail >= thresholds.subject_detail).astype(np.uint8)
    if not mask.any():
        return None

    # **The shape work happens at a coarser scale than the detail work.** The
    # threshold above has to run at full working resolution, because the signal
    # it looks for *is* fine print and area-averaging destroys it. The
    # morphology that follows does not: it is producing a silhouette, and a
    # silhouette does not need 512-pixel precision. Run at 512 with a kernel
    # sized to 6% of the frame it cost 11.4 ms, most of the gate's budget, for a
    # boundary accurate to a pixel that nothing downstream reads to a pixel.
    #
    # Area-averaging the *binary* mask gives, per coarse cell, the fraction of
    # its fine cells that carried detail; `_MASK_OCCUPANCY` is where that
    # fraction counts as occupied.
    full_shape = mask.shape
    scale = _MASK_SIDE / float(max(full_shape))
    if scale < 1.0:
        coarse = cv2.resize(
            mask.astype(np.float32),
            (max(8, int(full_shape[1] * scale)), max(8, int(full_shape[0] * scale))),
            interpolation=cv2.INTER_AREA,
        )
        mask = (coarse >= _MASK_OCCUPANCY).astype(np.uint8)
        if not mask.any():
            return None

    span = max(3, int(min(mask.shape[:2]) * 0.06)) | 1  # odd, ~6% of the short side
    kernel = np.ones((span, span), np.uint8)
    mask = cv2.dilate(cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel), kernel)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if count <= 1:
        return None
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    keep = (labels == largest).astype(np.uint8)

    # Fill holes by flooding the background inward from outside the image. The
    # one-pixel pad guarantees a starting point that is background even when the
    # subject reaches every edge of the frame, which a corner-seeded flood does
    # not and which is exactly the case — a pack filling the viewfinder — where
    # getting it wrong would erase the whole mask.
    height, width = keep.shape
    padded = np.zeros((height + 2, width + 2), np.uint8)
    padded[1:-1, 1:-1] = keep
    cv2.floodFill(padded, np.zeros((height + 4, width + 4), np.uint8), (0, 0), 2)
    keep = (padded[1:-1, 1:-1] != 2).astype(np.uint8)

    # Undo the dilation. It was there to join separate printed elements into one
    # region, not to claim territory: left in, it would hand back a mask with a
    # collar of backdrop around the pack, and that collar is both the brightest
    # thing in the frame and — being a hard pack-against-sweep edge — the
    # sharpest, so it would bias the glare ratio and the blur score in opposite
    # directions at once.
    keep = cv2.erode(keep, kernel)

    if keep.mean() < thresholds.min_subject_ratio:
        return None

    if keep.shape != full_shape:
        # INTER_NEAREST on the way back up. A linear or area interpolation would
        # return fractional values that then need a second threshold, and a
        # second threshold is a second place for the mask's area to drift away
        # from the area `subject_ratio` reports.
        keep = cv2.resize(
            keep, (full_shape[1], full_shape[0]), interpolation=cv2.INTER_NEAREST
        )
    return np.ascontiguousarray(keep)


def _blur_score(grey: np.ndarray, where: np.ndarray | None) -> float:
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

    The statistic is taken over `where` only. Sobel itself still runs on the
    whole plane so that every pixel inside the mask keeps a real neighbourhood;
    it is the *variance* that is restricted. A large featureless backdrop
    otherwise drags the variance down and makes a sharp photograph measure soft.
    """
    dxx = cv2.Sobel(grey, cv2.CV_64F, 2, 0, ksize=3)
    dyy = cv2.Sobel(grey, cv2.CV_64F, 0, 2, ksize=3)
    if where is not None:
        selected = where.astype(bool)
        dxx, dyy = dxx[selected], dyy[selected]
    variance = min(float(dxx.var()), float(dyy.var()))
    return variance / (variance + _BLUR_HALF)


def _glare_ratio(image: Image, grey: np.ndarray, where: np.ndarray | None) -> float:
    if image.ndim != 3:
        # A greyscale source has no saturation to test, so the specular
        # condition collapses to "very bright". That over-counts white
        # packaging, and the honest response is to say so rather than to
        # silently apply a different rule under the same name.
        blown = grey >= _GLARE_VALUE
    else:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        if hsv.shape[:2] != grey.shape[:2]:
            hsv = cv2.resize(hsv, (grey.shape[1], grey.shape[0]), interpolation=cv2.INTER_AREA)
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        blown = (value >= _GLARE_VALUE) & (saturation <= _GLARE_SATURATION)

    if where is None:
        return float(np.count_nonzero(blown)) / blown.size
    # Both halves of the fraction move inside the subject. Counting blown pixels
    # over the subject but dividing by the whole frame would understate glare on
    # a small pack as badly as the old code overstated it on a large backdrop.
    subject = where.astype(bool)
    return float(np.count_nonzero(blown & subject)) / float(max(subject.sum(), 1))


@dataclass(frozen=True, slots=True)
class _Exposure:
    """How the histogram is distributed, in the three numbers that matter."""

    score: float
    """1.0 when nothing is clipped at either end."""
    shadow_clip: float
    highlight_clip: float
    mean: float


def _exposure(grey: np.ndarray, where: np.ndarray | None) -> _Exposure:
    """The histogram of the subject, not of the room it was photographed in.

    `calcHist` takes the mask directly, and the mean is taken over the same
    pixels, so all three numbers describe one region. A white sweep behind a
    dark pack used to pin a third of the histogram against the top end and
    trip `overexposed` on a correctly exposed photograph.
    """
    histogram = cv2.calcHist([grey], [0], where, [256], [0, 256]).ravel()
    total = float(histogram.sum()) or 1.0
    shadow = float(histogram[:_CLIP_BINS].sum()) / total
    highlight = float(histogram[-_CLIP_BINS:].sum()) / total
    mean = float(grey[where.astype(bool)].mean()) if where is not None else float(grey.mean())
    return _Exposure(
        score=1.0 - shadow - highlight,
        shadow_clip=shadow,
        highlight_clip=highlight,
        mean=mean,
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
    colour, grey = _working_copy(image, thresholds.work_side)
    subject = _subject_mask(grey, thresholds)

    blur = _blur_score(grey, subject)
    glare = _glare_ratio(colour, grey, subject)
    exposure = _exposure(grey, subject)

    # Each check reports how far past its line it went, not merely whether it
    # went past. 1.0 is exactly at the threshold. Everything is expressed in the
    # same direction — larger is worse — so the two checks whose thresholds are
    # floors rather than ceilings are inverted here.
    exceedance: list[tuple[QualityFault, float]] = [
        # Resolution first: it is the cheapest to fix and it explains the
        # others. A frame taken from across the aisle is blurry *because* it is
        # small, and "move closer" is better advice than "hold still".
        ("resolution", thresholds.min_side / float(max(min(height, width), 1))),
        ("blur", thresholds.min_blur_score / max(blur, 1e-6)),
        ("glare", glare / max(thresholds.max_glare_ratio, 1e-6)),
        # Under and over are separate tests on opposite ends of the histogram,
        # so both can fire — a photograph taken against a shop window really is
        # both. Under-exposure has two independent causes and takes the worse:
        # an evenly dark frame clips nothing, and a frame with crushed blacks
        # can still have an acceptable mean.
        ("underexposed", max(
            thresholds.dark_mean / max(exposure.mean, 1e-6),
            exposure.shadow_clip / max(thresholds.max_shadow_clip, 1e-6),
        )),
        ("overexposed", exposure.highlight_clip / max(thresholds.max_highlight_clip, 1e-6)),
    ]

    faults = tuple(fault for fault, over in exceedance if over > 1.0)
    blocking = tuple(
        fault
        for fault, over in exceedance
        if over >= (1.0 if fault in _VETO else thresholds.severe_factor)
    )

    # The sentence the officer reads describes the worst *blocking* fault when
    # the frame is refused, and the worst fault otherwise — so "there is glare"
    # is not the headline on a frame that was actually refused for blur.
    speak = blocking[0] if blocking else (faults[0] if faults else None)

    elapsed_ms = (time.perf_counter() - started) * 1000.0

    return CaptureQuality(
        usable=not blocking,
        blur_score=round(min(blur, 1.0), 4),
        glare_ratio=round(min(glare, 1.0), 4),
        exposure_score=round(max(0.0, min(exposure.score, 1.0)), 4),
        width=width,
        height=height,
        faults=faults,
        blocking_faults=blocking,
        subject_ratio=round(float(subject.mean()) if subject is not None else 1.0, 4),
        reason=ADVICE[speak] if speak else None,
        elapsed_ms=round(elapsed_ms, 3),
    )


__all__ = ["THRESHOLDS", "Thresholds", "assess"]
