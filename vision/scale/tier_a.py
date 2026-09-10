"""Scale tier A — a printed marker of known size in the frame.

    "Section 17 previously proposed a Rs 5 coin as the reference object.
     **The marker is better and we are switching.**

     A coin gives one dimension — an apparent diameter that foreshortens into
     an ellipse the moment the camera tilts, which is most of the time in a
     shop. An ArUco or ChArUco marker of known physical size gives **four
     detected corners with sub-pixel accuracy**, which yields the scale *and*
     the homography from the same detection.

     Print the marker on the inspection card an officer already carries. It
     costs a sheet of paper and removes the weakest link in the measurement
     chain."                                              -- section 8b, B3

    "Done when: tier A mean absolute error <= 0.15 mm against ruler ground
     truth, p95 <= 0.25 mm."                     -- section 17 M2, section 18b U1

This is the demo moment and the hardest claim in the project: a millimetre
measurement taken from a shop photograph. Everything about it is arithmetic.

**Why this is a large accuracy win, not a lateral move.** A circle detector
recovers a diameter to roughly two pixels: `HoughCircles` quantises the radius
to whole pixels and a rim is a blurred ramp two or three pixels wide. Marker
corners are refined to sub-pixel precision — conservatively 0.3 px each — and
there are four of them, so averaging the four edges brings the effective error
to about 0.15 px. That is **a factor of thirteen**, and it buys two things at
once: a marker may be far smaller than a coin for the same precision, and at
the same size it measures far better.

**And the marker reports on itself.** A square is square. After rectification
its four edges should be equal, so their disagreement is a direct measurement of
residual perspective — something a coin can never provide, because a foreshortened
circle and a smaller circle are the same picture. `_edge_disagreement` folds that
into the tolerance, which is what keeps the REVIEW band honest.

**The three places this can silently go wrong**, all guarded below:

1.  *Measuring the marker in the wrong coordinate frame.* The marker is found in
    the raw frame, because rectification warps to the label face and may crop
    the card away entirely. Its corners must then be carried through the
    homography into rectified pixels — the pixels the glyphs are measured in.
    Skip that and every measurement is wrong by the warp's scale factor.

2.  *Assuming a size.* Nothing in the image says how large the printed marker
    is. A 20 mm marker read as 25 mm puts a 25% scale error into a legal
    document, so the caller declares the physical size and there is no default
    guessing: `MARKER_EDGE_MM` is the size of *our* printed card, and any other
    card must say so.

3.  *Claiming precision we do not have.* `mm_per_px` is a ratio, so its
    uncertainty is relative. The tolerance returned here is what makes the
    REVIEW band honest, so it is propagated from corner noise, edge
    disagreement and the rectification method rather than assumed.

**ArUco now, ChArUco later, and the primitive is the same.** A single ArUco
marker gives the four corners this module needs and fits in a corner of an
inspection card. A ChArUco board gives more corners and better accuracy for a
larger card, and its detection *begins* with exactly the ArUco pass below.
Nothing here needs rewriting to add it; it is a card-design decision, not a code
one, so it waits until the card is printed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from vision.rectify.rectify import map_point
from vision.types import XYWH, Image, Point, RectifyMethod, ScaleEstimate

DEFAULT_DICTIONARY = "DICT_4X4_50"
"""4x4 is the smallest grid OpenCV ships, which makes each printed cell as large
as possible for a given card area — and cell size is what survives a low
resolution photograph, motion blur and a cheap office printer. Fifty distinct
ids is far more than an inspection card needs.

Larger dictionaries (6x6, 7x7) exist to keep thousands of ids apart. We have one
card design, so their only effect here would be to make every cell smaller."""

MARKER_EDGE_MM = 25.0
"""Edge length of the marker printed on the AKSHAR inspection card, in
millimetres, **black border included** — that square is what `detectMarkers`
returns corners for.

25 mm is a choice, not a gazette value: large enough to clear `_MIN_EDGE_PX` at
arm's length on a 1080p frame, small enough to sit beside a packet without
covering the declarations we came to read. It is recorded here rather than in a
caller so that changing the card is a one-line, reviewable edit.

**Any other card must pass its own size.** There is deliberately no attempt to
infer the size from the image."""

_MIN_EDGE_PX = 24.0
"""Shortest acceptable mean edge, in raw pixels, set by our own accuracy target
rather than by taste.

At `_CORNER_SIGMA_PX` = 0.3 px per corner, averaging four edges gives an
effective error near 0.15 px. Requiring the scale to contribute under about 1%
of a measurement — roughly 0.02 mm on a 2 mm threshold, comfortably inside M2's
0.15 mm budget — needs `0.15 / edge <= 0.01`, so an edge of about 15 px. 24 px
carries a margin for a marker photographed at an angle, where the shortest edge
is the foreshortened one.

