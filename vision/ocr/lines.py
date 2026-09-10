"""Putting a printed line back together before anyone tries to read it.

**DBNet proposes words, not lines, and nothing was joining them up.** On a dev
corpus pack the MRP arrives like this:

    x=167 y=585   65x36   'MRP Rs.'        x=275 y=597  160x32   '10'
    x=172 y=618   60x32   '(incl. of'      x=283 y=629  152x32   '100004'
    x=170 y=648   78x30   'all taxes) :'
    x=172 y=678   78x30   'Batch No.:'     x=282 y=673  157x31   '060924'

Every one of those was detected, cropped and recognised correctly. Then
`regex_tier` was handed `'MRP Rs.'` on its own, which declares nothing, and
`'10'` on its own, which is a number with no field, and both came back `other`.
The declaration was never missing. It was never assembled.

This is also why the eight-crop budget looked far tighter than it is. Reading
eight *fragments* covers a fifth of a label; reading eight *lines* covers most
of one, because the same forty proposals collapse to roughly fifteen lines.
Merging before recognition rather than after is deliberate for a second reason:
CTC reads `'MRP Rs. 10'` better than it reads `'10'` alone, and the cap height,
character boxes and contrast all then come from one consistent crop instead of
being stitched from several.

**Orientation is respected, not assumed.** A line of text running down the side
of a pack is a run of boxes stacked vertically, and merging it along x would
join it to whatever is printed beside it. Regions are grouped by orientation
first and each group merges along its own reading axis.

The two constants below were chosen on `data/corpus/`, by `bench/rank_recall.py`,
and never on the sealed test split.
"""

from __future__ import annotations

import statistics

from vision.types import Box, Point, TextRegion

GAP_RATIO = 1.5
"""Largest gap between two fragments of one line, in line heights.

Typographically a word space is about a third of an em and a wide label-to-value
gap in a set table runs to one or two, so this reaches across `MRP Rs. ___ 10`
without reaching into the next column. Swept over 0.5, 1.0, 1.5, 2.0 and 3.0 on
the dev corpus; see RESULTS.md for the curve, which is flat from 1.0 to 2.0 and
falls off at 3.0 as separate columns start to fuse.
"""

OVERLAP_FRAC = 0.45
"""How much of the shorter fragment must lie across the other, perpendicular to
the reading direction, before the two count as the same line.

Below a half because set type wanders: `'MRP Rs.'` spans y 585-621 and the `10`
beside it spans y 597-629, an overlap of 0.75 of the shorter -- but a fragment
that is all-lowercase next to one with capitals and a descender overlaps far
less than that, and refusing those would drop exactly the label-plus-value pairs
this exists to join.
"""

HEIGHT_RATIO = 2.0
"""Fragments of one line are set at one size, within reason. A cap-height run
next to an x-height run differs by about 1.4; anything past 2 is a different
piece of typography and joining them would produce a box that measures neither.
"""


def _horizontal(box: Box) -> bool:
    return box.w >= box.h


def _line_height(box: Box) -> float:
    """The minor axis, which is the size of the letters either way round."""
    return min(box.w, box.h)


def _overlaps(a: Box, b: Box, *, horizontal: bool) -> bool:
    """Do the two boxes lie across each other, perpendicular to the reading axis?"""
    if horizontal:
        lo, hi = max(a.y, b.y), min(a.y2, b.y2)
        shorter = min(a.h, b.h)
    else:
        lo, hi = max(a.x, b.x), min(a.x2, b.x2)
        shorter = min(a.w, b.w)
    if shorter <= 0:
        return False
    return (hi - lo) >= OVERLAP_FRAC * shorter


def _gap(a: Box, b: Box, *, horizontal: bool) -> float:
    """Distance along the reading axis. Negative when the two overlap."""
    if horizontal:
        return max(a.x, b.x) - min(a.x2, b.x2)
    return max(a.y, b.y) - min(a.y2, b.y2)


BACKTRACK_FRAC = 0.5
"""How far two fragments may overlap *along* the reading axis and still be one
line, as a fraction of line height.

This is the test that separates a line from its neighbour, and it took a bug to
find. Fragments of one line sit **beside** each other, so the gap between them
is positive. Two stacked lines sit **on top of** each other and share almost
their whole horizontal extent, so their gap along x is hugely negative -- on a
dev-corpus pack, -168 px for two lines 45 px tall. Perpendicular overlap alone
does not tell them apart: DBNet's boxes are loose enough that consecutive lines
overlapped vertically by 61%, comfortably past `OVERLAP_FRAC`, and merged into
a block of prose that measured nothing.

A small negative allowance remains because a box drawn around a leading capital
often starts just inside the previous fragment's.
"""


