"""M4 — ROI-only OCR. The rule this module exists to enforce.

    "Never OCR the full image; detection supplies the crops. Devanagari and
     Latin both enabled. Done when: baseline CER recorded per surface type
     before any fine-tuning decision, and the ROI path at least 5x faster than
     full-image on the same photos."                      -- section 17, M4

    "ROI-only OCR. We never OCR the photo. [...] That alone is roughly 5x on
     the stage that dominates everything."                -- section 4

The whole 561 ms budget rests on this one discipline, so it is expressed as a
hard cap — `MAX_REGIONS` — rather than as an intention. The recognition head is
the most expensive thing in the pipeline; if a glare-covered pack proposes
sixty text regions, reading all of them would cost four seconds and the extra
fifty-two would be marketing copy we discard immediately.

**How the four to eight are chosen.** Not by score. A region is worth reading
if it could plausibly carry a declaration, and the law tells us where those
are: on the principal display panel, reasonably prominent. So regions are
ranked by height — declarations are set larger than ingredient lists — and by
whether they fall on the detected PDP. That ranking is a heuristic and it can
be wrong, which is why the regions we *skipped* are counted into `coverage`
rather than quietly forgotten. An officer sees "read 6 of 9 regions" and knows
what they are trusting.
"""

from __future__ import annotations

import time

import cv2
import numpy as np

from vision import runtime
from vision.measure.cap_height import measure_cap_height, measure_numeral_height
from vision.measure.characters import character_boxes, numerals_of
from vision.measure.contrast import contrast_band
from vision.measure.orientation import unrotate_box
from vision.ocr import detect_text, dictionary, recognise, rows
from vision.ocr import script as script_mod
from vision.ocr.lines import merge_into_lines
from vision.types import Box, Image, OcrLine, OcrResult, PanelId, Point, TextRegion

MAX_REGIONS = 64
"""How many proposed regions the first pass reads.

Section 4 assumes "four to eight crops", and this was 8 to make that a fact
rather than an aspiration. The assumption behind the number was that
recognition costs per crop; it did, at 56.9 ms each, because each crop was its
own ONNX run. Batching them (`recognise.read_batch`) makes the marginal crop
nearly free, and the whole-frame cost was measured across three ruler-set
photographs:

    crops read      23      66     113     151
    ms per frame  1339    1795    1947    1778

Six and a half times the regions for a third more time, and the ~1.3 s that
does not move is detection and rectification. A budget of eight was buying
almost nothing and it was **choosing which declaration to lose**: on the ruler
set the ranker's eight crops missed the retail sale price on most frames, and
every heuristic that picks which eight to read is another chance to discard the
one that mattered.

Section 17's discipline is untouched -- *"never OCR the full image; detection
supplies the crops"* -- because these are still the detector's regions and not
the photograph. What has changed is only the arithmetic the number 8 was
derived from.

This does put a scan at roughly 1.8 s on this machine, against section 4's
561 ms. That budget is a browser-latency claim (U3) and it has never been
measured in a browser; section 18b's fail-path for it is explicit -- detector
input 640 to 512, ROI count capped at the top four, INT8 everywhere -- so the
lever exists if latency turns out to bind. Spending it before knowing that a
declaration can be found at all would be optimising the wrong thing.
"""

CROP_PADDING = 0.12
"""Fraction of region height added on each side. Recognition accuracy improves
with a little context, and `contrast_ratio` needs background around the glyphs
to compare them against."""

ESCALATED_REGIONS = 160
"""The crop budget when the cheap pass came back without a declaration.

Spent **only** on a pack where the first pass found no retail sale price and no
net quantity, which is a pack that would otherwise return nothing at all. An
officer waiting three seconds for an answer is in a different position from an
officer being told the label is unreadable, and the second outcome is the one
this exists to avoid.

Measured on the sealed forty as a diagnostic, before it was built: 8 crops
measured 4 frames, 24 measured 6, 48 measured 9. Past 48 the merged-line count
on a dense label runs out (102 lines on `shampoo_400ml`, most of them
ingredients), so the ceiling is set where the returns stop rather than at the
number of lines.

Detection is paid once by `propose_lines` and is not repeated; recognition is
batched, so the marginal crop here costs a few milliseconds rather than the
38 ms it cost when this constant was first set.
"""