A marker smaller than this is not rejected because detection failed — it will
often decode perfectly. It is rejected because **it cannot support the claim we
make about it.**"""

_MAX_EDGE_FRAC = 0.45
"""And a marker filling half the frame means the card is being photographed, not
the packet. Almost certainly a calibration shot that wandered into the pipeline."""

_MAX_EDGE_DISAGREEMENT = 0.25
"""Maximum spread across the four rectified edges, relative to their mean,
before the marker is refused outright.

A square that still measures 25% out of square after rectification is not a
square seen at an angle — it is a marker on a *different plane* from the label
(lying on the shelf while the pack faces the camera, say), or a rectification
that has gone wrong. Either way the millimetre figure it implies would not apply
to the glyphs, so it is refused rather than widened. Below this bound the
disagreement is folded into the tolerance instead."""

_CORNER_SIGMA_PX = 0.3
"""Per-corner uncertainty after sub-pixel refinement. Deliberately pessimistic:
OpenCV's corner refinement typically does better, and a tolerance that is too
wide costs us a REVIEW where a tolerance that is too narrow costs us a wrong
conviction."""

# Perspective is only fully removed on the `quad` path. On the other two the
# marker and the glyphs may sit at different effective scales, so the estimate
# stays usable but stops pretending to be precise.
_METHOD_TOLERANCE_MULTIPLIER: dict[RectifyMethod, float] = {
    # The plane was rectified against this very marker, so the square it maps
    # to is square by construction and the residual is already measured by
    # `_edge_disagreement`. Nothing further to widen for.
    "marker": 1.0,
    "quad": 1.0,
    "detector_box": 3.0,
    "identity": 5.0,
}


@dataclass(frozen=True, slots=True)
class MarkerFit:
    """One detected marker, with its corners in RAW camera space."""

    marker_id: int
    corners: tuple[Point, Point, Point, Point]
    """Clockwise from the marker's own top-left, as OpenCV returns them."""

    @property
    def centre(self) -> Point:
        xs = [c[0] for c in self.corners]
        ys = [c[1] for c in self.corners]
        return (sum(xs) / 4.0, sum(ys) / 4.0)

    @property
    def box(self) -> XYWH:
        xs = [c[0] for c in self.corners]
        ys = [c[1] for c in self.corners]
        return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _edge_lengths(corners: tuple[Point, Point, Point, Point]) -> list[float]:
    """The four side lengths, in the order the corners are given."""
    return [
        math.dist(corners[i], corners[(i + 1) % 4])
        for i in range(4)
    ]


def _edge_disagreement(lengths: list[float]) -> float:
    """Spread across the four edges relative to their mean.

    Zero for a perfect square. Grows with residual perspective, with the marker
    sitting on a plane other than the label's, and with a bad homography. This
    is the self-check a coin cannot offer.
    """
    mean = sum(lengths) / len(lengths)
    if mean <= 0.0:  # pragma: no cover - degenerate quad
        return 1.0
    return (max(lengths) - min(lengths)) / mean


def _dictionary(name: str) -> cv2.aruco.Dictionary:
    attr = getattr(cv2.aruco, name, None)
    if attr is None:
        raise ValueError(
            f"unknown ArUco dictionary {name!r}; expected one of OpenCV's "
            f"DICT_* constants, for example {DEFAULT_DICTIONARY!r}"
        )
    return cv2.aruco.getPredefinedDictionary(attr)


def detect_markers(
    image: Image,
    *,
    dictionary: str = DEFAULT_DICTIONARY,
    marker_ids: frozenset[int] | None = None,
) -> list[MarkerFit]:
    """Every acceptable marker in the raw frame, largest first.

    `marker_ids` restricts detection to the ids printed on our own card. It is
    `None` by default because an officer may be issued a card from any batch,
    but a deployment that fixes its ids should pass them: a stray marker in the
    frame — on another product's packaging, on a shelf tag — would otherwise be
    measured as if it were the reference.

    Never raises on a frame with no marker; returns an empty list.
    """
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    longer = float(max(h, w))

    parameters = cv2.aruco.DetectorParameters()
    # Sub-pixel refinement is the entire reason this beats a coin. Without it
    # corners land on whole pixels and the accuracy advantage disappears.
    parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    detector = cv2.aruco.ArucoDetector(_dictionary(dictionary), parameters)

    corner_sets, ids, _rejected = detector.detectMarkers(gray)
    if ids is None or len(corner_sets) == 0:
        return []

    fits: list[MarkerFit] = []
    for quad, marker_id in zip(corner_sets, ids.ravel().tolist(), strict=True):
        if marker_ids is not None and marker_id not in marker_ids:
            continue
        points = tuple((float(x), float(y)) for x, y in quad.reshape(4, 2))
        lengths = _edge_lengths(points)  # type: ignore[arg-type]
        mean_edge = sum(lengths) / 4.0
        if mean_edge < _MIN_EDGE_PX:
            continue  # decodable, but too small to support our accuracy claim
        if mean_edge > longer * _MAX_EDGE_FRAC:
            continue  # the card is the subject, not the packet
        fits.append(MarkerFit(int(marker_id), points))  # type: ignore[arg-type]

    # Largest first: a bigger marker is the more precisely measurable one.
    fits.sort(key=lambda fit: sum(_edge_lengths(fit.corners)), reverse=True)
    return fits


