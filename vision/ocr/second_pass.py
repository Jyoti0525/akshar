"""B7 — read the doubtful lines again, from the photograph. AKSHAR.md section 8b.

    "B7 two-pass recognition — low-confidence crops re-cropped from **original
     full-resolution pixels** and re-read."

**What the second pass actually buys, stated honestly, because it is not more
pixels.** The first pass reads a crop that has been resampled three times:
`warpPerspective` flattens the whole frame, `_crop` cuts a padded rectangle out
of the result, `orientations` may rotate it, and the recogniser then resizes it
to the head's input height. Each resampling is an interpolation, and
interpolations compound — a 14-pixel line of print that survives one is mush
after three. This pass goes back to the photograph and performs **one** warp,
straight from the original pixels to the geometry the head wants.

Where the rectified image was also capped (`_MAX_WARP_SIDE`, 3000 px) there is
genuine resolution to recover as well. Where it was not, the gain is the
interpolation chain alone, and that is still the difference between an `8` and
a `3` on a small MRP.

---------------------------------------------------------------------------
THREE RULES, AND THE SECOND ONE IS THE IMPORTANT ONE
---------------------------------------------------------------------------

**1. It can only improve a line — and "improve" is not "score higher".** This is
where the first version of this module was wrong, and the corpus caught it.
`ctc_decode` sets `confidence` to the *mean* of the kept per-step scores, so a
decoder that drops the characters it finds hardest returns a **better score for
a worse reading**. Accepting on confidence alone turned `' c.N 1310010409'` into
`'  No 130029'` and called it a gain. A second reading is therefore kept only
when it is **no shorter** than the first and wins by `MIN_CONFIDENCE_GAIN`. See
`_is_an_improvement`.

**2. It replaces the text, never the geometry.** `cap_height_px`, `numeral_box`,
`char_boxes` and `box` all stay exactly as the first pass measured them.

The temptation is obvious and it is a trap. The re-cropped image has more pixels,
so a cap height measured on it would be more precise — but it is measured *in a
different pixel scale*, and `mm_per_px` is calibrated against rectified space.
Carrying a measurement from one scale into the other requires a division that
`vision/types.py` already names *"the single most dangerous unit slip in the
project"*. A more precise number in the wrong units is worse than a coarser one
in the right units, and the measurement is what an officer puts on a notice.
So the second pass is about **recognition** and nothing else, which is also all
section 8b asks of it.

**3. It is bounded.** Section 4 gives the whole scan 561 ms. At most
`MAX_REREADS` lines are revisited, chosen worst-confidence-first, so a label
that was entirely unreadable does not spend a minute proving it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from vision.types import Image, OcrLine, Transform

ENABLED = False
"""**Off in the scan path, on the evidence available. Measured, not assumed.**

The module works, is guarded both ways, and has 21 tests. What it does not have
is a reason to cost an officer their time, and that is a separate question which
only a labelled set can answer. Both answers, taken 2026-09-18:

*On the 38 hand-labelled declaration panels — the only ground truth this project
has — it changes **nothing**.* The bench was run twice, back to back, with this
pass on and off. Presence micro F1 0.7506 both times; every per-field precision
and recall identical; every value-accuracy count identical (mrp 19/38,
net_quantity 25/34, mfg_date 14/32). The two bench JSONs differ in their timing
fields and in nothing else.

*And it is not free.* Timed in isolation over those panels: **median 0.2 ms**,
because on most scans no line falls below `LOW_CONFIDENCE` and the pass never
starts — but it fired on **4 of 14** frames, and when it fires it costs **336 ms
on average and up to 953 ms**. Section 4 budgets the whole scan at 561 ms.

*On the unlabelled corpus it fires, and what it produces cannot be adjudicated.*
Over 70 frames and 1,915 lines: 237 below threshold, 144 re-read after the
budget, 13 confidences improved, **11 texts changed**. Some are plainly right —
`'[014814'` at 0.76 became `'1014814'` at 0.90, a bracket correctly re-read as
the leading digit of a licence number; `'6'` became `'760'`; `'A='` at 0.19
became `'59.82'` at 0.64. At least one is plainly wrong: `'THORN'` became
`'THDEA'`. The rest cannot be called either way, **because the corpus carries no
ground truth** — which is the whole reason the 38 labelled panels exist, and on
those it changed nothing.

So: a third of scans paying a third of a second, for eleven changes in two
thousand lines that nobody can score. That is not a trade to make quietly. Flip
this to `True` when there is evidence to justify it. **The evidence that would
settle it is the set the project is already waiting for**: the 38 panels are
close-ups whose rectification barely resamples, which is precisely where this
pass has least to offer, and full-resolution photographs of *angled* declaration
blocks would put these eleven changes on a measured footing either way.
"""

LOW_CONFIDENCE = 0.80
"""Below this, a line is worth a second look.

