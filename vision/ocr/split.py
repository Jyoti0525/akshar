"""One printed line, several declarations' values: split it back apart.

---------------------------------------------------------------------------
THE PACK THAT FORCED IT
---------------------------------------------------------------------------
`udadpapad.jpg` sets its coded strip as a two-row table:

    PACKED ON            USE BY              BATCH NO.        <- y 165
    09-08-2023           08-11-2023          M-09             <- y 208

The three labels come back as three regions, correctly classified `mfg_date`,
`expiry_date` and `batch`. The three values come back as **one** region
spanning the whole width, and the recogniser -- which emits a space for a word
gap, not for a column gap -- reads it as:

    '09-08-202308-11-2023M-09'

Two things then go wrong at once, and neither is fixable downstream:

1. **No value shape matches it.** `_DATE` ends in `(?![\\d])`, so `09-08-2023`
   followed immediately by `0` is refused -- correctly, because in isolation
   that string could be anything. Every pattern in `associate.ASSOCIABLE`
   fails, so the line carries no value as far as pairing is concerned.
2. **One line can only be one label's value.** Even had a shape matched,
   `associate` consumes a whole region per label, so at best one of the three
   declarations would have been completed and the other two would still report
   a label with nothing beside it.

Measured over the 38 labelled panels, that is the commonest way a value is
lost: `batch` reads correctly on 5 of 23 and `expiry_date` on 7 of 22, and the
bare captions -- `BATCH NO.`, `PACKED ON`, `USE BY`, `Net Weight:`, `Pkd.` --
come back as the declarations themselves.

---------------------------------------------------------------------------
WHY HERE AND NOT IN THE MERGER
---------------------------------------------------------------------------
`vision.ocr.lines` was right to merge those cells. They *are* one printed row,
at one baseline, in one size, and a merger that split on wide gaps would also
split `MRP        140.00` -- the very pairing the merge exists to preserve.
The information that they are separate values does not exist at merge time,
because nothing has been read yet. It exists only after recognition, in the
shape of the text, which is what this module tests.

So this runs after OCR and before classification, and the rest of the pipeline
sees what it would have seen if the detector had returned three regions.

---------------------------------------------------------------------------
IT SPLITS ONLY WHAT CANNOT BE ANYTHING ELSE
---------------------------------------------------------------------------
Splitting a line is destructive -- it invents a boundary the recogniser did not
report -- so the bar is deliberately high. A run is split only where:

- **two or more value shapes meet with no separator at all.** A space, comma or
  slash between them means the recogniser saw one field and we leave it alone.
- **each fragment is claimed by a different field**, under the same
  `associate.SPECIFICITY` order the pairing uses. Two dates running together
  are still split; a date and the digits of a batch code are not, because the
  batch pattern claims the whole token first.
- **the fragments cover essentially the whole line.** A shape found inside
  prose is not a column cell, and `INGREDIENTS: ... 2023` must not be cut in
  half.

Where any of those fails the line is returned exactly as it arrived.

**The sub-boxes are proportional, and that is a real approximation.** Character
geometry is available on about one line in six, so a fragment's box is
interpolated across the parent box by character offset. It is accurate enough
to decide which label a fragment sits under -- the question this exists to
answer -- and `cap_height_px` is inherited from the parent rather than
recomputed, because the parent measured one baseline for the whole row and that
is exactly what each fragment sits on.
"""

from __future__ import annotations

import dataclasses
import re
from itertools import pairwise

from vision.classify.associate import ANCHORED, SPECIFICITY, claims
from vision.types import Box, OcrLine

MIN_FRAGMENTS = 2
"""One match is just a value. Splitting begins at two."""

MIN_COVERAGE = 0.80
"""Fraction of the line's non-space characters the fragments must account for.

Below this the matches are shapes sitting inside prose rather than the cells of
a column, and the line is left whole. `'Percent daily values are based on a
2000 calorie diet'` carries a number; it is not a table row."""

