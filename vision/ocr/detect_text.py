"""PP-OCRv6 `small_det` — text region proposal (DB-style).

    "v6 released 11 Jun 2026 with PaddleOCR 3.7; LCNetV4 + RepLKFPN. `small`
     over `tiny` (0.43M) because our declarations are the smallest print on the
     pack — benchmark both, downgrade only if field recall holds. Detection is
     script-agnostic, so v6 serves Hindi and English alike."
                                                          -- section 15b

**Detection moved to v6; recognition deliberately did not.** PP-OCRv6's fifty
languages are Chinese, Japanese and forty-six *Latin-script* — **Devanagari is
not among them**. Taking v6 wholesale would have silently dropped Hindi, which
section 7 calls "the requirement that catches everyone out", and the symptom
would have been *"MRP not found"* on perfectly compliant Hindi-only labels: the
worst failure this project can produce. So `recognise.py` stays on PP-OCRv5's
Devanagari head and only this stage advances.

That split is safe precisely because **detection is script-agnostic** — it finds
where ink is, not what the ink says — which is the same property that makes our
core measurement script-independent (section 7).

This stage produces `TextRegion`s and nothing else. It is what makes ROI-only
recognition possible, and therefore what makes the 561 ms budget reachable:

    "We never OCR the photo. Detection hands us candidate text regions, and the
     expensive recognition head runs only on the four to eight crops that could
     plausibly be declarations. That alone is roughly 5x on the stage that
     dominates everything."                               -- section 4

**Unclipping without pyclipper.** DBNet shrinks its training polygons, so the
predicted region must be expanded back. The reference implementation uses
`pyclipper` for a true polygon offset; we use the same Vatti distance formula
applied to the minimum-area rectangle, which is exact for the rectangular
regions printed text actually produces and saves a C++ dependency in the
browser bundle. Curved text on a bottle is the case where it is approximate,
and there the box is slightly generous — which costs a little recognition
context and never loses characters.
"""

from __future__ import annotations

import math
import time

import cv2
import numpy as np

from vision import runtime
from vision.types import Box, Image, TextRegion

MODEL_FILENAME = "ppocrv6_small_det.onnx"
"""PP-OCRv6 `small_det`, the official PaddlePaddle ONNX export, Apache-2.0.

Not `_int8`, which the name here used to claim. The published artifact is
fp32; at 9.88 MB it is within a rounding error of section 15b's ~9.5 MB
estimate, so the bundle budget survives intact. Quantising it is a real option
and belongs to U3 (latency), behind the benchmark section 15b asks for --
**not** a claim to make in a filename before anybody has measured what it costs
in field recall on the smallest print on the pack."""

LIMIT_SIDE = 640
"""Detector input when nothing better is known -- no scale, no millimetres.

Section 4's resolution ladder: detection needs to find boxes, not read them.
That reasoning holds for a pack photographed close, and fails for a pack
photographed beside a marker card. See `input_side`."""

MIN_LINE_PX_AT_INPUT = 10.0
"""Line height, in detector-input pixels, below which DBNet stops finding text.

Measured on 25 dev-corpus photographs by taking the detections at a 2560 input
as the reference set and asking what fraction each smaller input recovers,
bucketed by the region's height at the input it was given:

    height at input     ~5 px    ~6 px    ~12 px
    recall              0-15%      68%       92%

This is a property of the recogniser's detector, not of that corpus -- the
bucket is measured in input pixels, so it transfers to any photograph. It is
the one number in this module that came from an experiment rather than from a
config file, and `docs/` records the sweep."""

LINE_TO_CAP = 1.5
"""A line of print is about half again its capital height, once ascenders and
descenders are counted. Rule 7 legislates *cap* heights; DBNet finds *lines*."""

SMALLEST_STATUTORY_CAP_MM = 1.0
"""Rule 7(3): the smallest letter the law permits on a declaration. Anything
smaller is a violation -- which we can only report if we detected it, so this
is the print the input size has to be chosen for, not the average print."""

LIMIT_SIDE_MAX = 2048
"""Ceiling on the derived input, because detector cost grows with its square.

Section 4's budget is a *browser* budget -- WebGPU first, WASM fallback -- and
the plan's own pre-registered fallback if that budget blows is to drop the
detector input to 512 px (line 2021). So this ceiling is a latency decision and
not a recall one: above it we would rather report a declaration as unread than
miss the scan window entirely."""

