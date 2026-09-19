"""Two declarations printed as one sentence run: cut them apart.

---------------------------------------------------------------------------
THE PACK THAT FORCED IT
---------------------------------------------------------------------------
A face serum carton, scanned live on 2026-09-19. Across the foot of the front
panel, in one line of type, the pack prints:

    Face Serum. Made in India

That is two of Rule 6(1)'s declarations -- the common or generic name under
6(1)(b) and the country of origin under 6(1)(g) -- set as one sentence run and
detected, correctly, as one region. The classifier then has to give the region
one name, `country_of_origin` wins it at 0.88, and **the generic name is gone**:
not misread, not absent from the pack, simply never offered to any tier as a
line of its own. `vision.classify.commodity` never sees `Face Serum`, because
what it is shown is a line containing the word `Made`, which is a prose marker
and a correct one.

The officer's exhibit then carries a box drawn round `Face Serum. Made in
India` captioned *Country of origin* -- an assertion that the words `Face
Serum` are part of that declaration, which they are not -- and a separate
finding that the pack declares no generic name, which it does, in the largest
type on the panel.

It is the same shape of defect as the perfume packet reported earlier: **one
detected region carrying more than one declaration.** `vision.ocr.split`
handles the column-table form of it, where several *values* weld together with
no separator at all. This handles the opposite form, where the separator is
there and is a full stop.

---------------------------------------------------------------------------
THE RULE, AND WHY IT IS THIS STRICT
---------------------------------------------------------------------------
Cutting a line is destructive: it invents a boundary and it can take an address
away from the name it belongs to. So a line is cut only when the cut is a pure
gain, and every condition below has to hold at once:

1. **The stop ends a word, not an abbreviation.** `MIN_WORD_BEFORE_STOP` asks
   for four unbroken word characters running up to the stop, which is what
   separates `Serum.` and `645.00.` from `NET WT.`, `MRP RS.`, `Pvt.`, `Mfg.`
   and `No.` -- an English abbreviation is three letters or fewer with a space
   in front of it. This is the guard that does most of the work.

2. **Every piece is substantial.** `MIN_PART_CHARS` refuses a cut that would
   leave a fragment shorter than a word.

3. **At least two pieces name DIFFERENT declarations.** Not "the remainder is
   left over" -- each piece has to be claimed, by the same classifier that will
   claim it downstream. `Marketed by Acme Foods Ltd. 12 MG Road, Pune` names
   the manufacturer in one piece and nothing in the other, so it is left whole
   and Rule 6(1)(a) keeps its address. Neighbours that name the same field, or
   that name nothing, are joined back together first (`_regroup`), so a caption
   is never cut off its own figure.

4. **Nothing already found is lost.** Whatever the whole line was called must
   still be called that by one of the pieces. This is the condition that makes
   the operation safe to reason about: a cut can only ever *add* a declaration,
   never move one or drop one. A line that was `other` has nothing to lose and
   may be cut on condition 3 alone.

Two whole kinds of line are refused outright on top of all four: an address,
because it is *made* of full stops and is the declaration a cut most easily
destroys, and an ingredients or nutrition panel, because its items are drawn
from the same vocabulary the generic-name lexicon is.

Measured over 13,197 corpus lines and 796 from the labelled panels: a draft
without conditions 1 and 4 cut seven lines, four of them wrongly. The shipped
form cuts one, and that one is a body lotion recovering its generic name.

---------------------------------------------------------------------------
WHERE IT RUNS
---------------------------------------------------------------------------
After recognition and before classification, beside `vision.ocr.split`, so the
rest of the pipeline sees what it would have seen had the detector returned two
regions. Association, continuation and the commodity tier all then work on
ordinary single-declaration lines with no knowledge that this ran.

The geometry is divided honestly. Character boxes are *sliced* rather than
dropped -- unlike `split.unweld_line`, the offsets here are exact, so Rule
7(3)'s character-width proviso survives the cut -- and the numerals go to the
piece that actually contains them, or nowhere.
"""

from __future__ import annotations

import dataclasses
import re

from vision.classify import commodity
from vision.classify.regex_tier import classify_text, is_address_like
from vision.ocr.script import script_of_text
from vision.ocr.split import slice_box
from vision.types import Box, OcrLine

MAX_PARTS = 4
"""More declarations than this off one region and it is a paragraph of copy,
not a row of declarations. Four allows `Toilet Soap. Net Wt. 100 g. MRP Rs.
45.00. Made in India`, which is how a small carton prints its whole 6(1) block.

Counted **after** `_regroup`, on declarations rather than on stops: that line
carries five full stops and four declarations, and it is the four that this is
a statement about."""

MAX_STOPS = 2 * MAX_PARTS
"""How many boundaries are worth examining at all, before anything is grouped.

Purely a bound on work and on the blast radius. A region with nine sentence
stops in it is body copy, and no arrangement of `MAX_PARTS` declarations needs
more stops than one apiece with their abbreviations."""

