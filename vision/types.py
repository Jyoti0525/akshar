"""Vision-internal vocabulary — AKSHAR.md sections 8 and 17.

Everything in here is *extraction* machinery. None of it crosses the wall into
`rules/`; the only thing that does is a `DeclarationSet` (section 3, principle
one). If you find yourself importing one of these types from `rules/`, the
boundary has leaked.

**Why raw pixels are not `contracts.Box`.** `contracts.Box` documents itself as
living in *rectified label space*, because `Box.h` there is proportional to true
printed height and is multiplied by a single scalar to get millimetres. A box in
raw camera space has no such property — perspective makes the far end of a
packet smaller than the near end, so the same 2 mm glyph measures differently
depending on where it sits in frame. Putting one in a `Box` would produce a
confident, wrong measurement.

So raw-space geometry uses plain `XYWH` tuples and `Quad`, and only crosses into
`contracts.Box` after `vision.rectify` has applied the homography. The type
system does the remembering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from contracts import Box, PanelId, ScaleTier, Script

if TYPE_CHECKING:  # pragma: no cover - typing only
    import numpy as np
    from numpy.typing import NDArray

    Image = NDArray[np.uint8]
else:  # pragma: no cover - runtime alias, keeps numpy optional at import time
    Image = "NDArray[np.uint8]"


Point = tuple[float, float]
Quad = tuple[Point, Point, Point, Point]
"""Four corners in raw camera space, ordered top-left, top-right,
bottom-right, bottom-left."""

XYWH = tuple[float, float, float, float]
"""A box in RAW camera space. Deliberately not `contracts.Box`."""


# ---------------------------------------------------------------------------
# Rectification (M1)
# ---------------------------------------------------------------------------

RectifyMethod = Literal["marker", "quad", "detector_box", "identity"]
"""How the rectified image was obtained.

``marker``        a printed marker of known square geometry was found, and the
                  whole plane was rectified against it. The strongest option:
                  a square is square by construction, whereas a label outline
                  is only *assumed* to be a rectangle — and on a pouch or a
                  shaped carton it is not one.
``quad``          a clean four-sided label outline was found and warped.
``detector_box``  no clean quad; the detector's package box was cropped
                  axis-aligned. Measurement is still possible but the
                  uncertainty is larger, so tolerance widens.
``identity``      nothing was found; the frame is passed through unchanged and
                  the scan degrades.
"""


@dataclass(frozen=True, slots=True)
class RectifyResult:
    """Output of M1. `image` is the flattened label."""

    image: Image
    method: RectifyMethod
    quad: Quad | None
    homography: Image | None
    """3x3 forward transform, raw -> rectified. Kept so a box detected in raw
    space (the marker, say) can be mapped into rectified space rather than
    re-detected."""

    skew_deg: float | None = None
    """Residual deviation of printed baselines from horizontal, after warping.
    M1's acceptance criterion is < 2 degrees across the 40 test photos."""

    scale_factor: float = 1.0
    """Rectified pixels per raw pixel along the reference edge. `mm_per_px`
    measured on the raw image must be divided by this to stay true after the
    warp — the single most dangerous unit slip in the project."""