BINARY_THRESHOLD = 0.2
BOX_THRESHOLD = 0.45
UNCLIP_RATIO = 1.4
"""DBNet post-processing, taken from the values PP-OCRv6 ships beside itself.

`data/models/ppocrv6_small_det.yml` declares `thresh: 0.2, box_thresh: 0.45,
unclip_ratio: 1.4`. These had been 0.3, 0.6 and 1.6 -- PP-OCRv4's defaults, and
a reasonable guess before the model was in hand. A threshold set too high does
not error and does not look like a bug: it silently drops the faintest regions
on the page, which on a retail pack are exactly the declarations this project
exists to measure."""
MIN_REGION_SIDE = 3

# PaddleOCR's ImageNet normalisation. Wrong constants here do not error; they
# quietly degrade recall on low-contrast print, which is our hardest surface.
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def input_side(image: Image, mm_per_px: float | None) -> int:
    """How large the detector's input has to be to see the smallest legal print.

    With a scale the size is *derived*: the frame spans a known number of
    millimetres, the smallest declaration the law allows is
    `SMALLEST_STATUTORY_CAP_MM` tall, and DBNet needs `MIN_LINE_PX_AT_INPUT`
    pixels to find a line. Those three facts fix the answer.

    ---------------------------------------------------------------------------
    WITHOUT A SCALE, THE OLD ANSWER WAS BACKWARDS
    ---------------------------------------------------------------------------
    This used to return the 640 px floor whenever `mm_per_px` was None, on the
    reasoning that with no millimetre there is nothing to derive from. True, and
    it drew the wrong conclusion: a 4032 px photograph was detected at a **6.3x
    downscale**, so the 1 mm print Rule 7(2) exists to measure fell below a
    pixel and was never proposed at all. Not knowing how small the print is, is
    a reason to keep resolution, not to throw it away.

    Measured on 2026-09-10 over fifteen corpus frames:

        detector input   detect ms   regions   declarations identified
        640 px               21.7        14        15
        2048 px             225.2        42        23   (+53%)

    **The cost is real and it is affordable here.** Section 4 budgets 110 ms for
    detection and 225 ms breaks it. But tier C is precisely the state in which
    the three `min_height_mm` rules already return NO_DATA, so the budget is
    protecting a measurement that is not being made; what is scarce at tier C is
    recall, not milliseconds. Section 4's own pre-registered lever moves the
    other way for the other case -- *"detector input to 512 px"* when latency
    blows -- and this is its mirror.

    The frame's own long side is the ceiling, clamped into
    `[LIMIT_SIDE, LIMIT_SIDE_MAX]`, so a small photograph is never upscaled into
    detail it does not contain and a large one is never cropped by more than the
    ceiling demands.

    **Why this is not a tuned constant.** The alternative was to sweep input
    sizes against the 40 ruler frames and keep whichever scored best. That is
    tuning against a sealed test set: it would make U1 a number this pipeline
    had been fitted to rather than measured against. Every term here comes from
    either the statute or a dev-corpus experiment, and none from the test split.
    """
    if mm_per_px is None or mm_per_px <= 0:
        return int(min(max(max(image.shape[:2]), LIMIT_SIDE), LIMIT_SIDE_MAX))

    span_mm = max(image.shape[:2]) * mm_per_px
    needed_px_per_mm = MIN_LINE_PX_AT_INPUT / (SMALLEST_STATUTORY_CAP_MM * LINE_TO_CAP)
    required = span_mm * needed_px_per_mm
    # Round up, never down: this is a floor on recall, and truncating it puts
    # the smallest legal print back under the threshold it was sized to clear.
    return int(min(max(math.ceil(required), LIMIT_SIDE), LIMIT_SIDE_MAX))


def _preprocess(image: Image, side: int) -> tuple[np.ndarray, float, float]:
    h, w = image.shape[:2]
    scale = side / float(max(h, w))
    # DBNet requires both sides to be multiples of 32.
    new_h = max(32, round(h * scale / 32) * 32)
    new_w = max(32, round(w * scale / 32) * 32)

    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    normalised = (rgb - _MEAN) / _STD
    tensor = np.transpose(normalised, (2, 0, 1))[np.newaxis, ...]
    return np.ascontiguousarray(tensor), w / float(new_w), h / float(new_h)


