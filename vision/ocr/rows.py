"""A block of five printed lines is five regions, not one unreadable crop.

---------------------------------------------------------------------------
WHAT THIS EXISTS TO FIX
---------------------------------------------------------------------------
A face serum carton, scanned live on 2026-09-19. The declarations are printed
down the left of the panel and their values are inkjet-coded onto a white
label to the right:

    Batch No.:              B77A6571
    Mfg./Exp...             01/2026
    Use before:             01/2028
    MRP: Rs                 645.00
    USP per ml: Rs          21.50/ML

Every caption on the left was detected, read and classified correctly. The
coded block on the right came back as three regions, and this is what the
recogniser returned for them:

    x=1864 y=1677  616x385   ->  '['
    x=1966 y=1767  428x195   ->  'S2T'
    x=1939 y=1958  462x88    ->  '21.30M1'

The third is one line 88 px tall and it reads almost correctly. The first two
are **385 px and 195 px tall on a panel whose text lines run 62 to 107 px** --
four and two lines of print handed to a recogniser that reads one line. CTC
decodes along a single sequence; give it stacked rows and it returns a
character or two of noise.

So the officer was shown a pack with a batch caption and no batch, a price
caption and no price, and an expiry caption and no date -- and the rules,
correctly, reported the values missing. **Nothing downstream can recover
this.** Association cannot pair a value that was never read, and
`vision.ocr.split` un-welds a row that *was* read into its cells. This is the
case where the pixels never became text at all.

---------------------------------------------------------------------------
WHY THE DETECTOR PRODUCES A BLOCK
---------------------------------------------------------------------------
DBNet predicts a shrunken text mask and dilates it back. Dense small print at
tight leading -- which is exactly what a coding printer lays down -- shrinks to
one connected blob, and one blob is one region however many lines of type are
inside it. `vision.ocr.lines` cannot help: its whole job is joining fragments
*along* a line, and it has `BACKTRACK_FRAC` specifically to refuse stacking two
lines into one. It never saw two regions here. It saw one.

---------------------------------------------------------------------------
THE METHOD, AND WHY IT IS ARITHMETIC AND NOT A MODEL
---------------------------------------------------------------------------
Horizontal projection: count ink per row of the crop, and the gaps between
lines of type are the rows with no ink in them. It is the oldest trick in
document analysis and it is the right one here because the thing being found --
leading between lines -- is defined by the absence of ink, which a projection
measures directly.

Section 14: *rectification, scale and measurement -- trained? No, deterministic
geometry.* This is the same kind of thing and is held to the same standard: no
weights, no threshold fitted to a photograph, and a refusal rather than a guess
where the profile does not clearly separate.
"""

from __future__ import annotations

import cv2
import numpy as np

from vision.measure.cap_height import binarise
from vision.types import Box, Image, TextRegion

MULTILINE_RATIO = 2.2
"""How many median line heights tall a region must be before it is suspected of
holding more than one line.

A single line of type varies: a descender, a bracket or a rupee sign makes one
region half again as tall as its neighbours, and an assembled line's union box
is taller than any of its parts by design (`TextRegion.line_height_px` records
why). Two lines of the same type plus their leading is at least 2.2 of a line,
so this sits above the noise and below the thing being caught.

The reference is the median over the page's own regions rather than a constant
in millimetres. A projection is a statement about *this* crop, and the page it
came from already says what a line looks like on it."""

MIN_ROW_PX = 8
"""An ink band thinner than this is not a line of print. It is a rule, an
underline, the top of a barcode, or the dust the binariser kept."""

INK_FRACTION = 0.06
"""How much ink a row needs, as a fraction of the busiest row in the crop,
before it counts as part of a line rather than part of the gap.

Low on purpose. The test is meant to find *empty* leading, and the cost of
setting it high is cutting a line in half through the waist of its own
lower-case letters -- which produces two unreadable crops out of one readable
one, the opposite of the point."""

MAX_ROWS = 12
"""A region that appears to hold more than a dozen lines is not a block of
declarations; it is a paragraph, a nutrition table, or a binarisation that went
wrong. Splitting it would spend the whole crop budget in one place, so it is
left exactly as the detector proposed it."""

MIN_BAND_FRAC = 0.4
"""How tall a band must be against the page's own line height to count as a
line of print rather than a fragment.

**A projection measures ink, and a detector box measures ink plus padding**, so
a band is reliably shorter than the region it came from -- on the serum
sticker, 40 px of ink inside a 74 px line. Four tenths sits below that and
above the strays: a logo with a horizontal break in it, the bar above a
barcode, one accent floating over a block. Those were producing a band that
recognised as nothing, which costs a crop for no reading."""

MIN_GAP_PX = 3
"""Ink bands closer than this are one line. Below it the "gap" is the space
between a capital and the accent above the next line, not leading."""


