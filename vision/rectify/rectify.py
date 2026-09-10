"""M1 Rectify — AKSHAR.md section 17.

    "Edge detection, largest quadrilateral, perspective transform, warp;
     falls back to the detector box when no clean quad is found.
     Done when: printed lines deviate under 2 degrees from horizontal after
     warping, across the 40 test photos."

**Why this exists at all.** Every millimetre measurement in the system assumes
that `Box.h` is proportional to true printed height. In a raw photograph it is
not: a packet photographed at an angle has its far edge foreshortened, so the
same 2 mm glyph measures 14 px at the near edge and 9 px at the far one. Apply
one `mm_per_px` scalar to that and you get a confident violation notice for a
compliant pack. Rectification is what makes a single scalar legitimate.

**No model is involved.** Section 14's table lists rectification, scale and
measurement under *Trained? No — deterministic geometry*. That is a deliberate
answer to "where is the AI": the AI finds things, arithmetic measures them, and
arithmetic is what we are willing to defend in court.

**The marker path, added with section 8b.** *"Four detected corners with
sub-pixel accuracy ... yields the scale **and the homography** from the same
detection."* That is a better starting point than a contour search, because the
marker's true geometry is *known* — it is a square — whereas a label outline is
only assumed to be a rectangle, and on a pouch or a shaped carton it is not one.
So when a marker is present we fit the warp to it and rectify the whole plane;
`find_label_quad` stays as the fallback for a frame with no card in it.

**Field procedure note, which belongs here rather than in a manual.** The
homography is only valid on the plane it was fitted to — the label face. A card
lying on the counter *beside* the packet is on a different plane, so mapping it
through this homography is an approximation that degrades as the pack gets
taller. Laying the card flat against the label face makes the mapping exact.
This is why the ruler ground-truth session must photograph the marker on the
pack, not next to it. Tier A measures how far from square the marker still
comes out and widens its tolerance accordingly, so a card on the wrong plane
degrades the confidence rather than corrupting the number silently.
"""

from __future__ import annotations

import cv2
import numpy as np

from vision.rectify.skew import deskew, estimate_skew
from vision.types import XYWH, Image, Point, Quad, RectifyResult

# Working resolution for contour finding. Edges do not get better above this
# and the search is O(pixels); the quad found here is scaled back up before
# the warp, so the output keeps full resolution.
_WORK_MAX_SIDE = 1000

_MIN_QUAD_AREA_FRAC = 0.20
"""Below this fraction of the frame, a quad is something printed on the label
rather than the label, and warping to it throws the declaration away.

Was 0.12, on the reasoning that a quad under 12% is almost certainly a shelf
rectangle, a tile or a price rail, and that accepting one produces a beautifully
warped photograph of a floor. The reasoning is right; the number left no margin.
What makes the margin matter is what happens when a quad IS accepted: `rectify`
prefers a quad over every other method except a marker, so whatever this returns
becomes the whole scan, and everything outside it is discarded before a single
region is proposed.

The declaration-block set measured the cost. The search returns a quad on four
of its 38 photographs. Three of the four cover 13%, 13% and 35% of the frame —
a barcode block, a coded sticker and a nutrition table, each a real printed
rectangle *inside* the panel — and the panel around them was thrown away. On
`papad.jpg`, whose label is an octagon and so never matches as a quad in its own
right, the interior box left one legible line out of a full panel and took the
scan to L4, "nothing legible recovered". The fourth quad covered 86%: that one
was the label, and it read 63 lines.

**Twenty per cent is a floor with margin on both sides, not a fitted value.**
The two junk quads sit at 0.13. The smallest quad known to be a real label is
the synthetic golden scene at 0.366 — a 760x520 label on a 1200x900 canvas,
which is an ordinary pack-on-a-counter framing and must keep its rectification.
0.50 was tried first and `tests/golden` rejected it by failing on exactly that
scene, which is what that suite is for."""

_MAX_QUAD_AREA_FRAC = 0.995
"""At the other end, a quad that is the whole frame is the frame border."""

_APPROX_EPS_FRAC = 0.02
"""`approxPolyDP` tolerance as a fraction of perimeter. Below ~0.01 a slightly
bowed packet never reduces to four points; above ~0.04 a hexagonal blister
pack flattens into a quad that is not its outline."""


def order_corners(points: np.ndarray) -> Quad:
    """Order four points top-left, top-right, bottom-right, bottom-left.

    The sum/difference trick: TL has the smallest x+y and BR the largest; TR
    has the smallest y-x and BL the largest. It is orientation-stable for any
    convex quad that is not rotated past 45 degrees, which a hand-held photo of
    a packet never is.
    """
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    total = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).ravel()
    tl = pts[int(np.argmin(total))]
    br = pts[int(np.argmax(total))]
    tr = pts[int(np.argmin(diff))]
    bl = pts[int(np.argmax(diff))]
    return (
        (float(tl[0]), float(tl[1])),
        (float(tr[0]), float(tr[1])),
        (float(br[0]), float(br[1])),
        (float(bl[0]), float(bl[1])),
    )