MIN_PART_CHARS = 4
"""Shortest piece a cut may produce.

**This is the guard that does the work**, and it is a statement about
abbreviations rather than about declarations. Every full stop that is not the
end of a sentence sits behind a short word -- `Mfg`, `Lic`, `No`, `Pvt`, `Ltd`,
`Co`, `Rd`, `Dr`, `St`, `Ex`, `Wt` -- and a cut there leaves that word standing
alone. Nothing this project must find is three characters long: the shortest
commodity term in the lexicon is `tea`, and it is never printed as a sentence
of its own beside another declaration.
"""

MIN_NAMED_PARTS = 2
"""How many pieces must be claimed by a field before the cut is worth making.

One named piece and one leftover is the address case, and the leftover is
usually the rest of the address."""

_PANEL_BODY = frozenset({"ingredients", "nutrition"})
"""Declarations that are a list, and whose items are commodity nouns.

Neither is a Rule 6(1) declaration in its own right for our purposes, and both
are made of exactly the words the generic-name lexicon is built from. A line
already named one of these is not carrying a second declaration; it is carrying
its own contents."""

MIN_WORD_BEFORE_STOP = 4
"""How many unbroken word characters must run up to the stop.

**This is the abbreviation test, and it is the guard that earns its keep.**
`MIN_PART_CHARS` looks at the whole piece and so cannot see the difference
between `Face Serum.` and `Made in India NET WT.` -- both are long. What
separates them is the word the stop is attached to, and an English abbreviation
is three letters or fewer with a space in front of it:

    Serum.  erum    four word characters      a sentence ended
    645.00. 5.00    four, counting the point  a figure ended
    NET WT. 'T WT'  a space two back          an abbreviation
    MRP RS. 'P RS'  a space two back          an abbreviation
    MFG.    ' MFG'  a space                   an abbreviation
    Pvt.    ' Pvt'  a space                   an abbreviation

Measured over 13,197 corpus lines and 796 from the labelled panels: of seven
cuts the looser form made, this refuses four, and all four were wrong.
"""

_BOUNDARY = re.compile(
    # A whole word has to end here, not an abbreviation. Four characters of
    # unbroken word -- a space or a comma inside them fails the class, which is
    # exactly how `NET WT.` and `Pvt.` are told from `Serum.`. The decimal
    # point is in the class so `645.00.` ends a figure rather than a two-digit
    # stub. See MIN_WORD_BEFORE_STOP.
    r"(?<=[A-Za-z0-9.\)\]ऀ-ॿ]{4})"
    # A pack that sets `Face Serum | Made in India` puts a space either side of
    # the pipe. One that sets `Face Serum. Made in India` puts none before the
    # stop. Both are the same boundary.
    r"\s*"
    # The stop itself. The danda is Devanagari's full stop; the pipe and the
    # bullet are what packs use when they set two declarations on one line
    # without one.
    r"[.।|•·]"
    # A gap the recogniser thought worth reporting. `645.00` has no space after
    # its stop and is one number; `Serum. Made` has one and is two sentences.
    r"\s+"
    # And a fresh start after it.
    r"(?=[A-Z0-9ऀ-ॿ])"
)


def _spans(text: str) -> list[tuple[int, int]]:
    """Half-open character ranges of the pieces, or `[]` for one piece."""
    cuts = [(m.start(), m.end()) for m in _BOUNDARY.finditer(text)]
    if not cuts:
        return []

    spans: list[tuple[int, int]] = []
    cursor = 0
    for cut_start, cut_end in cuts:
        spans.append((cursor, cut_start))
        cursor = cut_end
    spans.append((cursor, len(text)))
    return spans


def _tighten(text: str, start: int, end: int) -> tuple[int, int]:
    """The same range with surrounding whitespace excluded.

    Offsets are kept rather than the stripped string, because `char_boxes` is a
    positional contract against `text` and a piece that reported its own text
    trimmed but its boxes untrimmed would compare every character against the
    wrong glyph.
    """
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _field_of(text: str) -> str | None:
    """The declaration this piece would be called on its own, or `None`.

    The commodity lexicon is consulted as well as the caption patterns because
    Rule 6(1)(b) is the declaration packs print with no caption -- it is the
    whole reason this line was worth cutting -- and asking only the captioned
    tier would find one declaration on `Face Serum. Made in India` and conclude
    there was nothing to gain.
    """
    field = classify_text(text).field
    if field != "other":
        return field
    # `whole_line_term` and not `match`: the piece has to BE a commodity, not
    # merely contain one. `Milk& Soya` off an allergen statement contains
    # `milk`, and a cut that counted it would hand the generic-name tier a
    # clean short line reading `Milk& Soya` on a biscuit pack -- inventing the
    # very false positive `commodity.py` lists five guards to prevent. `Face
    # Serum` is the whole term, exactly, which is what a declaration looks like.
    return "generic_name" if commodity.whole_line_term(text) is not None else None