MIN_REGION_HEIGHT_PX = 6
"""Below this a crop cannot be recognised or measured, and reading it would
add a low-confidence line that only dilutes coverage."""

STATUTORY_MAX_MM = 6.0
"""The tallest cap height any rule in the pack actually requires.

Rule 7(2) Table I sets numerals at 1, 2 or 4 mm by net quantity; Table II at
1 to 6 mm by panel area; Rule 7(3) sets letters at 1 mm. Nothing legally
required is above 6 mm. Print between here and `DECLARATION_BAND_MM`'s ceiling
is still *plausibly* a declaration -- a manufacturer may print generously -- but
it is second in line behind print at a size the law names."""

DECLARATION_BAND_MM = (0.8, 12.0)
"""Cap heights, in millimetres, inside which a region might be a declaration.

**Ranking by pixel height alone reads the brand name.** That was this module's
first rule and its reasoning was sound as far as it went -- *"declarations are
set larger than ingredient lists"* -- but it stops one size short. On a real
pack the largest print is the brand, the flavour and the promotional copy, and
`MAX_REGIONS` is spent on those before a declaration is reached. Measured on
the ruler set: at the cap of 8, `protein_powder_400g` read `'8]'`, a stray
Devanagari glyph and `'2'`; raising the cap to 40 on the same photograph
surfaced `'Net Quantity:'`, `'Bach No:'`, `'USE BY:'` and two dates. **Nothing
was wrong with the recogniser. The eight crops were spent in the wrong place.**

So the ordering now uses the one thing this project has that a generic OCR
pipeline does not: a scale in millimetres, and a statute that says how tall a
declaration is. Rule 7(2) Table I sets numerals at 1, 2 or 4 mm by net
quantity, Table II at 1 to 6 mm by panel area, and Rule 7(3) sets letters at
1 mm. Nothing legally required is above 6 mm, and print above about 12 mm is
branding.

**The lower edge is 0.8 mm, deliberately below the 1 mm legal minimum.** A
declaration printed too small is the violation the tool exists to catch, and a
band starting at 1.0 mm would rank it last, leave it unread, and report a
missing declaration instead of an undersized one -- turning a precise FAIL into
a vague one, in the manufacturer's favour.

This is a preference, not a filter. Out-of-band regions are still ranked and
still read when fewer than `MAX_REGIONS` fall inside, so a pack that prints its
MRP at 15 mm is not skipped for being generous."""


def _point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    contour = np.asarray(polygon, dtype=np.float32).reshape(-1, 1, 2)
    return cv2.pointPolygonTest(contour, (float(point[0]), float(point[1])), False) >= 0


def _line_height_px(region: TextRegion) -> float:
    """How tall the *line of print* is, whichever way the text runs.

    **`box.h` is not the line height when the text is vertical.** A declaration
    printed down the side of a pack gives a box that is narrow and long, and its
    `h` is the length of the sentence rather than the size of the letters. On
    `turmeric_powder_10g` the MRP measured 17.5 mm that way -- outside
    `DECLARATION_BAND_MM` and therefore ranked below the branding -- when the
    print is 5.7 mm tall. The MRP was detected, read as `'MRP():5-'` and
    classified `mrp` at 0.88 confidence, and then discarded by the crop budget.

    The minor axis is the line height for horizontal text too, where it is
    simply `h` again, so this is not a special case bolted on. It is the same
    assumption the recogniser had to be taught (`recognise._orientations`):
    text on packaging does not always run left to right.
    """
    if region.line_height_px is not None:
        # An assembled line knows its own type size better than its bounding
        # box does; see TextRegion.line_height_px.
        return region.line_height_px
    return min(region.box.w, region.box.h)


