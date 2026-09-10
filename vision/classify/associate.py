"""A label and its figure, printed as two regions, are one declaration.

The detector proposes words. On `bodywash_bottle_300ml` it proposed the price
label and the price as separate regions, and the pipeline read both of them:

    (2171, 1591, 28, 24)   'o'        <- the MRP label, badly read
    (2297, 1597, 145, 42)  '449.00'   <- the price, at confidence 0.97

`449.00` on its own matches no locate pattern in the rulepack, and rightly so:
a bare number is a batch code as often as it is a price. So it was classified
`other`, the pack was reported as declaring no retail sale price, and the
number we needed was sitting in the output the whole time. Across the ruler set
this is not an edge case -- it is the commonest way a declaration is lost.

**Why this is not more line merging.** `vision.ocr.lines` merges *regions*
before they are read, and it must stay conservative: merging two lines of body
copy produces one crop with the height of a paragraph, which measures nothing
and reads as nonsense. It joins fragments a printer set as one line. What is
missing here is different -- a label and its value, often with a colon and a
wide gap between them, sometimes in different sizes -- and the right time to
join those is *after* reading, when we know what each fragment says. A gap
ratio wide enough to catch them before reading would sweep in the marketing
copy beside them.

**The value keeps its own pixels.** The declaration that comes out is measured
on the figure's region and not on the union of the two, because Rule 7(2) and
Rule 9 measure the numerals. Joining the boxes first would hand the height
rules a box spanning the label, the gap and the figure, which is exactly the
overstatement `vision.ocr.lines` computes `line_height_px` to avoid.

**It routes; the rulepack still decides.** What comes out is a declaration
whose text is the two fragments joined, so the rulepack's format patterns judge
`'MRP Rs. 449.00'` on its merits and can still fail it. The association is
reported in the guess's reason, naming both fragments, so an officer disputing
the reading sees exactly which two regions were joined and why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from contracts import FieldName
from vision.classify.regex_tier import FieldGuess
from vision.ocr.lines import _gap, _horizontal, _line_height, _overlaps
from vision.types import Box, OcrLine

ASSOCIABLE: dict[FieldName, re.Pattern[str]] = {
    "mrp": re.compile(r"(?<![\d.])\d{1,5}(?:[.,]\d{1,2})?(?![\d.])"),
    "net_quantity": re.compile(r"(?i)(?<![\d.])\d{1,5}(?:[.,]\d{1,3})?(?![\d.])"),
}
"""Fields routinely set as a label beside a figure, and what their figure
looks like.

Only these two, for the same reason `MEASURED_ON_NUMERALS` holds only these
two: they are the fields whose statutory requirement attaches to a *number*, so
"the value is missing from this line" is a question with an answer. A
manufacturer's address has no numeric form to look for, and an address split
across two regions is a job for the layout head, not for this.

The patterns are loose on purpose. They are never asked *"is this a price?"* --
that question, asked of a bare number, has no honest answer. They are asked
"does this fragment carry a figure at all", and the claim that the figure
belongs to the label rests on the label sitting next to it, which is checked
geometrically below.
"""

GAP_RATIO = 4.0
"""How far from its label a figure may sit, in multiples of the label's height.

Wider than `vision.ocr.lines.GAP_RATIO` (1.5) and deliberately so: that
constant governs merging *before* reading, where a generous gap sweeps
marketing copy into a declaration's crop and costs the reading. Here both
fragments have already been read and the value fragment has already been shown
to carry a figure, so distance is the last check rather than the only one.

Four is drawn from the layout it exists for. A label/value pair on a pack is
set with the value flush to a column edge -- the label at x 2199 and `449.00`
at x 2297 on `bodywash_bottle_300ml`, a 98 px gap on 33 px type, ratio 3.0 --
and the tabular gap between a label and its own column is the widest gap that
still belongs to one declaration.
"""

STACK_ALIGN_FRAC = 0.5
"""How much of the narrower box must lie within the wider one's span for a
figure printed *underneath* its label to count as belonging to it.