def _regroup(
    text: str, spans: list[tuple[int, int]]
) -> list[tuple[tuple[int, int], str | None]]:
    """Join back the neighbours that were never two declarations.

    ---------------------------------------------------------------------------
    THE CUT THIS UNDOES
    ---------------------------------------------------------------------------
    `Hair Serum. Net Qty. 30 ml` offers two boundaries and only the first of
    them is real. The second sits inside `Qty.`, an abbreviation, and cutting
    there separates a caption from its own figure -- which is the exact damage
    `vision.classify.associate` exists to repair, being done here for no
    reason.

    A boundary is only worth keeping where the text either side of it declares
    something **different**, so neighbours are merged while the right-hand one
    either names the same field or names nothing at all. An unnamed piece goes
    to the left because that is what a value, a unit or a qualifier is: the rest
    of the declaration in front of it.

    Merging by offset rather than by string keeps the separator inside the
    result, so the group's text is a verbatim slice of the line and its
    character boxes still line up with it.
    """
    groups: list[tuple[tuple[int, int], str | None]] = []
    for start, end in spans:
        field = _field_of(text[start:end])
        if groups:
            (open_start, _), open_field = groups[-1]
            if field is None or field == open_field:
                groups[-1] = ((open_start, end), open_field)
                continue
        groups.append(((start, end), field))
    return groups


def _numeral_owner(line: OcrLine, pieces: list[str], boxes: list[Box]) -> int | None:
    """Which piece the line's numerals are printed in, if that is knowable.

    `numeral_height_px` is what every Rule 7(2) height verdict on an MRP or a
    net quantity is computed from, so handing it to the wrong piece would
    measure one declaration and report it as another's. Where the digits cannot
    be placed, no piece gets them and the height rules answer NO_DATA -- the
    same refusal they already make when the figures could not be separated.
    """
    if line.numeral_box is None:
        if line.numeral_height_px is None:
            return None
        # No geometry, so the only evidence is which piece has digits in it.
        # Exactly one piece, or nobody: two candidates and the measurement
        # could belong to either, which is not a basis for a height verdict.
        with_digits = [index for index, piece in enumerate(pieces) if any(c.isdigit() for c in piece)]
        return with_digits[0] if len(with_digits) == 1 else None

    probe = line.numeral_box
    if line.box.w >= line.box.h:
        centre = probe.x + probe.w / 2.0
        for index, box in enumerate(boxes):
            if box.x <= centre <= box.x2:
                return index
        return None

    centre = probe.y + probe.h / 2.0
    for index, box in enumerate(boxes):
        if box.y <= centre <= box.y2:
            return index
    return None


def unstitch_line(line: OcrLine) -> list[OcrLine]:
    """`line`, or the separate declarations it turned out to be carrying."""
    text = line.text
    if not text or not text.strip():
        return [line]
    if is_address_like(text):
        # An address is built out of full stops and is the one declaration a
        # cut here would damage rather than complete.
        return [line]
    if classify_text(text).field in _PANEL_BODY:
        # `INGREDIENTs: Maize Starch. Iodised Salt,` is one declaration written
        # as two sentences, and `Iodised Salt` is a lexicon term. Cutting it out
        # produces a short clean line that the generic-name tier would then
        # declare to be what the pack contains. `commodity._inside_a_prose_block`
        # normally shadows those, but it walks DOWN the panel from the heading
        # and these two pieces sit side by side on one row, so it would never
        # see this one. Refusing the cut is the only place the heading is still
        # attached to its own list.
        return [line]

    spans = [_tighten(text, start, end) for start, end in _spans(text)]
    if not (2 <= len(spans) <= MAX_STOPS):
        return [line]
    if any(end - start < MIN_PART_CHARS for start, end in spans):
        return [line]

    if any(is_address_like(text[start:end]) for start, end in spans):
        return [line]

    groups = _regroup(text, spans)
    spans = [span for span, _ in groups]
    if not (2 <= len(spans) <= MAX_PARTS):
        return [line]

    named = {field for _, field in groups if field is not None}
    if len(named) < MIN_NAMED_PARTS:
        return [line]

    whole = classify_text(text).field
    if whole != "other" and whole not in named:
        # The cut would take away a declaration we already had. Whatever else
        # it would gain, that trade is never worth making.
        return [line]

    pieces = [text[start:end] for start, end in spans]
    boxes = [slice_box(line.box, text, start, end) for start, end in spans]
    digits = _numeral_owner(line, pieces, boxes)
    aligned = len(line.char_boxes) == len(text)

    return [
        dataclasses.replace(
            line,
            text=piece,
            box=box,
            script=script_of_text(piece),
            char_boxes=list(line.char_boxes[start:end]) if aligned else [],
            # One printed line, one baseline: the cap height the parent
            # measured is each piece's own.
            cap_height_px=line.cap_height_px,
            numeral_box=line.numeral_box if index == digits else None,
            numeral_height_px=line.numeral_height_px if index == digits else None,
        )
        for index, (piece, box, (start, end)) in enumerate(zip(pieces, boxes, spans, strict=True))
    ]


def unstitch(lines: list[OcrLine]) -> list[OcrLine]:
    out: list[OcrLine] = []
    for line in lines:
        out.extend(unstitch_line(line))
    return out


__all__ = [
    "MAX_PARTS",
    "MAX_STOPS",
    "MIN_NAMED_PARTS",
    "MIN_PART_CHARS",
    "unstitch",
    "unstitch_line",
]