def rank_regions(
    regions: list[TextRegion],
    *,
    pdp_polygon: list[Point] | None = None,
    limit: int = MAX_REGIONS,
    mm_per_px: float | None = None,
) -> tuple[list[TextRegion], list[TextRegion]]:
    """Split proposals into (to read, skipped), preserving reading order.

    Returns both halves because the skipped ones are not free to ignore: they
    are the denominator of `coverage`, and coverage is what tells an officer
    how much of the label the verdict is actually based on.
    """
    usable = [r for r in regions if _line_height_px(r) >= MIN_REGION_HEIGHT_PX]

    low, high = DECLARATION_BAND_MM

    def priority(region: TextRegion) -> tuple[float, float, float, float, float]:
        on_pdp = (
            1.0
            if pdp_polygon and _point_in_polygon((region.box.cx, region.box.cy), pdp_polygon)
            else 0.0
        )
        height = _line_height_px(region)
        if mm_per_px is None:
            # Scale tier C. There is no millimetre to reason about, so this is
            # the original height ordering, unchanged.
            return (on_pdp, 0.0, 0.0, 0.0, height)

        mm = height * mm_per_px
        if low <= mm <= high:
            # Inside the plausible band, prefer the sizes the statute actually
            # legislates. Ranking the whole band by "bigger first" reproduces
            # the very bias the band was introduced to remove, one level down:
            # on `turmeric_powder_10g` the MRP is 5.7 mm and lost all eight
            # crops to in-band print of 6.3 to 10.9 mm.
            statutory = 1.0 if mm <= STATUTORY_MAX_MM else 0.0
            return (on_pdp, 1.0, statutory, 0.0, height)
        # Outside the band, prefer the near miss over the billboard.
        return (on_pdp, 0.0, 0.0, -min(abs(mm - low), abs(mm - high)), height)

    ordered = sorted(usable, key=priority, reverse=True)
    chosen = {id(r) for r in ordered[:limit]}

    keep = [r for r in regions if id(r) in chosen]
    skip = [r for r in regions if id(r) not in chosen]
    return keep, skip


def _crop(image: Image, box: Box) -> tuple[Image, float, float]:
    """The padded crop, and the rectified coordinates of its top-left corner.

    The offset is returned rather than assumed to be `box.x, box.y`: the crop is
    padded, so it starts *above and left of* the region, and every character box
    measured inside it was being reported that much too far down and right.
    """
    h, w = image.shape[:2]
    # Padded by the line height, not by `box.h`. For vertical text those are
    # different numbers and the difference is ruinous: the MRP on
    # `turmeric_powder_10g` is a 91x426 box, so padding by `h` added 51 px to
    # each side of a 91 px-wide crop and left the glyphs sitting in 47%
    # background. For horizontal text the minor axis *is* `h`, so nothing
    # about the common case changes.
    pad = max(2.0, min(box.w, box.h) * CROP_PADDING)
    x0 = int(max(0, round(box.x - pad)))
    y0 = int(max(0, round(box.y - pad)))
    x1 = int(min(w, round(box.x2 + pad)))
    y1 = int(min(h, round(box.y2 + pad)))
    return image[y0:y1, x0:x1], float(x0), float(y0)


def _panel_of(box: Box, pdp_polygon: list[Point] | None) -> PanelId:
    if pdp_polygon is None:
        return "unknown"
    return "pdp" if _point_in_polygon((box.cx, box.cy), pdp_polygon) else "side"


def _heads_for(crop: Image) -> list[str]:
    """Which recognition heads this crop should be put through, deduplicated.

    The script classifier names one head, and asks for the second when it is
    unsure. Both keys currently resolve to the same weights and the same
    character table -- one head covers Latin and Devanagari, and
    `recognise.MODEL_FILENAMES` explains at length why that is the plan's
    default rather than a missing file. So "run both heads when unsure" was
    running one head twice, decoding the same logits against the same table and
    picking between two identical readings, at exactly double the cost on every
    crop the classifier was unsure about.

    Deduplicating here rather than deleting the second candidate keeps the
    shape of the decision: the day a benchmark justifies a separate Latin head,
    the pair stops collapsing and the crop is genuinely read twice.
    """
    guess, confidence = script_mod.detect_script(crop)
    if guess == "other":
        guess = "latin"

    candidates: list[str] = [guess]
    if script_mod.needs_both_heads(confidence):
        candidates.append("devanagari" if guess == "latin" else "latin")

    seen: set[tuple[str, str]] = set()
    heads: list[str] = []
    for script in candidates:
        key = (
            recognise.MODEL_FILENAMES.get(script) or "",
            dictionary.DICT_FILENAMES.get(script) or "",  # type: ignore[arg-type]
        )
        if key in seen:
            continue
        seen.add(key)
        heads.append(script)
    return heads