def _edges(gray: Image) -> Image:
    """Canny with thresholds derived from the image, not hardcoded.

    A fixed (50, 150) works on a lit studio shot and finds nothing on a photo
    taken in the back of a kirana shop. Median-based thresholds adapt.
    """
    blurred = cv2.bilateralFilter(gray, 9, 75, 75)
    median = float(np.median(blurred))
    lower = int(max(0, 0.66 * median))
    upper = int(min(255, 1.33 * median))
    edged = cv2.Canny(blurred, lower, max(upper, lower + 1))
    # Close 1-2 px gaps so a label edge broken by a glare spot still forms a
    # closed contour. Without this, high-gloss foil packets never yield a quad.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    return cv2.morphologyEx(edged, cv2.MORPH_CLOSE, kernel, iterations=2)


def find_label_quad(image: Image, *, min_area_frac: float = _MIN_QUAD_AREA_FRAC) -> Quad | None:
    """Largest convex four-sided contour that plausibly is the label face."""
    h, w = image.shape[:2]
    if h < 32 or w < 32:
        return None

    scale = min(1.0, _WORK_MAX_SIDE / float(max(h, w)))
    work = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = work if work.ndim == 2 else cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)

    contours, _ = cv2.findContours(_edges(gray), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    frame_area = float(gray.shape[0] * gray.shape[1])
    best: np.ndarray | None = None
    best_area = 0.0

    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:24]:
        area = cv2.contourArea(contour)
        if area < frame_area * min_area_frac or area > frame_area * _MAX_QUAD_AREA_FRAC:
            continue
        peri = cv2.arcLength(contour, closed=True)
        approx = cv2.approxPolyDP(contour, _APPROX_EPS_FRAC * peri, closed=True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        if area > best_area:
            best, best_area = approx, area

    if best is None:
        return None

    corners = order_corners(best.reshape(4, 2).astype(np.float32) / scale)
    return corners


def _target_size(quad: Quad) -> tuple[int, int]:
    """Output size from the quad's own edge lengths.

    Using the longer of each opposing pair keeps the nearer, less foreshortened
    edge as the reference, so rectification upsamples the far end rather than
    throwing away resolution at the near one. Glyph height is measured in these
    pixels, so discarding resolution here directly costs measurement accuracy.
    """
    tl, tr, br, bl = (np.asarray(p, dtype=np.float64) for p in quad)
    width = max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl))
    height = max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl))
    return max(round(width), 1), max(round(height), 1)


def warp_to_quad(image: Image, quad: Quad) -> tuple[Image, Image, float]:
    """Warp `quad` to a front-facing rectangle. Returns (image, H, scale_factor)."""
    width, height = _target_size(quad)
    src = np.asarray(quad, dtype=np.float32)
    dst = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(image, matrix, (width, height), flags=cv2.INTER_CUBIC)

    tl, tr, br, bl = (np.asarray(p, dtype=np.float64) for p in quad)
    mean_raw_width = (np.linalg.norm(br - bl) + np.linalg.norm(tr - tl)) / 2.0
    scale_factor = float(width / mean_raw_width) if mean_raw_width > 0 else 1.0
    return warped, matrix, scale_factor


def map_point(homography: Image | None, point: Point) -> Point:
    """Carry a raw-space point into rectified space.

    Used by scale tier A: the marker is found in the raw frame (rectification
    may crop it out), and its corners must be expressed in the same pixels the
    glyphs are measured in.
    """
    if homography is None:
        return point
    vec = np.array([point[0], point[1], 1.0], dtype=np.float64)
    out = np.asarray(homography, dtype=np.float64) @ vec
    if abs(out[2]) < 1e-12:  # pragma: no cover - degenerate homography
        return point
    return float(out[0] / out[2]), float(out[1] / out[2])


_MAX_WARP_SIDE = 3000
"""Cap on the rectified output. A homography fitted to a small marker can send
the frame's far corners a very long way — in the limit, past the horizon line,
where the warped bounding box is unbounded. Capping keeps a pathological
geometry from allocating gigabytes, and the scale reduction is folded into the
returned matrix so mapped points stay correct."""

_MAX_WARP_GROWTH = 12.0
"""If rectifying would grow the frame more than this, the marker is being read
at a grazing angle and the plane's far end is effectively at infinity. Refuse
and fall back rather than warp a photograph into a smear."""