def estimate(
    image: Image,
    *,
    homography: Image | None = None,
    rectify_method: RectifyMethod = "quad",
    edge_mm: float = MARKER_EDGE_MM,
    dictionary: str = DEFAULT_DICTIONARY,
    marker_ids: frozenset[int] | None = None,
) -> ScaleEstimate | None:
    """Recover `mm_per_px` in RECTIFIED pixels from a printed marker.

    Returns None when no acceptable marker was found, so the caller falls
    through to tier B and then to tier C. Never returns a guess.

    **Every marker found contributes.** A card carrying two or three markers is
    cheap to print and gives independent estimates of the same quantity; their
    median is used, and their disagreement widens the tolerance. With one marker
    this reduces to the single-marker case exactly.
    """
    if edge_mm <= 0.0:
        raise ValueError(f"marker edge must be positive, got {edge_mm!r}")

    markers = detect_markers(image, dictionary=dictionary, marker_ids=marker_ids)
    if not markers:
        return None

    per_marker: list[float] = []
    disagreements: list[float] = []
    rectified_edges: list[float] = []
    accepted: list[MarkerFit] = []

    for fit in markers:
        # Map the corners into rectified space FIRST, then measure there. The
        # glyphs are measured in rectified pixels, so the reference must be too;
        # mapping a scalar length instead would ignore that the warp's scale
        # varies across the frame.
        mapped = tuple(map_point(homography, corner) for corner in fit.corners)
        lengths = _edge_lengths(mapped)  # type: ignore[arg-type]
        mean_edge = sum(lengths) / 4.0
        if mean_edge <= 1.0:  # pragma: no cover - degenerate mapping
            continue

        disagreement = _edge_disagreement(lengths)
        if disagreement > _MAX_EDGE_DISAGREEMENT:
            # Not on the label's plane, or the rectification is wrong. A scale
            # from here would not apply to the glyphs.
            continue

        per_marker.append(edge_mm / mean_edge)
        disagreements.append(disagreement)
        rectified_edges.append(mean_edge)
        accepted.append(fit)

    if not per_marker:
        return None

    mm_per_px = float(np.median(per_marker))
    worst_disagreement = max(disagreements)
    mean_edge_px = float(np.median(rectified_edges))

    # Uncertainty, combined in quadrature from three independent sources.
    #
    #   corner  — sub-pixel refinement error, averaged over four edges
    #   square  — how far from square the marker still measures, which is
    #             residual perspective expressed as a length error
    #   spread  — disagreement between markers, when there is more than one
    corner_rel = (_CORNER_SIGMA_PX / 2.0) / mean_edge_px
    square_rel = worst_disagreement / 2.0
    spread_rel = (
        float(np.std(per_marker)) / mm_per_px if len(per_marker) > 1 and mm_per_px > 0 else 0.0
    )
    relative = math.sqrt(corner_rel**2 + square_rel**2 + spread_rel**2)
    tolerance = mm_per_px * relative * _METHOD_TOLERANCE_MULTIPLIER.get(rectify_method, 5.0)

    primary = accepted[0]
    centre = map_point(homography, primary.centre)
    half = mean_edge_px / 2.0
    ids = ", ".join(str(fit.marker_id) for fit in accepted)
    detail = (
        f"ArUco {dictionary} id {ids}, {edge_mm:g} mm edge, "
        f"{mean_edge_px:.1f} px rectified "
        f"({len(accepted)} marker{'s' if len(accepted) != 1 else ''}, "
        f"squareness {worst_disagreement:.3f}, rectify={rectify_method})"
    )

    return ScaleEstimate(
        tier="A",
        mm_per_px=mm_per_px,
        tolerance=tolerance,
        method="aruco",
        detail=detail,
        reference_box=(centre[0] - half, centre[1] - half, mean_edge_px, mean_edge_px),
    )


def marker_quad(
    image: Image,
    *,
    dictionary: str = DEFAULT_DICTIONARY,
    marker_ids: frozenset[int] | None = None,
) -> tuple[Point, Point, Point, Point] | None:
    """The largest marker's corners in raw space, for rectification.

    This is the half of section 8b's claim that the coin could never deliver:
    *"four detected corners ... yields the scale **and the homography** from the
    same detection."* `vision.rectify` uses it to fit a warp against four points
    of known relative geometry, rather than against a label outline recovered by
    contour search that may or may not be rectangular in the first place.
    """
    markers = detect_markers(image, dictionary=dictionary, marker_ids=marker_ids)
    return markers[0].corners if markers else None


__all__ = [
    "DEFAULT_DICTIONARY",
    "MARKER_EDGE_MM",
    "MarkerFit",
    "detect_markers",
    "estimate",
    "marker_quad",
]