@dataclass(frozen=True, slots=True)
class Transform:
    """The way back to the photograph. AKSHAR.md section 8b, B3.

    Every `Box` in a `DeclarationSet` is in **rectified** space — the contract
    says so in `contracts/declarations.py`, and it has to, because a height in
    raw camera pixels is not proportional to printed height and cannot be
    converted to millimetres by one scalar. That is the right space to measure
    in and the wrong space to *show* anyone: section 6 wants an annotated
    exhibit, and an exhibit has to be the officer's photograph with the measured
    region marked on it. Nobody disputing a finding will accept a warped
    rectangle they have never seen as evidence of what was on their pack.

    So the forward matrix is kept rather than the rectified image alone, and
    this carries the inverse with it.

    ---------------------------------------------------------------------------
    **A box does not map back to a box.** It maps back to a quadrilateral.

    That is not a detail to round off. A perspective warp does not preserve
    right angles, so the four corners of a rectified box land on four points
    that are not, in general, the corners of an axis-aligned rectangle — on a
    steeply angled shot they are visibly a trapezium. Drawing the bounding box
    of those four points would mark a region *larger than the one measured*, on
    an exhibit whose entire purpose is to show exactly what was measured. So
    `box_to_original` returns a `Quad` and there is deliberately no function
    here that returns an `XYWH`: a caller that wants one has to compute it
    itself, and thereby has to know it is approximating.
    """

    homography: Image
    """3x3, raw photograph -> rectified. The same matrix `RectifyResult` carries;
    held here so the context can offer the round trip without the image."""

    method: RectifyMethod
    original_size: tuple[int, int]
    """`(height, width)` of the photograph as decoded, so a caller can tell
    whether a mapped point landed outside the frame it is about to draw on."""

    rectified_size: tuple[int, int]
    """`(height, width)` of the flattened label the boxes are measured in."""

    @property
    def is_identity(self) -> bool:
        """True when rectification did nothing — no warp, no deskew.

        Worth asking: a second pass that re-crops from the original gains
        nothing when the original and the rectified image are the same pixels.
        """
        import numpy as _np

        return bool(_np.allclose(self.homography, _np.eye(3), atol=1e-9))

    def inverse(self) -> Image | None:
        """Rectified -> raw. `None` when the matrix is singular.

        Returned rather than raised. A degenerate homography is a bad
        photograph, not a bug, and the consequence is one missing annotation on
        an exhibit rather than a failed scan.
        """
        import numpy as _np

        try:
            return _np.linalg.inv(_np.asarray(self.homography, dtype=_np.float64))
        except _np.linalg.LinAlgError:  # pragma: no cover - needs a singular warp
            return None

    def point_to_original(self, point: Point) -> Point | None:
        inverse = self.inverse()
        if inverse is None:
            return None
        return _project(inverse, point)

    def point_to_rectified(self, point: Point) -> Point:
        return _project(_as_matrix(self.homography), point)

    def box_to_original(self, box: Box) -> Quad | None:
        """The four corners of a rectified box, on the original photograph.

        Corner order is preserved — top-left, top-right, bottom-right,
        bottom-left *as they were in rectified space* — so a polygon drawn
        through them never self-intersects, however the perspective moved them.
        """
        inverse = self.inverse()
        if inverse is None:
            return None
        x, y, w, h = float(box.x), float(box.y), float(box.w), float(box.h)
        corners = ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
        mapped = tuple(_project(inverse, corner) for corner in corners)
        return mapped  # type: ignore[return-value]


def _as_matrix(matrix: Image) -> Image:
    import numpy as _np

    return _np.asarray(matrix, dtype=_np.float64)


def _project(matrix: Image, point: Point) -> Point:
    import numpy as _np

    vec = _np.array([point[0], point[1], 1.0], dtype=_np.float64)
    out = _as_matrix(matrix) @ vec
    if abs(out[2]) < 1e-12:  # pragma: no cover - degenerate homography
        return point
    return float(out[0] / out[2]), float(out[1] / out[2])


# ---------------------------------------------------------------------------
# Scale (M2)
# ---------------------------------------------------------------------------

ScaleMethod = Literal["aruco", "operator_height", "known_sku", "none"]
"""How `mm_per_px` was obtained.

``aruco``      a printed marker of known physical size (tier A, section 8b B3).
``known_sku``  stored label dimensions for a SKU seen before (tier B).
``none``       no scale at all (tier C) — a real answer, not a failure.

The coin is gone. A circle foreshortens into an ellipse the moment the camera
tilts and gives one dimension; a marker gives four sub-pixel corners, and so
yields the scale and the homography from one detection.
"""


@dataclass(frozen=True, slots=True)
class ScaleEstimate:
    """Millimetres per rectified pixel, or an honest absence of one.

    Tier C is a real answer, not a failure: it carries ``mm_per_px is None``,
    and the two ``scale_free`` rules plus every presence, format, placement and
    unit-symbol rule still run against it. Only the three ``min_height_mm``
    rules go dark.
    """

    tier: ScaleTier
    mm_per_px: float | None
    tolerance: float | None
    """Half-width of the estimate's confidence interval, in mm/px. Propagates
    into `Declaration.height_mm_tolerance` so a REVIEW band is derived from
    real measurement uncertainty rather than a guessed constant."""

    method: ScaleMethod
    detail: str = ""
    """Human-readable provenance, shown in the report: "ArUco DICT_4X4_50 id 7,
    25 mm edge, 88.2 px rectified". An officer must be able to see what the
    ruler was."""

    reference_box: XYWH | None = None
    """Where the reference object was found, so the report can circle it."""

    @property
    def is_measurable(self) -> bool:
        return self.mm_per_px is not None


