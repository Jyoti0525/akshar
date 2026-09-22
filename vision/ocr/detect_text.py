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

BINARY_THRESHOLD = 0.85
BOX_THRESHOLD = 0.45
UNCLIP_RATIO = 1.1
"""DBNet post-processing. **Measured against the corpus, not inherited.**

`data/models/ppocrv6_small_det.yml` ships `thresh: 0.2, box_thresh: 0.45,
unclip_ratio: 1.4`, and those were used here on the reasoning that a threshold
set too high silently drops the faintest regions on the page. That reasoning is
sound and it is not the failure this corpus actually has.

**What the shipped values were doing.** DBNet emits a per-pixel probability of
"this is inside a text line". `thresh` decides which pixels form the blobs that
become contours, and `unclip_ratio` decides how far each contour is then pushed
back out. At 0.2 the blobs are fat: on densely-set small print, the blob of one
line touches the blob of the line above it, the two become **one contour**, and
1.4 then expands the merged result further. The crop handed to recognition
holds three clipped lines stacked on top of each other, and a CTC line
recogniser returns **nothing at all** for it -- not low confidence, nothing. On
`santoor1.jpg`, 18 of 35 regions read as the empty string this way, every one of
them a perfectly legible block of address text.

The pair that fixes it is the opposite of the intuition: take only the *core* of
each line (0.85), where adjacent lines do not touch, and expand it back by a
little less (1.1) than before.

**Character error rate alone would have picked the wrong pair.** Weighted CER is
dominated by the longest strings on a pack -- a 280-character manufacturer
address outweighs an MRP forty to one -- so a setting that shaves a character
off every short value while reading addresses better still *improves* it. This
was very nearly shipped at 0.9/0.5, the grid's weighted-CER minimum, which is
also the grid's **worst MRP reading**: it dropped MRP exact-match to 14/20 and
MRP value accuracy on the real bench from 0.58 to 0.39. Getting a printed price
wrong is the failure this project cannot have.

So the choice was made on `bench/declaration_blocks.py`, which scores what a
rule actually consumes, over all 38 hand-labelled panels:

                        micro F1   precision   recall   MRP F1   MRP value
      0.2 / 1.4  (was)    0.8426      0.9694   0.7451     0.85       0.58
      0.9 / 0.5           0.8670      0.9573   0.7922     0.91       0.39
      0.9 / 0.9           0.8837      0.9587   0.8196     0.91       0.58
      0.85 / 1.1 (is)     0.8913      0.9766   0.8196     0.93       0.66

0.85/1.1 beats the shipped pair on **every** column, precision included -- it is
not a recall-for-precision trade, which is the trade a compliance tool must not
make. Rule 6(1) mandatory recall goes 0.7619 -> 0.8307, batch precision 0.95 ->
1.00, and empty crops across the corpus fall from 85 to 64.

It also sits mid-plateau rather than at an optimum: across the whole
0.80-0.95 x 0.80-1.10 box, weighted CER varies by 0.006 and value CER by 0.008.
Nothing here balances on a knife edge, which is the property worth having when
two numbers are chosen against thirty-eight photographs.

Both ends of the unclip range are held by physics rather than by the fit: below
0.4 the box closes inside the glyphs and clips the first and last character of
every line -- which is exactly what cost 0.9/0.5 its MRPs, and what still shows
on the 8 px synthetic `small_print` golden -- and above 1.4 it re-merges the
neighbours. The measured curve turns at both ends, which is what tells you the
optimum is real rather than the edge of a search.

`BOX_THRESHOLD` is unchanged. It scores the mean probability *inside* a contour,
and tightening the binarisation raises that mean for every surviving region, so
it now rejects strictly less than it did."""
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


def _unclip(rect_points: np.ndarray, ratio: float | None = None) -> np.ndarray:
    """Expand a shrunk DBNet box back to the glyph extent.

    Vatti's offset distance for a polygon of area A and perimeter L expanded by
    `ratio` is `A * ratio / L`. Applied to a rotated rectangle this is an exact
    outward offset of every edge.

    **`ratio` defaults to `None` and is resolved here, not in the signature.**
    A default of `UNCLIP_RATIO` is bound once, when this module is imported, so
    assigning to `detect_text.UNCLIP_RATIO` afterwards changed nothing and did
    so silently. `BINARY_THRESHOLD` and `BOX_THRESHOLD` are both read inside
    `_regions_from_map`, which makes them tunable at runtime; this one looked
    identical and was not, and a threshold sweep over it returned byte-identical
    results for every value — the most convincing possible evidence that a
    parameter does not matter, produced entirely by the way it was declared.
    """
    if ratio is None:
        ratio = UNCLIP_RATIO
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