Not tuned against `data/test_split/`, which is sealed. It is set where the
recogniser's own score stops being a useful discriminator: PP-OCR's CTC
confidence clusters hard above 0.9 on clean print, and the interesting failures
— a digit misread on a small MRP, a letter dropped from an address — sit in the
0.5-0.85 band. A line below ~0.3 is usually not text at all and rereading rarely
rescues it, but it is left in rather than excluded, because "usually" is not a
reason to refuse to look and the budget below already bounds the cost."""

MAX_REREADS = 12
"""At most this many lines get a second pass, worst first.

A budget rather than a fraction: a label with 60 doubtful lines is a label the
scan is going to report as partly unread whatever happens, and spending 60 warps
to confirm that costs the officer time they are standing in a shop to spend."""

MIN_CONFIDENCE_GAIN = 0.10
"""How much better a second reading has to be before it is believed.

Not a tuning knob for accuracy — a guard against a metric that can be gamed by
reading *less*. See `_is_an_improvement`: CTC confidence is the mean of the kept
per-step scores, so dropping the hardest characters raises it. A margin this
wide costs a few genuine small gains and buys immunity from every reading that
improved its average by saying less."""

MODEL_HEIGHT_PX = 48
"""`recognise.REC_HEIGHT`. The crop is delivered at exactly this height so the
recogniser's own resize is a no-op, which is the whole point of going back to
the photograph: land on the head's input geometry rather than arrive there
through a third interpolation."""

MAX_CROP_PIXELS = 12_000_000
"""Refuse to allocate a warp larger than this. A homography fitted to a small
marker can map a line box onto most of a 12-megapixel frame; the cap turns a
pathological geometry into a skipped line rather than a memory spike."""


@dataclass(frozen=True, slots=True)
class SecondPassReport:
    """What the pass did. Reported rather than inferred from the lines."""

    considered: int
    """Lines whose first-pass confidence was below `LOW_CONFIDENCE`."""

    reread: int
    """Lines actually re-cropped and re-read, after the budget."""

    improved: int
    """Lines where the second reading was more confident and was kept."""

    changed_text: int
    """Of those, how many now say something different. An improvement that does
    not change the text is a confidence gain and nothing more, and conflating
    the two would overstate what this pass achieves."""

    elapsed_ms: float = 0.0

    @property
    def ran(self) -> bool:
        return self.reread > 0


def _native_size(quad) -> tuple[int, int]:
    """The quad's own size in original pixels, so the warp neither invents
    detail nor throws any away.

    Warping straight to the recogniser's 48 px input would be a single large
    downsample through `warpPerspective`, which offers no area filter and
    therefore aliases — small print turns to moiré and the reading gets *worse*,
    which is how the first version of this module lost to the pass it was
    supposed to improve on. Resample at native density here; `_to_model_height`
    does the reduction afterwards with a filter that has an area mode.
    """
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = quad
    width = max(np.hypot(x1 - x0, y1 - y0), np.hypot(x2 - x3, y2 - y3))
    height = max(np.hypot(x3 - x0, y3 - y0), np.hypot(x2 - x1, y2 - y1))
    return max(round(width), 1), max(round(height), 1)


def _to_model_height(crop: Image) -> Image:
    """Land the crop on the head's input height, with the right filter.

    `INTER_AREA` going down (it integrates over the source pixels, so a 300 px
    line reduced to 48 keeps its stroke weight instead of sampling every sixth
    row), `INTER_CUBIC` going up. Using one filter for both directions is the
    commonest way to lose small print.
    """
    import cv2

    height, width = crop.shape[:2]
    if height <= 0 or width <= 0 or height == MODEL_HEIGHT_PX:
        return crop
    scale = MODEL_HEIGHT_PX / height
    target = (max(round(width * scale), 1), MODEL_HEIGHT_PX)
    mode = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(crop, target, interpolation=mode)


def _recrop(original: Image, transform: Transform, line: OcrLine, pad: float) -> Image | None:
    """Back to the photograph, for the pixels of one line.

    The padding is applied in *rectified* space before mapping back, so a
    slanted line gets a slanted margin rather than an axis-aligned one that
    would clip its own ascenders on one side and swallow the next line on the
    other.
    """
    import cv2

    from contracts import Box

    margin = max(2.0, min(line.box.w, line.box.h) * pad)
    padded = Box(
        x=line.box.x - margin,
        y=line.box.y - margin,
        w=line.box.w + 2 * margin,
        h=line.box.h + 2 * margin,
    )
    quad = transform.box_to_original(padded)
    if quad is None:
        return None

    height, width = original.shape[:2]
    if all(x < 0 or y < 0 or x > width or y > height for x, y in quad):
        # Every corner outside the photograph: this line came from a region the
        # warp invented, and there are no original pixels to go back to.
        return None

    out_w, out_h = _native_size(quad)
    if out_w * out_h > MAX_CROP_PIXELS:
        return None
    source = np.asarray(quad, dtype=np.float32)
    destination = np.array(
        [[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]],
        dtype=np.float32,
    )
    try:
        matrix = cv2.getPerspectiveTransform(source, destination)
        warped = cv2.warpPerspective(original, matrix, (out_w, out_h), flags=cv2.INTER_CUBIC)
    except cv2.error:  # pragma: no cover - degenerate quad
        return None
    return _to_model_height(warped)


def _is_an_improvement(before: OcrLine, text: str, confidence: float) -> bool:
    """Is this second reading better, or just shorter?

    **The question the first version of this module got wrong.** `ctc_decode`
    computes `confidence` as the *mean* of the kept per-step scores, so a
    decoder that drops the characters it finds hardest comes back with a
    **higher** score for a worse reading. Measured on 20 corpus frames, that
    rule accepted `'Ske Inernatonal: B-57, Lawrence Ro'` -> `'SkeInterationat:
    -57Lence Rod'` on a gain of 0.01, and `' c.N 1310010409'` -> `'  No 130029'`
    — losing four digits of a licence number and calling it an improvement.

    So two conditions, and the first is the one that matters:

      - **It may not be shorter.** Characters dropped are evidence dropped, and
        the confidence metric actively rewards dropping them.
      - **It must win decisively.** A gain of 0.01 on a mean of a dozen softmax
        scores is noise; `MIN_CONFIDENCE_GAIN` is what separates a better
        reading from a differently-rounded one.
    """
    new = text.strip()
    old = before.text.strip()
    if not new:
        return False
    if len(new) < len(old):
        return False
    return confidence >= before.confidence + MIN_CONFIDENCE_GAIN


def reread(
    original: Image | None,
    transform: Transform | None,
    lines: list[OcrLine],
    *,
    threshold: float = LOW_CONFIDENCE,
    budget: int = MAX_REREADS,
    pad: float = 0.12,
) -> tuple[list[OcrLine], SecondPassReport]:
    """Return the lines, with doubtful ones re-read where that helped.

    Never raises and never degrades a reading. Every reason it cannot run — no
    photograph, no transform, a transform that is the identity, no recognition
    head — returns the lines exactly as given, with a report saying nothing
    happened.
    """
    empty = SecondPassReport(considered=0, reread=0, improved=0, changed_text=0)
    if original is None or transform is None or not lines:
        return lines, empty

    # An identity transform means the rectified image *is* the photograph. The
    # crop would come from the same pixels through the same interpolations, so
    # there is nothing to gain and a budget to waste.
    if transform.is_identity:
        return lines, empty

    from vision.ocr import recognise

    if not recognise.is_available():
        return lines, empty

    doubtful = [index for index, line in enumerate(lines) if line.confidence < threshold]
    doubtful.sort(key=lambda index: lines[index].confidence)
    chosen = doubtful[:budget]
    if not chosen:
        return lines, SecondPassReport(
            considered=len(doubtful), reread=0, improved=0, changed_text=0
        )

    started = time.perf_counter()
    out = list(lines)
    improved = 0
    changed = 0
    attempted = 0

    for index in chosen:
        line = lines[index]
        crop = _recrop(original, transform, line, pad)
        if crop is None or crop.size == 0:
            continue
        attempted += 1
        try:
            second = recognise.recognise(crop, line.script)
        except Exception:
            continue

        if not _is_an_improvement(line, second.text, second.confidence):
            continue

        improved += 1
        if second.text != line.text:
            changed += 1
        # Text, confidence and engine only. Everything geometric is the first
        # pass's, measured in the space `mm_per_px` is calibrated against.
        out[index] = replace_reading(line, second.text, second.confidence)

    return out, SecondPassReport(
        considered=len(doubtful),
        reread=attempted,
        improved=improved,
        changed_text=changed,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
    )


def replace_reading(line: OcrLine, text: str, confidence: float) -> OcrLine:
    """A copy of `line` saying something new, in the same place.

    Written out as its own function so the list of what a second pass may touch
    is a list somebody can read. `char_boxes` in particular stays: `roi.py`
    segmented them from the ink of the first crop and carried them back into
    rectified space, and Rule 7(3)'s width ratio is measured from them there.
    Re-segmenting the new crop would produce boxes in a third pixel scale and a
    width ratio that no longer matches the line it describes.

    `is_available` is checked against latin only in `reread`, deliberately: the
    Devanagari head is a separate file and may be absent while latin is present,
    and `recognise` raises `ModelUnavailableError` for the missing one, which
    the caller catches and treats as "no improvement" like any other.
    """
    from dataclasses import replace as _replace

    engine = line.engine if line.engine.endswith("+2pass") else f"{line.engine}+2pass"
    return _replace(line, text=text, confidence=confidence, engine=engine)


__all__ = [
    "ENABLED",
    "LOW_CONFIDENCE",
    "MAX_REREADS",
    "MIN_CONFIDENCE_GAIN",
    "SecondPassReport",
    "reread",
]
