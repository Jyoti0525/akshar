"""An address is a declaration, not a caption. Join a block to its first line.

---------------------------------------------------------------------------
WHAT THIS EXISTS TO FIX
---------------------------------------------------------------------------
Rule 6(1)(a) requires "the name and address of the manufacturer". On a pack that
is six printed lines:

    MANUFACTURED BY: OMEGA INCENSE, 23, VAISHNODEVI
    INDUSTRIAL ESTATE,
    BHEEMANAHALLI, BIDADI HOBLI,
    RAMANAGAR - 562109,
    KARNATAKA, INDIA.

The detector returns six regions and the recogniser reads all six, at 0.97
confidence. Only the first carries the words `MANUFACTURED BY`, so only the
first is classified `manufacturer` — and **the address itself, which is the
declaration the rule is about, lands in `other` and never reaches a rule.**

Measured over the 38 hand-labelled panels on 2026-09-10: of 1,041 lines read,
845 were `other`. **205 of those are the body of a declaration whose first line
we had already named** — 114 manufacturer lines and 91 consumer-care lines. That
is the single largest recoverable population in the bucket, and none of it is an
OCR failure: the median recognition confidence on those lines is 0.95.

The consumer-care consequence is the sharper one. Rule 6(2) wants a contact, and
the rulepack looks for a telephone number in the declaration. The caption line
reads `For feedback, please contact the Consumer Care Executive at the` and the
number is two lines below it, in `other`. The pack declared a helpline; we
reported it had none.

---------------------------------------------------------------------------
ONLY ADDRESSES, AND ONLY DOWNWARD
---------------------------------------------------------------------------
This runs for the four fields whose value is prose that wraps: manufacturer,
packer, importer and consumer care. It deliberately does **not** run for `mrp`,
`net_quantity` or the dates. Those are a caption and a single value, the line
below them is the next declaration in the table, and joining there would merge
two declarations into one — which is what `vision.classify.associate` is for,
sideways and one value at a time.

A block ends at the first line that fails any test, and the tests are all local:
a line too far below the last one, a line not aligned with it, a line the
classifier has already named as some other declaration, or the eighth line. A
declaration cannot run away with the panel.

---------------------------------------------------------------------------
THE BOX GROWS; THE MEASUREMENT DOES NOT
---------------------------------------------------------------------------
Same contract as `_joined_line`, for the same reason. The merged declaration's
`box` is the union, because that is where the declaration is printed and it is
what `same_panel` and `clear_space` ask about — and it is what the annotated
evidence image draws, so an officer sees one rectangle round the whole address
instead of one round its first line.

Every measured pixel still comes from the anchor: `cap_height_px`,
`numeral_box`, `numeral_height_px` and `contrast_ratio` are the first line's.
Rule 7 measures glyphs, and the glyphs of a six-line block have no single
height. Taking the union's height would report an address as 40 mm tall.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from contracts import FieldName
from vision.classify.regex_tier import FieldGuess
from vision.types import Box, OcrLine

MULTILINE_FIELDS: frozenset[FieldName] = frozenset(
    {"manufacturer", "packer", "importer", "consumer_care"}
)
"""Fields whose declared value is an address or a contact block.

Rule 6(1)(a)'s name-and-address and Rule 6(2)'s consumer care. Every other
declaration in the rulepack is a caption and one value on one line."""

MAX_LINES = 8
"""How many lines a block may run to.

An Indian manufacturer's address is four to six lines; `santoor1.jpg` lists ten
alternative units keyed by a letter of the batch code and runs to fourteen. Eight
is past the ordinary case and short of the pathological one: the cost of
stopping early is a partial address, which still satisfies the rule, and the cost
of running on is swallowing the ingredients list below it."""

LINE_GAP_RATIO = 1.8
"""Vertical gap allowed between one line of a block and the next, in line
heights. Ordinary leading is well under 1.0; a gap of two full lines is a
paragraph break, and on a declaration panel a paragraph break is a new
declaration."""

ALIGN_FRAC = 0.5
"""How much of the narrower line must sit within the wider one's span.

An address block is set flush to one margin, so consecutive lines overlap
heavily. Half is generous enough for a short last line — `KARNATAKA, INDIA.` under a
full-width line — and mean enough to refuse a neighbouring column. It was a
third until `parleg.jpg` walked a consumer-care block into the nutrition table
beside it."""

_HAS_WORDS = re.compile(r"[A-Za-zऀ-ॿ]{3,}")
"""A continuation of an address contains words. This refuses a bare number, a
barcode and a one-character fragment, none of which is part of a name and
address even when it happens to sit underneath one."""

_ENDS_BLOCK = re.compile(
    r"(?i)\b(nutrition\w*|nutritional|energy|protein|carbohydrate|sugars?|"
    r"total\s*fat|saturated|trans\s*fat|cholesterol|sodium|serving\s*size|"
    r"kcal|rda|ingredients?|emulsifier|preservative|antioxidant|raising\s*agent|"
    r"allergen|contains\s+(wheat|milk|soy)|store\s+in|storage\s*condition|"
    r"keep\s+(in|away|under|refrigerat)|best\s*before|directions?\s*for\s*use)\b"
)
"""Vocabulary that is never part of a name and address, and ends the block.