def warp_to_marker(
    image: Image, corners: Quad, *, target_edge_px: float | None = None
) -> tuple[Image, Image, float] | None:
    """Rectify the whole plane using a marker known to be square.

    Returns (image, H, scale_factor), or None when the geometry is degenerate.

    The marker's four corners are mapped to an axis-aligned square, and **the
    same homography is then applied to the entire frame** — the point is not to
    extract the marker but to remove perspective from the plane it lies on,
    which is the label face. That is why this is stronger than `warp_to_quad`:
    a square is square by construction, whereas a label outline is only assumed
    to be a rectangle.
    """
    src = np.asarray(corners, dtype=np.float32)
    edges = [
        float(np.linalg.norm(np.asarray(corners[i]) - np.asarray(corners[(i + 1) % 4])))
        for i in range(4)
    ]
    edge = float(target_edge_px) if target_edge_px else sum(edges) / 4.0
    if edge < 1.0:  # pragma: no cover - guarded by tier A's _MIN_EDGE_PX
        return None

    dst = np.array([[0, 0], [edge, 0], [edge, edge], [0, edge]], dtype=np.float32)
    base = cv2.getPerspectiveTransform(src, dst)

    h, w = image.shape[:2]
    frame = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32).reshape(-1, 1, 2)
    mapped = cv2.perspectiveTransform(frame, base).reshape(-1, 2)
    if not np.all(np.isfinite(mapped)):
        return None

    x0, y0 = mapped.min(axis=0)
    x1, y1 = mapped.max(axis=0)
    out_w, out_h = float(x1 - x0), float(y1 - y0)
    if out_w < 8.0 or out_h < 8.0:
        return None
    if out_w > w * _MAX_WARP_GROWTH or out_h > h * _MAX_WARP_GROWTH:
        return None  # grazing angle: the plane runs to the horizon

    shrink = min(1.0, _MAX_WARP_SIDE / max(out_w, out_h))
    translation = np.array(
        [[shrink, 0.0, -x0 * shrink], [0.0, shrink, -y0 * shrink], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    matrix = translation @ np.asarray(base, dtype=np.float64)
    size = (max(round(out_w * shrink), 1), max(round(out_h * shrink), 1))
    warped = cv2.warpPerspective(image, matrix, size, flags=cv2.INTER_CUBIC)

    mean_raw_edge = sum(edges) / 4.0
    scale_factor = float(edge * shrink / mean_raw_edge) if mean_raw_edge > 0 else 1.0
    return warped, matrix, scale_factor


def _crop_to_box(image: Image, box: XYWH, pad_frac: float = 0.02) -> tuple[Image, Image]:
    """Axis-aligned crop plus the translation that describes it as a homography."""
    h, w = image.shape[:2]
    bx, by, bw, bh = box
    pad_x, pad_y = bw * pad_frac, bh * pad_frac
    x0 = int(max(0, round(bx - pad_x)))
    y0 = int(max(0, round(by - pad_y)))
    x1 = int(min(w, round(bx + bw + pad_x)))
    y1 = int(min(h, round(by + bh + pad_y)))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return image, np.eye(3, dtype=np.float64)
    translation = np.array(
        [[1.0, 0.0, -float(x0)], [0.0, 1.0, -float(y0)], [0.0, 0.0, 1.0]], dtype=np.float64
    )
    return image[y0:y1, x0:x1].copy(), translation


def rectify(
    image: Image,
    *,
    marker: Quad | None = None,
    package_box: XYWH | None = None,
    correct_skew: bool = True,
) -> RectifyResult:
    """Flatten the label face. Never raises; degrades instead.

    Four outcomes, in preference order:

    ``marker``        a printed marker of known square geometry was found and
                      the whole plane was rectified against it. Best accuracy,
                      because the reference shape is known rather than assumed.
    ``quad``          a clean label outline was found and warped. Full accuracy.
    ``detector_box``  no quad, but the detector told us where the package is.
                      Foreshortening is uncorrected, so scale tier A should
                      widen its tolerance — see `vision.scale.tier_a`.
    ``identity``      neither. The frame is returned unchanged and the scan is
                      headed for a lower degradation tier, but it still runs:
                      presence, format and regex rules need no geometry at all.
    """
    # `marker` is supplied by the caller rather than detected here, so that
    # `vision.rectify` never imports `vision.scale` — tier A already imports
    # `map_point` from this module, and the reverse edge would close a cycle.
    # It also means the marker is detected once per scan, not twice.
    warped_marker = warp_to_marker(image, marker) if marker is not None else None

    quad = None if warped_marker is not None else find_label_quad(image)

    if warped_marker is not None:
        warped, homography, scale_factor = warped_marker
        method = "marker"
    elif quad is not None:
        warped, homography, scale_factor = warp_to_quad(image, quad)
        method = "quad"
    elif package_box is not None:
        warped, homography = _crop_to_box(image, package_box)
        scale_factor = 1.0
        method = "detector_box"
    else:
        warped, homography = image, np.eye(3, dtype=np.float64)
        scale_factor = 1.0
        method = "identity"

    applied = 0.0
    if correct_skew:
        warped, applied = deskew(warped)
        if applied:
            # Fold the rotation into the homography so raw-space points still
            # map correctly. Forgetting this is how the marker ends up measured
            # in one coordinate frame and the glyphs in another.
            h, w = warped.shape[:2]
            affine = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), applied, 1.0)
            rotation = np.vstack([affine, [0.0, 0.0, 1.0]])
            homography = rotation @ np.asarray(homography, dtype=np.float64)

    return RectifyResult(
        image=warped,
        method=method,  # type: ignore[arg-type]
        quad=quad,
        homography=np.asarray(homography, dtype=np.float64),
        skew_deg=estimate_skew(warped),
        scale_factor=scale_factor,
    )


__all__ = [
    "find_label_quad",
    "map_point",
    "order_corners",
    "rectify",
    "warp_to_marker",
    "warp_to_quad",
]