# ---------------------------------------------------------------------------
# Detection (M3)
# ---------------------------------------------------------------------------

DetectClass = Literal["package", "panel"]
"""Two classes, which is why RTMDet-Ins-tiny is enough (section 15b)."""


@dataclass(frozen=True, slots=True)
class DetectedObject:
    box: XYWH
    cls: DetectClass
    score: float
    polygon: list[Point] | None = None
    """Segmentation outline. For a panel this becomes `LabelGeometry.pdp_polygon`
    after rectification, and Rule 8(1)'s clear-space check depends on it."""


@dataclass(frozen=True, slots=True)
class DetectionResult:
    objects: list[DetectedObject] = field(default_factory=list)
    inference_ms: float = 0.0
    model_version: str = ""

    def packages(self) -> list[DetectedObject]:
        return [o for o in self.objects if o.cls == "package"]

    def panels(self) -> list[DetectedObject]:
        return [o for o in self.objects if o.cls == "panel"]

    def best_package(self) -> DetectedObject | None:
        """The largest confident package. A shelf photo may contain several;
        the officer is pointing at one, and it is the one filling the frame."""
        packages = self.packages()
        if not packages:
            return None
        return max(packages, key=lambda o: o.box[2] * o.box[3] * o.score)

    def has_package(self) -> bool:
        """False triggers pipeline exit one — "point the camera at a product",
        about 110 ms. The 60 negative photos exist to make this reliable."""
        return bool(self.packages())


# ---------------------------------------------------------------------------
# OCR (M4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TextRegion:
    """A candidate text area proposed by detection, before recognition runs.

    These are what makes ROI-only OCR possible: the expensive recognition head
    runs on four to eight of these, never on the twelve-megapixel frame.
    """

    box: Box
    """Rectified space — regions are proposed on the rectified crop."""

    score: float
    polygon: list[Point] | None = None
    script_hint: Script | None = None

    line_height_px: float | None = None
    """How tall the type is, when the box no longer says.

    For a region straight from the detector this is None and the box's minor
    axis is the answer. For a region assembled from several word proposals by
    `vision.ocr.lines` it is not: fragments of one line do not sit at exactly
    the same height, so the union box is taller than any of them. `MRP Rs.`
    spanning y 585-621 and the `10` beside it spanning y 597-629 union to 44 px
    of box for 34 px of type -- a 29% overstatement, enough to push a
    declaration out of the statutory size band and lose it the crop it needed.

    So a merged region carries the median height of its parts, and the ranking
    prefers this over the box. It is deliberately not used for *measurement*:
    cap height comes from the ink, never from a box."""