def _joins(a: Box, b: Box, *, horizontal: bool, gap_ratio: float) -> bool:
    ha, hb = _line_height(a), _line_height(b)
    if ha <= 0 or hb <= 0:
        return False
    if max(ha, hb) / min(ha, hb) > HEIGHT_RATIO:
        return False
    if not _overlaps(a, b, horizontal=horizontal):
        return False
    mean_height = (ha + hb) / 2.0
    gap = _gap(a, b, horizontal=horizontal)
    return -BACKTRACK_FRAC * mean_height <= gap <= gap_ratio * mean_height


def _union(boxes: list[Box]) -> Box:
    x0 = min(b.x for b in boxes)
    y0 = min(b.y for b in boxes)
    x1 = max(b.x2 for b in boxes)
    y1 = max(b.y2 for b in boxes)
    return Box(x=x0, y=y0, w=x1 - x0, h=y1 - y0, panel_id=boxes[0].panel_id)


def _merge_group(group: list[TextRegion], *, horizontal: bool, gap_ratio: float) -> list[TextRegion]:
    """Union-find over every pair that could be the same line.

    An earlier version sorted along the reading axis and chained neighbours in
    one pass, which is wrong the moment a label has two columns: sorting by x
    interleaves the left column's six lines with the right column's three, so
    `'MRP Rs.'` was compared against `'all taxes) :'` -- the next line down --
    rather than against the `'10'` printed beside it, and nothing merged at all.

    Quadratic, deliberately. A label proposes a couple of hundred regions at
    most, the test is a handful of comparisons, and correctness here is worth
    more than the microseconds an interval tree would save.
    """
    n = len(group)
    if n < 2:
        return list(group)

    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if _joins(group[i].box, group[j].box, horizontal=horizontal, gap_ratio=gap_ratio):
                parent[find(i)] = find(j)

    clusters: dict[int, list[TextRegion]] = {}
    for i, region in enumerate(group):
        clusters.setdefault(find(i), []).append(region)

    return [_collapse(parts) for parts in clusters.values()]


def _collapse(parts: list[TextRegion]) -> TextRegion:
    """One region standing for the whole line."""
    if len(parts) == 1:
        return parts[0]
    # The polygon is dropped rather than unioned: it described the shape of one
    # word, and a convex hull over several would claim a precision about the
    # line's outline that we no longer have. Nothing downstream requires it.
    polygon: list[Point] | None = None
    hints = {p.script_hint for p in parts if p.script_hint}
    return TextRegion(
        box=_union([p.box for p in parts]),
        # The median of the parts, not the union's minor axis. Fragments of one
        # line sit at slightly different heights, so the box that contains them
        # all is taller than the type in it -- by 29% on the pack above. The
        # ranking reads this as the size of the print, and overstating it pushes
        # a small declaration out of the band the statute cares about.
        line_height_px=statistics.median(_line_height(p.box) for p in parts),
        # The weakest link. A line is only as trustworthy as its least certain
        # fragment, and averaging would let one confident word carry three
        # doubtful ones into the crop budget.
        score=min(p.score for p in parts),
        polygon=polygon,
        script_hint=next(iter(hints)) if len(hints) == 1 else None,
    )


def merge_into_lines(
    regions: list[TextRegion], *, gap_ratio: float = GAP_RATIO
) -> list[TextRegion]:
    """Join word-level proposals into the printed lines they came from.

    Orientation-aware: horizontal fragments merge along x, vertical ones along
    y, and the two groups never merge into each other. `gap_ratio` is a
    parameter so `bench/rank_recall.py` can sweep it on the dev corpus; callers
    should leave it alone.
    """
    if len(regions) < 2:
        return list(regions)

    horizontal = [r for r in regions if _horizontal(r.box)]
    vertical = [r for r in regions if not _horizontal(r.box)]

    return _merge_group(horizontal, horizontal=True, gap_ratio=gap_ratio) + _merge_group(
        vertical, horizontal=False, gap_ratio=gap_ratio
    )


__all__ = ["GAP_RATIO", "HEIGHT_RATIO", "OVERLAP_FRAC", "merge_into_lines"]