def ink_bands(crop: Image) -> list[tuple[int, int]]:
    """Rows of ink in the crop, top to bottom, as half-open (top, bottom).

    Returns one band for an ordinary single line, which is how the caller knows
    there was nothing to do.
    """
    if crop is None or crop.size == 0:
        return []
    gray = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if gray.shape[0] < 2 * MIN_ROW_PX:
        return []

    binary, _ = binarise(gray)  # ink is white, whichever way the pack prints
    profile = (binary > 0).sum(axis=1).astype(np.float64)
    if profile.max() <= 0:
        return []

    inked = profile >= INK_FRACTION * profile.max()

    bands: list[list[int]] = []
    start: int | None = None
    for row, has_ink in enumerate(inked):
        if has_ink and start is None:
            start = row
        elif not has_ink and start is not None:
            bands.append([start, row])
            start = None
    if start is not None:
        bands.append([start, len(inked)])

    # Close the gaps that are not leading: an accent, a dotted i, a comma
    # hanging below the baseline.
    merged: list[list[int]] = []
    for band in bands:
        if merged and band[0] - merged[-1][1] < MIN_GAP_PX:
            merged[-1][1] = band[1]
        else:
            merged.append(band)

    return [(top, bottom) for top, bottom in merged if bottom - top >= MIN_ROW_PX]


LINE_ASPECT = 2.5
"""How many times wider than tall a region must be to vote on what a line
looks like on this page.

**The reference cannot be taken over every region, because the blocks are in
it.** On the serum carton the two stacked blocks are 616x385 and 428x195 -- 1.6
and 2.2 wide-to-tall -- and including them in the median pulls the yardstick up
towards the very thing it is meant to measure against. The captions on the same
panel run 2.8 to 9.3, so a threshold between the two separates them cleanly.

A line of print is wide. That is what a line is."""


def _median_line_height(regions: list[TextRegion]) -> float:
    def height(region: TextRegion) -> float:
        return region.line_height_px or min(region.box.w, region.box.h)

    line_shaped = [
        height(r)
        for r in regions
        if r.box.h > 0 and r.box.w / r.box.h >= LINE_ASPECT and height(r) > 0
    ]
    if line_shaped:
        return float(np.median(line_shaped))

    # Nothing on the page is line-shaped. Either it is all vertical text or the
    # detector has proposed nothing but blocks, and in both cases there is no
    # yardstick here worth trusting -- so decline rather than invent one.
    return 0.0


def _rows_of(image: Image, region: TextRegion, reference: float) -> list[TextRegion] | None:
    """The lines inside one region, or None if it holds a single line.

    None rather than `[region]` so the caller can tell "nothing to do" from "it
    split into one", which are different statements about the same region.
    """
    box = region.box
    if box.w < box.h:
        # Text running down the side of a pack is one line and it is tall. The
        # projection would cut it into its own characters.
        return None
    if reference <= 0 or box.h < MULTILINE_RATIO * reference:
        return None

    x0, y0 = int(max(0, box.x)), int(max(0, box.y))
    x1, y1 = int(min(image.shape[1], box.x2)), int(min(image.shape[0], box.y2))
    if x1 - x0 < 1 or y1 - y0 < 2 * MIN_ROW_PX:
        return None

    bands = ink_bands(image[y0:y1, x0:x1])
    bands = [b for b in bands if (b[1] - b[0]) >= MIN_BAND_FRAC * reference]
    if len(bands) < 2 or len(bands) > MAX_ROWS:
        return None

    rows: list[TextRegion] = []
    for top, bottom in bands:
        height = float(bottom - top)
        rows.append(
            TextRegion(
                box=Box(x=float(x0), y=float(y0 + top), w=float(x1 - x0), h=height),
                score=region.score,
                # `polygon` describes the whole block and would place a row
                # where it is not. `line_height_px` is now the band itself,
                # which is a better answer than the median the block carried.
                polygon=None,
                script_hint=region.script_hint,
                line_height_px=height,
            )
        )
    return rows


def unstack(image: Image, regions: list[TextRegion]) -> list[TextRegion]:
    """Replace every multi-line block with the lines inside it.

    Runs before the crop budget is applied, deliberately: a block holding the
    batch number, the expiry and the price should compete for crops as three
    declarations, not lose one crop as a single unreadable region -- and on the
    carton that prompted this, the one region the budget did spend on the block
    returned a single left bracket.
    """
    reference = _median_line_height(regions)
    if reference <= 0:
        return regions

    out: list[TextRegion] = []
    for region in regions:
        rows = _rows_of(image, region, reference)
        out.extend(rows if rows is not None else [region])
    return out


__all__ = [
    "INK_FRACTION",
    "MAX_ROWS",
    "MIN_GAP_PX",
    "MIN_ROW_PX",
    "MULTILINE_RATIO",
    "ink_bands",
    "unstack",
]