A label over its value is an ordinary packaging layout and has to be caught,
but the line under a label is also just the next line of whatever else is
printed there. Requiring half of the narrower fragment to sit inside the wider
one's span is what separates a value set under its label from the paragraph
that happens to follow it.
"""

BESIDE_BACKTRACK_FRAC = 0.25
"""How far a figure may overlap its label along the reading axis and still be
counted as printed beside it. See `_beside`."""

STACK_GAP_RATIO = 1.5
"""Line spacing a stacked pair may be separated by. Two lines down is a
different declaration, or somebody else's."""


@dataclass(frozen=True, slots=True)
class Association:
    """One label region and the value region it belongs to."""

    label: int
    value: int
    field: FieldName
    reason: str


def _carries_value(text: str, field: FieldName) -> bool:
    pattern = ASSOCIABLE.get(field)
    return bool(pattern and pattern.search(text))


def _stacked(label: Box, value: Box) -> bool:
    """Is `value` printed directly under (or over) `label`, and aligned to it?"""
    if _horizontal(label) != _horizontal(value):
        return False
    horizontal = _horizontal(label)
    # "Under" along the reading axis means overlapping *across* it, which is
    # the opposite of what `_overlaps` tests for two fragments of one line, so
    # the flag is inverted for both questions asked here.
    if not _overlaps(label, value, horizontal=not horizontal):
        return False

    if horizontal:
        span = min(label.x2, value.x2) - max(label.x, value.x)
        narrower = min(label.w, value.w)
    else:
        span = min(label.y2, value.y2) - max(label.y, value.y)
        narrower = min(label.h, value.h)
    if narrower <= 0 or span < narrower * STACK_ALIGN_FRAC:
        return False

    height = max(_line_height(label), _line_height(value))
    return abs(_gap(label, value, horizontal=not horizontal)) <= height * STACK_GAP_RATIO


def _beside(label: Box, value: Box) -> bool:
    """Is `value` printed on the same line as `label`, to its left or right?"""
    if _horizontal(label) != _horizontal(value):
        return False
    horizontal = _horizontal(label)
    if not _overlaps(label, value, horizontal=horizontal):
        return False
    height = max(_line_height(label), _line_height(value))
    if height <= 0:
        return False
    gap = _gap(label, value, horizontal=horizontal)
    # A little overlap is the detector's boxes touching, not a relationship:
    # DBNet pads its proposals and a label and the figure beside it routinely
    # come back a few pixels into each other. Past a quarter of a line height,
    # though, one fragment is inside the other rather than beside it, and that
    # is not a label/value pair.
    return -height * BESIDE_BACKTRACK_FRAC <= gap <= height * GAP_RATIO


def _distance(a: Box, b: Box) -> float:
    return abs(a.cx - b.cx) + abs(a.cy - b.cy)


def associate(lines: list[OcrLine], guesses: list[FieldGuess]) -> list[Association]:
    """Pair each value-less field label with the nearest figure beside it.

    Only lines the classifier left as `other` are eligible as values, so this
    never takes a declaration away from a field that claimed one outright. Each
    label takes at most one value and each value serves at most one label; the
    nearer fragment wins, and ties break on index so that two runs over one
    photograph agree.
    """
    taken: set[int] = set()
    found: list[Association] = []

    for i, (line, guess) in enumerate(zip(lines, guesses, strict=True)):
        if guess.field not in ASSOCIABLE:
            continue
        if _carries_value(line.text, guess.field):
            continue  # the figure is already on this line; nothing to join

        candidates = [
            j
            for j, other in enumerate(lines)
            if j != i
            and j not in taken
            and guesses[j].field == "other"
            and other.rotation_k == line.rotation_k
            and _carries_value(other.text, guess.field)
            and (_beside(line.box, other.box) or _stacked(line.box, other.box))
        ]
        if not candidates:
            continue

        best = min(candidates, key=lambda j: (_distance(line.box, lines[j].box), j))
        taken.add(best)
        found.append(
            Association(
                label=i,
                value=best,
                field=guess.field,
                reason=(
                    f"{guess.field} label {line.text.strip()!r} was read as its own "
                    f"region; the figure {lines[best].text.strip()!r} is printed "
                    f"beside it and carries no field label of its own"
                ),
            )
        )

    return found


__all__ = [
    "ASSOCIABLE",
    "BESIDE_BACKTRACK_FRAC",
    "GAP_RATIO",
    "STACK_ALIGN_FRAC",
    "STACK_GAP_RATIO",
    "Association",
    "associate",
]