_SEPARATOR = re.compile(r"[\s,;:/|]")
"""Anything the recogniser emits between two fragments it saw as related.

A column gap produces nothing at all -- that absence is the signal. If the
recogniser put a character between two values it read them as one field's text,
and this module does not second-guess that."""


def _fragments(text: str) -> list[tuple[str, int, int]]:
    """Tokenise the whole line into value fragments, or return nothing.

    Left to right, taking at each offset the narrowest field that matches
    there -- `SPECIFICITY`, the same order `associate` resolves ties in, so a
    token is never carved up by `mrp`'s bare-number shape when a date or a
    batch code claims it whole.

    **It is all or nothing.** If any character that is not a separator cannot
    be consumed, this returns `[]` and the line is left exactly as read. That
    single condition is what keeps prose out: `'Percent daily values are based
    on a 2000 calorie diet'` offers `2000` and then cannot account for
    `calorie`, so nothing is split. A column row offers nothing but cells.
    """
    found: list[tuple[str, int, int]] = []
    position = 0
    length = len(text)

    while position < length:
        if _SEPARATOR.match(text[position]):
            position += 1
            continue

        matched = False
        for field in SPECIFICITY:
            match = ANCHORED[field].match(text, position)
            if match is None or not match.group():
                continue
            token = match.group()
            if not claims(field, token):
                continue
            found.append((token, position, position + len(token)))
            position += len(token)
            matched = True
            break

        if not matched:
            return []  # a character no value shape accounts for; not a row

    return found


def _abutting(text: str, fragments: list[tuple[str, int, int]]) -> bool:
    """Do the fragments run together with nothing between them?

    At least one junction must be bare. A row read as `'09-08-2023 08-11-2023'`
    has a space, and the recogniser saw a gap it thought worth reporting -- that
    line is left alone, because `associate` can already read it.
    """
    return any(not text[end:start] for (_, _, end), (_, start, _) in pairwise(fragments))


def _coverage(text: str, fragments: list[tuple[str, int, int]]) -> float:
    counted = sum(len(frag.replace(" ", "")) for frag, _, _ in fragments)
    total = len(text.replace(" ", ""))
    return counted / total if total else 0.0


def _slice_box(box: Box, text: str, start: int, end: int) -> Box:
    """The part of `box` that holds `text[start:end]`, by character offset."""
    n = max(len(text), 1)
    if box.w >= box.h:  # set across the page
        left = box.x + box.w * (start / n)
        return Box(x=left, y=box.y, w=box.w * ((end - start) / n), h=box.h)
    top = box.y + box.h * (start / n)
    return Box(x=box.x, y=top, w=box.w, h=box.h * ((end - start) / n))


def unweld_line(line: OcrLine) -> list[OcrLine]:
    """`line`, or the value fragments it turned out to be carrying."""
    text = line.text
    if not text or not text.strip():
        return [line]

    fragments = _fragments(text)
    if len(fragments) < MIN_FRAGMENTS:
        return [line]
    if not _abutting(text, fragments):
        return [line]
    if _coverage(text, fragments) < MIN_COVERAGE:
        return [line]

    return [
        dataclasses.replace(
            line,
            text=frag,
            box=_slice_box(line.box, text, start, end),
            # Character geometry describes the parent's characters at the
            # parent's offsets; carrying it onto a fragment would hand
            # `min_width_ratio` boxes belonging to a different piece of text.
            # Dropping it makes that check answer NO_DATA, which is its
            # documented behaviour when geometry is unavailable and is the
            # conservative direction.
            char_boxes=[],
        )
        for frag, start, end in fragments
    ]


def unweld(lines: list[OcrLine]) -> list[OcrLine]:
    """Every line, with welded value rows split into their cells."""
    out: list[OcrLine] = []
    for line in lines:
        out.extend(unweld_line(line))
    return out


__all__ = ["MIN_COVERAGE", "MIN_FRAGMENTS", "unweld", "unweld_line"]