Geometry alone was not enough. On `parleg.jpg` the consumer-care block sat
directly above the nutrition panel, the two are set to a shared margin, and the
walk continued straight into it — producing a `consumer_care` declaration
reading `CONSUMER CARE CELL NUTRITION FACTS/INFORMATION AMOUNT PER 100g 453
kcal`. That is not a false accusation, but it is evidence an officer would be
embarrassed to show, and it puts a nutrition table inside the text a locate
pattern searches.

An address contains a company, a street and a pin code. It does not contain the
word `ENERGY`, and the first line that does is the start of something else.
"""


@dataclass(frozen=True, slots=True)
class Continuation:
    """One line of a block, and the declaration line it continues."""

    line: int
    anchor: int
    field: FieldName


def _continues(cursor: Box, candidate: Box) -> bool:
    """Is `candidate` the next line of the block `cursor` belongs to?"""
    height = max(cursor.h, candidate.h)
    if height <= 0:
        return False

    gap = candidate.y - cursor.y2
    if gap < -height or gap > height * LINE_GAP_RATIO:
        return False

    span = min(cursor.x2, candidate.x2) - max(cursor.x, candidate.x)
    narrower = min(cursor.w, candidate.w)
    return narrower > 0 and span >= narrower * ALIGN_FRAC


def find(
    lines: list[OcrLine],
    guesses: list[FieldGuess],
    *,
    reserved: frozenset[int] = frozenset(),
) -> list[Continuation]:
    """Every unclassified line that is the body of a named declaration.

    Anchors are taken in reading order and each line is claimed at most once, so
    two address blocks printed one above the other do not both claim the line
    between them. The nearer anchor — the one above — wins, which is the one the
    line is actually part of.

    `reserved` names lines another step has already spoken for. It carries the
    values `vision.classify.associate` has paired with their labels: a price
    sitting under a consumer-care block is geometrically a continuation of it and
    is in fact the MRP, and without this the block swallowed it and the pack lost
    its price. Association is the stronger claim — it rests on a pattern match as
    well as on adjacency — so it is resolved first and this defers to it.

    **The block ends at the line below it, not at the next named line anywhere.**
    An earlier draft broke out of the walk on the first classified line it met in
    reading order, wherever it sat on the panel, which ended most blocks after
    one line. The test has to be local: a named line stops the block only when it
    is the line the block would have continued into.
    """
    order = sorted(range(len(lines)), key=lambda i: (lines[i].box.y, lines[i].box.x))
    claimed: set[int] = set()
    found: list[Continuation] = []

    for anchor in order:
        field = guesses[anchor].field
        if field not in MULTILINE_FIELDS or anchor in reserved:
            continue

        cursor = lines[anchor].box
        taken = 0
        for index in order:
            if taken >= MAX_LINES:
                break
            if index == anchor or index in claimed:
                continue
            if lines[index].box.y <= cursor.y:
                continue  # above the cursor: not a continuation of it
            if lines[index].rotation_k != lines[anchor].rotation_k:
                continue
            if not _continues(cursor, lines[index].box):
                continue  # not the next line of this block; look further down

            # From here the line IS the next line of the block, so what it is
            # decides whether the block goes on or ends here.
            if guesses[index].field != "other" or index in reserved:
                break  # the next declaration has started
            if not _HAS_WORDS.search(lines[index].text):
                break  # a bare number or a barcode ends an address
            if _ENDS_BLOCK.search(lines[index].text):
                break  # the nutrition panel, the ingredients, the storage note

            claimed.add(index)
            found.append(Continuation(line=index, anchor=anchor, field=field))
            cursor = lines[index].box
            taken += 1

    return found


def merge(anchor: OcrLine, body: list[OcrLine]) -> OcrLine:
    """The anchor line with its block's text appended and its box grown.

    `char_boxes` are concatenated with a real box for each joining space when
    every part was segmented, and dropped otherwise — the same positional
    contract `_joined_line` keeps, for the same reason: `min_width_ratio` walks
    them against `text`, and a list describing only the first line would compare
    every later character against the wrong glyph.
    """
    if not body:
        return anchor

    parts = [anchor, *body]
    text = " ".join(p.text.strip() for p in parts if p.text.strip())

    boxes: list[Box] = []
    if all(p.char_boxes and len(p.char_boxes) == len(p.text) for p in parts):
        for i, part in enumerate(parts):
            if i:
                last = boxes[-1]
                boxes.append(Box(x=last.x2, y=last.y, w=1.0, h=1.0, panel_id=last.panel_id))
            boxes.extend(part.char_boxes)

    x0 = min(p.box.x for p in parts)
    y0 = min(p.box.y for p in parts)
    x1 = max(p.box.x2 for p in parts)
    y1 = max(p.box.y2 for p in parts)

    return OcrLine(
        text=text,
        box=Box(x=x0, y=y0, w=x1 - x0, h=y1 - y0, panel_id=anchor.box.panel_id),
        confidence=min(p.confidence for p in parts),
        script=anchor.script,
        char_boxes=boxes,
        panel_id=anchor.panel_id,
        engine=anchor.engine,
        # Every measured pixel stays the anchor's. A block has no single glyph
        # height, and the union's height is the height of a paragraph.
        cap_height_px=anchor.cap_height_px,
        numeral_box=anchor.numeral_box,
        numeral_height_px=anchor.numeral_height_px,
        contrast_ratio=anchor.contrast_ratio,
        rotation_k=anchor.rotation_k,
    )


__all__ = [
    "ALIGN_FRAC",
    "LINE_GAP_RATIO",
    "MAX_LINES",
    "MULTILINE_FIELDS",
    "Continuation",
    "find",
    "merge",
]