def _read_one(crop: Image) -> tuple[recognise.Recognised, str, Image, int] | None:
    """Recognise a crop with the right head, paying for both only when unsure.

    Returns the reading, the head that produced it, **the crop as it was read**
    and the quarter-turns applied to get there. The last two exist because the
    measurement stage has to work on the same pixels: cap height, character
    segmentation and contrast all assume horizontal text, and handing them the
    original crop would have them measure the wrong axis on the 37% of regions
    that run down the side of a pack.
    """
    best: tuple[recognise.Recognised, str, Image, int] | None = None
    for script in _heads_for(crop):
        try:
            result, oriented, k = recognise.read(crop, script)  # type: ignore[arg-type]
        except runtime.ModelUnavailableError:
            continue
        if result.text and (best is None or result.confidence > best[0].confidence):
            best = (result, script, oriented, k)
    return best


def _read_all(crops: list[Image]) -> list[tuple[recognise.Recognised, str, Image, int] | None]:
    """Every crop, read in as few ONNX runs as the heads allow.

    Section 8b's B7 opens *"first pass batches every detected crop at working
    resolution"*. This is that pass. Crops are grouped by the head they need
    and each group goes through `recognise.read_batch`, which sorts by width
    and pads within a bucket -- measured at 2.5x the per-crop loop on real
    regions from the dev corpus, 56.9 ms/crop down to 22.9.

    That number is why the crop budget can stop being the thing that decides
    whether a declaration is found. A ranker exists because reading is
    expensive; every heuristic that picks *which eight regions to read* is a
    chance to discard the one that mattered, and on the ruler set it was taking
    that chance. Reading is still capped -- a glare-covered pack can propose
    sixty regions and we do not owe it four seconds -- but the cap is now set
    by what the budget affords rather than by what the loop could bear.
    """
    out: list[tuple[recognise.Recognised, str, Image, int] | None] = [None] * len(crops)
    if not crops:
        return out

    groups: dict[str, list[int]] = {}
    for index, crop in enumerate(crops):
        for script in _heads_for(crop):
            groups.setdefault(script, []).append(index)

    for script, indices in groups.items():
        try:
            readings, _ = recognise.read_batch(
                [crops[i] for i in indices], script  # type: ignore[arg-type]
            )
        except runtime.ModelUnavailableError:
            continue
        for i, (result, oriented, k) in zip(indices, readings, strict=True):
            if not result.text:
                continue
            current = out[i]
            if current is None or result.confidence > current[0].confidence:
                out[i] = (result, script, oriented, k)
    return out


def read_regions(
    rectified: Image,
    regions: list[TextRegion],
    *,
    pdp_polygon: list[Point] | None = None,
    limit: int = MAX_REGIONS,
    mm_per_px: float | None = None,
) -> OcrResult:
    """Recognise the chosen regions and measure them. Never the whole image."""
    started = time.perf_counter()
    keep, skip = rank_regions(regions, pdp_polygon=pdp_polygon, limit=limit, mm_per_px=mm_per_px)

    lines: list[OcrLine] = []
    version = ""

    prepared: list[tuple[TextRegion, Image, float, float]] = []
    for region in keep:
        crop, x0, y0 = _crop(rectified, region.box)
        if crop.size == 0:
            continue
        prepared.append((region, crop, x0, y0))

    readings = _read_all([crop for _, crop, _, _ in prepared])

    for (region, crop, x0, y0), read in zip(prepared, readings, strict=True):
        if read is None:
            continue
        result, script, oriented, k = read

        panel = _panel_of(region.box, pdp_polygon)
        origin = Box(x=region.box.x, y=region.box.y, w=region.box.w, h=region.box.h, panel_id=panel)

        # Everything measurable about this crop is measured now, while it is
        # in hand -- and measured on `oriented`, the pixels the text was read
        # from, so that every measurement below is taken along the axis the
        # glyphs actually run. `classify` then needs no pixels at all.
        crop_h, crop_w = crop.shape[:2]
        oriented_h, oriented_w = oriented.shape[:2]
        cap = measure_cap_height(oriented)

        # Segmented in the oriented frame, then carried back: first the
        # rotation is undone, then the crop's own offset is added. Reporting
        # boxes in the frame we happened to read them in would put every
        # character of a vertical declaration on the wrong side of the pack.
        in_crop = character_boxes(
            oriented, result.text, Box(x=0.0, y=0.0, w=float(oriented_w), h=float(oriented_h))
        )

        # The digits' columns, still in the oriented frame -- they are what
        # tells `measure_numeral_height` which ink is the figure and which is
        # the label printed beside it. See its docstring for why this is not
        # simply "the tallest components on the line".
        digit_columns = [
            (box.x, box.x2)
            for ch, box in zip(result.text, in_crop, strict=False)
            if ch.isdigit()
        ]
        numeral_height = measure_numeral_height(
            oriented, result.text, columns=digit_columns or None
        )
        boxes = [
            Box(
                x=undone.x + x0,
                y=undone.y + y0,
                w=undone.w,
                h=undone.h,
                panel_id=panel,
            )
            for undone in (
                unrotate_box(box, k, crop_h=crop_h, crop_w=crop_w) for box in in_crop
            )
        ]

        # Ratio AND error bar, from one pass over the same crop. A verdict
        # needs both: see `vision.measure.contrast.contrast_band`.
        band = contrast_band(oriented)

        lines.append(
            OcrLine(
                text=result.text,
                box=origin,
                confidence=result.confidence,
                script=script,  # type: ignore[arg-type]
                char_boxes=boxes,
                panel_id=panel,
                engine=f"ppocrv5-rec-{script}",
                cap_height_px=cap.cap_height_px if cap else None,
                numeral_box=numerals_of(result.text, boxes),
                numeral_height_px=numeral_height,
                contrast_ratio=None if band is None else band[0],
                contrast_tolerance=None if band is None else band[1],
                rotation_k=k,
            )
        )
        if not version:
            version = recognise.MODEL_FILENAMES.get(script) or ""  # type: ignore[arg-type]

    elapsed = (time.perf_counter() - started) * 1000.0
    return OcrResult(
        lines=lines,
        regions_proposed=len(keep) + len(skip),
        regions_read=len(lines),
        inference_ms=elapsed,
        model_version=version,
    )