def _unclip(rect_points: np.ndarray, ratio: float = UNCLIP_RATIO) -> np.ndarray:
    """Expand a shrunk DBNet box back to the glyph extent.

    Vatti's offset distance for a polygon of area A and perimeter L expanded by
    `ratio` is `A * ratio / L`. Applied to a rotated rectangle this is an exact
    outward offset of every edge.
    """
    (cx, cy), (w, h), angle = cv2.minAreaRect(rect_points.astype(np.float32))
    area, perimeter = w * h, 2.0 * (w + h)
    if perimeter <= 0:  # pragma: no cover - degenerate contour
        return rect_points
    distance = area * ratio / perimeter
    return cv2.boxPoints(((cx, cy), (w + 2 * distance, h + 2 * distance), angle))


def _regions_from_map(probability: np.ndarray, scale_x: float, scale_y: float) -> list[TextRegion]:
    binary = (probability > BINARY_THRESHOLD).astype(np.uint8)
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    regions: list[TextRegion] = []
    for contour in contours:
        if len(contour) < 4:
            continue

        # Score the region by the mean probability inside it, not by its area.
        #
        # Scored inside the contour's own bounding box rather than over the
        # whole map. The two give identical scores; the difference is that the
        # naive form allocates a full-frame mask per contour and averages over
        # every pixel of it, which is O(contours x frame). At a 2048 input that
        # made post-processing **1747 ms against the model's 172 ms** -- ten
        # times the cost of the network it was interpreting, and the reason a
        # GPU appeared to buy almost nothing.
        x, y, w_box, h_box = cv2.boundingRect(contour)
        if w_box <= 0 or h_box <= 0:  # pragma: no cover - degenerate contour
            continue
        mask = np.zeros((h_box, w_box), dtype=np.uint8)
        cv2.drawContours(mask, [contour - np.array([[x, y]])], -1, 1, -1)
        if not mask.any():  # pragma: no cover
            continue
        score = float(probability[y : y + h_box, x : x + w_box][mask.astype(bool)].mean())
        if score < BOX_THRESHOLD:
            continue

        points = _unclip(contour.reshape(-1, 2))
        xs, ys = points[:, 0] * scale_x, points[:, 1] * scale_y
        x0, y0 = float(xs.min()), float(ys.min())
        w, h = float(xs.max() - x0), float(ys.max() - y0)
        if w < MIN_REGION_SIDE or h < MIN_REGION_SIDE:
            continue

        regions.append(
            TextRegion(
                box=Box(x=max(x0, 0.0), y=max(y0, 0.0), w=w, h=h),
                score=score,
                polygon=[(float(px * scale_x), float(py * scale_y)) for px, py in points],
            )
        )

    # Reading order: top to bottom, then left to right. The classifier's
    # position features and the report's layout both assume it.
    regions.sort(key=lambda r: (round(r.box.y / 10.0), r.box.x))
    return regions


def propose_regions(
    image: Image, *, mm_per_px: float | None = None, model_name: str = MODEL_FILENAME
) -> tuple[list[TextRegion], float, str]:
    """Candidate text regions on a rectified label. Returns (regions, ms, version).

    `mm_per_px` is optional and comes from `vision.scale`. Supplying it lets the
    input size be derived rather than assumed; omitting it is the old behaviour
    and is what the scale-free tiers get.
    """
    model = runtime.load(model_name)

    started = time.perf_counter()
    tensor, scale_x, scale_y = _preprocess(image, input_side(image, mm_per_px))
    outputs = model.session.run(None, {model.input_name: tensor})
    probability = outputs[0][0, 0]
    regions = _regions_from_map(probability, scale_x, scale_y)
    elapsed = (time.perf_counter() - started) * 1000.0

    return regions, elapsed, model.version


def is_available(model_name: str = MODEL_FILENAME) -> bool:
    return runtime.available(model_name)


__all__ = [
    "BOX_THRESHOLD",
    "LIMIT_SIDE",
    "LIMIT_SIDE_MAX",
    "MIN_LINE_PX_AT_INPUT",
    "MODEL_FILENAME",
    "UNCLIP_RATIO",
    "input_side",
    "is_available",
    "propose_regions",
]