@dataclass(frozen=True, slots=True)
class OcrLine:
    """One recognised line, with the geometry the measurement stage needs."""

    text: str
    box: Box
    confidence: float
    script: Script
    char_boxes: list[Box] = field(default_factory=list)
    """Per-character geometry. `min_width_ratio` (Rule 7(3) proviso) needs it;
    when the engine cannot supply it that check returns NO_DATA rather than
    inventing character widths by dividing the line box."""

    panel_id: PanelId | None = None
    engine: str = ""
    """Which recognition head produced this, so a cross-check disagreement can
    name both engines in the report."""

    # -- measured while the crop is in hand ---------------------------------
    #
    # These three are computed during the OCR pass rather than later, because
    # the alternative is re-cropping the same region a second time in
    # `classify`. Section 4 gives the whole scan 561 ms; paying twice for the
    # same pixels to keep a data structure tidy is not a trade worth making.

    cap_height_px: float | None = None
    """Top of a capital to the baseline, descenders excluded. NOT `box.h`."""

    cap_height_confidence: float | None = None
    """How much of the crop's ink agreed on the baseline `cap_height_px` was
    measured from, 0..1. Carried because `CapHeightResult.confidence` says what
    to do with it and nothing was doing it:

        "Low confidence means a multi-line or badly segmented crop, and the
         caller should widen tolerance rather than assert a height."

    It was computed on every crop and dropped on the floor at `roi.py`, so a
    height measured across two printed lines claimed exactly the same precision
    as one measured off a clean single line. `vision.measure.to_mm` now scales
    the glyph term by its reciprocal, which is the widening that sentence asks
    for. Measured over 787 crops of the 38 development panels: median 0.90, 41%
    at exactly 1.0, 13% below 0.5 — a real signal rather than a constant, and
    the low tail is the multi-line crops it was meant to catch.

    `None` where no cap height was measured, and then nothing is widened."""

    numeral_box: Box | None = None
    """Sub-box over the digits. Its *position* feeds Rule 8(1) clear space; its
    height is not a measurement -- see `numeral_height_px`."""

    numeral_height_px: float | None = None
    """Height of the digits alone, from `measure_numeral_height`.

    Separate from `numeral_box.h` because the two are computed by different
    methods and only one of them is trustworthy. `numeral_box` comes from
    column-run segmentation, which finds *where* each character is by scanning
    for ink columns; the vertical extent of such a run is whatever ink happens
    to sit in those columns, including the neighbouring line the crop padding
    caught and the printer's rule underneath. Measured on `449.00` from
    `bodywash_bottle_300ml`, the six per-character heights came back as
    [52, 41, 52, 52, 41, 42] px on a 52 px crop, for digits that are 19 px
    tall -- the segmentation had found the crop, not the figures.

    `measure_numeral_height` works from connected components instead: it drops
    anything spanning the crop, clusters on the shared baseline, and takes the
    median of the tall cluster, which is what lining figures form. It is a
    scalar rather than a box, so unlike `numeral_box` it also cannot be read
    along the wrong axis on rotated text -- it is measured on the oriented
    crop, where the glyphs are already upright."""

    contrast_ratio: float | None = None
    """WCAG ratio against the local background, for Rules 9(1)(b) and 18(5)."""

    contrast_tolerance: float | None = None
    """How far `contrast_ratio` can be trusted, measured on the same crop.

    Wide where the crop is out of focus, near zero where it is sharp. See
    `vision.measure.contrast.contrast_band` for why a legibility verdict
    without this became a false accusation against a legible pack."""

    rotation_k: int = 0
    """Quarter-turns anticlockwise applied to read this line, 0 for upright text.

    Recorded because it changes which side of a box carries glyph *height*.
    Text running down the side of a pack -- where net quantity and batch codes
    very often sit -- has its height across `box.w`, and `box.h` is how far the
    line runs. `vision.measure.orientation.glyph_axis` is the one place that
    decision is made; nothing should re-derive it from the box's shape, because
    a single upright digit is also taller than it is wide."""


@dataclass(frozen=True, slots=True)
class OcrResult:
    lines: list[OcrLine] = field(default_factory=list)
    regions_proposed: int = 0
    regions_read: int = 0
    inference_ms: float = 0.0
    model_version: str = ""

    @property
    def coverage(self) -> float:
        """Fraction of detected text regions successfully read.

        This is the number shown on the scan screen. It is the honest answer to
        "how much of this label did you actually understand", and it is what
        separates degradation tier L3 from a silent partial read.
        """
        if self.regions_proposed <= 0:
            return 0.0
        return min(1.0, self.regions_read / self.regions_proposed)

    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


# ---------------------------------------------------------------------------
# Identity (M9)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Identity:
    """What we know about which product this is, before any model runs.

    Computed first, because exit zero — the cache — depends on it and costs
    about 12 ms against roughly 561 ms for the full path.
    """

    phash: int | None = None
    """64-bit DCT perceptual hash. Match at Hamming distance <= 8."""

    barcode: str | None = None
    """EAN-13 when readable. Tried before pHash: a barcode is an exact key."""

    embedding: list[float] | None = None
    """MobileNetV3-Small penultimate layer, PCA-reduced to 512-d, for
    near-duplicate SKU search via pgvector cosine."""

    def cache_key(self) -> str | None:
        if self.barcode:
            return f"barcode:{self.barcode}"
        if self.phash is not None:
            return f"phash:{self.phash:016x}"
        return None


__all__ = [
    "XYWH",
    "Box",
    "DetectClass",
    "DetectedObject",
    "DetectionResult",
    "Identity",
    "Image",
    "OcrLine",
    "OcrResult",
    "Point",
    "Quad",
    "RectifyMethod",
    "RectifyResult",
    "ScaleEstimate",
    "ScaleMethod",
    "ScaleTier",
    "TextRegion",
    "Transform",
]