def propose_lines(
    rectified: Image, *, mm_per_px: float | None = None
) -> tuple[list[TextRegion], float, str]:
    """Detect text and assemble it into printed lines. Returns (lines, ms, version).

    Split out from `run` so a caller can propose **once** and read twice. The
    escalation path in `vision.pipeline` needs exactly that: detection costs
    705 ms on a 3000 px label and recognition costs 38 ms a crop, so paying for
    detection again in order to read a few more regions would be the expensive
    half of a cheap decision.
    """
    proposals, detect_ms, detect_version = detect_text.propose_regions(
        rectified, mm_per_px=mm_per_px
    )
    # DBNet proposes words; the declarations are lines. Joining them before the
    # crop budget is applied is what makes eight crops enough -- and it is the
    # difference between handing the classifier `'MRP Rs.'` and `'10'`, which
    # declare nothing apiece, and handing it `'MRP Rs. 10'`. See vision.ocr.lines.
    #
    # And the mirror of it, in the same breath and for the same reason. Dense
    # coded print shrinks to one blob in DBNet's mask, so a block of five
    # declarations can arrive as a single region four lines tall -- which a
    # line recogniser returns as one stray character. `unstack` cuts those back
    # into lines before the budget is applied, so each one competes for a crop
    # on its own merits. See vision.ocr.rows.
    return rows.unstack(rectified, merge_into_lines(proposals)), detect_ms, detect_version


def run(
    rectified: Image,
    *,
    pdp_polygon: list[Point] | None = None,
    limit: int = MAX_REGIONS,
    mm_per_px: float | None = None,
) -> OcrResult:
    """Propose regions, then read only the chosen ones. The full M4 path.

    `mm_per_px` is the scale in *rectified* pixels, the same space the regions
    are in. It is optional because tier C never recovers one, and the ranking
    falls back to pixel height when it is absent.
    """
    regions, detect_ms, detect_version = propose_lines(rectified, mm_per_px=mm_per_px)
    result = read_regions(
        rectified, regions, pdp_polygon=pdp_polygon, limit=limit, mm_per_px=mm_per_px
    )
    return OcrResult(
        lines=result.lines,
        regions_proposed=result.regions_proposed,
        regions_read=result.regions_read,
        inference_ms=result.inference_ms + detect_ms,
        model_version=f"{detect_version}+{result.model_version}",
    )


def is_available() -> bool:
    return detect_text.is_available() and (
        recognise.is_available("latin") or recognise.is_available("devanagari")
    )


__all__ = [
    "CROP_PADDING",
    "MAX_REGIONS",
    "is_available",
    "rank_regions",
    "read_regions",
    "run",
]
