"""Tying what the model read to where the detector found ink.

A `Reading` says "the MRP is 335.00 and it is about here". That is not enough to
become a `Declaration`, and the gap is the whole safety argument of this package.

`contracts.Declaration` requires a `box`. It is not optional and it never was,
and the consequence is structural: **a reading that does not correspond to a
text region the detector independently found cannot enter the record at all.**
A model that invents a price for a pack that has none produces a reading with
nowhere to land, and it is dropped here with a count kept. Fluency cannot
manufacture ink.

So this module does one job: for every reading, find the detected line it
belongs to, and replace that line's *text* with what the model read. Then
`vision/classify/assemble.py` runs exactly as it does today -- same cap-height
measurement, same numeral extraction, same label-and-value association, same
address grouping, same duplicate suppression. Every millimetre in the finished
record still comes from the detector's geometry and the scale.

**What the model's box is for, and what it is not for.** It picks one rectangle
out of twenty. It is never measured, never stored, and never reaches a rule. A
model that boxes loosely still chooses the right region; a model that boxes
perfectly gains nothing further. This is deliberate, because reading is what
these models are good at and localising is what they are middling at, and the
design should lean on the first and not depend on the second.

**Where the residual risk actually sits.** Matching a box proves there is ink
there. It does not prove the ink says what the model says it says. Where the
OCR path read *something* the two are compared and the agreement is recorded as
`ocr_confidence`, which is an honest number an officer can see; where OCR read
nothing legible -- the coconut-oil strip, where it produced `PONDIA` and
`4cal` -- there is nothing to corroborate against and the reading stands on the
model alone. That is a real limitation, it is why `corroboration` is reported
per line rather than averaged away, and it is why this is a tier rather than a
replacement.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from difflib import SequenceMatcher

from contracts.declarations import Box
from vision.classify.regex_tier import FieldGuess
from vision.types import OcrLine
from vision.vlm.prompt import Reading

MIN_OVERLAP = 0.15
"""How much of the detected line the model's box must cover before the two are
called the same text.

Low, on purpose. The model is being asked to pick one region out of twenty, not
to trace it: a box that covers a fifth of the right line is a hit, and a box
that covers a fifth of the wrong line almost never happens because the wrong
lines are elsewhere on the pack. Raising this trades readings the system would
have got right for a precision it does not need."""

READER_CONFIDENCE = 0.75
"""What `field_confidence` a reading carries.

A fixed number rather than one the model supplies, because a self-reported
confidence is not calibrated against anything and putting it in a legal record
dressed as a measurement would be worse than a constant that everybody knows is
a constant. It sits below the regex tier's certainty on the patterns regex is
sure about, and above its floor."""


@dataclass(frozen=True, slots=True)
class Applied:
    """What the reader changed, for the record and for the officer's screen."""

    lines: list[OcrLine]
    fields: dict[int, FieldGuess]

    readings: int = 0
    matched: int = 0
    unplaced: int = 0
    """Readings with no detected region under them. Dropped, and counted --
    a silent drop here is exactly the failure this package is guarding."""

    corroborated: int = 0
    """Matches where the OCR path read something close to the same thing."""

    elapsed_ms: float = 0.0
    """Wall clock, including the network. Reported beside the other stages so a
    tier that has quietly become the slow one is visible rather than inferred."""

    @property
    def note(self) -> str:
        if not self.readings:
            return "the label reader returned nothing usable"
        parts = [f"{self.matched} of {self.readings} readings placed on detected text"]
        if self.corroborated:
            parts.append(f"{self.corroborated} corroborated by the recogniser")
        if self.unplaced:
            parts.append(f"{self.unplaced} dropped with no text region under them")
        return "; ".join(parts)


def _overlap(box: Box, x0: float, y0: float, x1: float, y1: float) -> float:
    """Fraction of the detected line covered by the model's rectangle."""
    left = max(box.x, x0)
    top = max(box.y, y0)
    right = min(box.x + box.w, x1)
    bottom = min(box.y + box.h, y1)
    if right <= left or bottom <= top:
        return 0.0
    area = max(1e-6, box.w * box.h)
    return ((right - left) * (bottom - top)) / area


def agreement(left: str, right: str) -> float:
    """How much two readings of the same ink look alike, 0 to 1."""

    def normalise(text: str) -> str:
        return "".join(ch for ch in text.lower() if ch.isalnum())

    a, b = normalise(left), normalise(right)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def apply(
    lines: list[OcrLine],
    readings: list[Reading],
    *,
    width: int,
    height: int,
) -> Applied:
    """Rewrite the lines the model read, and say which field each one is.

    Returns the lines unchanged when there is nothing to apply, so a caller can
    use the result unconditionally.
    """
    if not lines or not readings or width <= 0 or height <= 0:
        return Applied(lines=list(lines), fields={}, readings=len(readings))

    # Greedy, best overlap first. One detected region cannot be two
    # declarations, and taking the strongest pairing first stops a marginal
    # match from stealing a line that a confident one wanted.
    scored: list[tuple[float, int, int]] = []
    for r_index, reading in enumerate(readings):
        x0, y0, x1, y1 = reading.box
        pixels = (x0 * width, y0 * height, x1 * width, y1 * height)
        for l_index, line in enumerate(lines):
            overlap = _overlap(line.box, *pixels)
            if overlap >= MIN_OVERLAP:
                scored.append((overlap, r_index, l_index))
    scored.sort(key=lambda row: row[0], reverse=True)

    taken_lines: set[int] = set()
    taken_readings: set[int] = set()
    rewritten = list(lines)
    fields: dict[int, FieldGuess] = {}
    corroborated = 0

    for overlap, r_index, l_index in scored:
        if r_index in taken_readings or l_index in taken_lines:
            continue
        taken_readings.add(r_index)
        taken_lines.add(l_index)

        reading = readings[r_index]
        line = lines[l_index]
        similarity = agreement(reading.text, line.text)
        if similarity >= 0.6:
            corroborated += 1

        # Geometry is untouched. Only the words change, and with them the field.
        rewritten[l_index] = replace(
            line,
            text=reading.text,
            confidence=max(line.confidence, similarity),
        )
        fields[l_index] = FieldGuess(
            field=reading.field,  # type: ignore[arg-type]
            confidence=READER_CONFIDENCE,
            reason=(
                f"read from the photograph by the label reader "
                f"(overlap {overlap:.2f}, recogniser agreement {similarity:.2f})"
            ),
        )

    return Applied(
        lines=rewritten,
        fields=fields,
        readings=len(readings),
        matched=len(taken_readings),
        unplaced=len(readings) - len(taken_readings),
        corroborated=corroborated,
    )


__all__ = ["MIN_OVERLAP", "READER_CONFIDENCE", "Applied", "agreement", "apply"]
