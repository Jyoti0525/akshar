"""What the model is asked, and how little of its answer is believed.

The reply is **untrusted input**. Not because the model is adversarial, but
because it is fluent: a wrong field name arrives in exactly the same shape as a
right one, and a value that was never printed on the pack reads exactly like one
that was. Everything below exists to make an unusable reply *drop out* rather
than propagate.

Three rules govern the parse, and all three fail closed:

- **An unknown field name is discarded, never coerced.** `contracts.FieldName`
  is the vocabulary; a reply saying `"price"` is dropped rather than mapped to
  `mrp`, because a mapping table is a place for the next wrong guess to hide.
- **A declaration with no box is discarded.** The box is what
  `vision/vlm/read.py` uses to find the real text region on the label, and a
  declaration that cannot be tied to one cannot be shown to anybody.
- **Nothing is invented to fill a gap.** No defaults, no empty strings promoted
  to values, no "the model probably meant". A missing field is a missing field
  and the rules engine already knows what to do with one.

**Why the model is asked for a box at all**, when the whole premise of this
package is that a model reads better than it localises: the box is used *only*
to choose which of the detector's regions a reading belongs to. It has to be
good enough to pick one rectangle out of twenty, and it is never measured. Every
millimetre in the final record still comes from the detector's geometry and the
scale, exactly as before.
"""

from __future__ import annotations

import json
import re
import typing
from dataclasses import dataclass

from contracts import FieldName

FIELDS: tuple[str, ...] = tuple(typing.get_args(FieldName))

INSTRUCTION = """You are reading a photograph of the label on an Indian packaged commodity.

List every statutory declaration you can actually see. For each one give:
  "field" - one of exactly these names: {fields}
  "text"  - the words as printed, verbatim, including the number and its unit
  "box"   - [x0, y0, x1, y1] as fractions of the image width and height,
            0 to 1, around the printed text you read

Rules you must follow:
- Only report text you can actually see in this image. If a declaration is
  covered, cut off, or too blurred to read, leave it out entirely.
- Never guess a value from the product or the brand. An unreadable price is
  absent, not estimated.
- Labels and values are often in separate columns that do not line up. Pair
  them by meaning: a price goes with the price label, a date with the date
  label, a lot code with the lot label.
- "text" is what is printed. Do not translate it, tidy it, or expand
  abbreviations.
- Use "other" for printed text that is none of the listed declarations.

Reply with JSON only: {{"declarations": [ ... ]}}"""


def build() -> str:
    return INSTRUCTION.format(fields=", ".join(FIELDS))


@dataclass(frozen=True, slots=True)
class Reading:
    """One thing the model claims is printed on the label.

    Not a `Declaration`. It has no measurement, no script, no confidence and no
    real geometry, and it cannot become one until `read.py` has matched it to a
    text region the detector independently found.
    """

    field: str
    text: str
    box: tuple[float, float, float, float]
    """Normalised (x0, y0, x1, y1). Association only -- never measured."""


_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def _payload(reply: str) -> dict | None:
    """The JSON object in a reply that may be wrapped in prose or a fence."""
    for candidate in (reply, *(m.group(1) for m in _FENCE.finditer(reply))):
        try:
            loaded = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(loaded, dict):
            return loaded
    # Last resort: the outermost braces. A model that wrote a sentence before
    # its JSON is a formatting miss, not a reason to lose the whole read.
    start, end = reply.find("{"), reply.rfind("}")
    if 0 <= start < end:
        try:
            loaded = json.loads(reply[start : end + 1])
        except (ValueError, TypeError):
            return None
        return loaded if isinstance(loaded, dict) else None
    return None


def _box(raw: object) -> tuple[float, float, float, float] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    if not all(0.0 <= v <= 1.0 for v in (x0, y0, x1, y1)):
        return None
    # Some models emit corners in either order. Normalising is a formatting
    # fix and not a guess about content.
    left, right = min(x0, x1), max(x0, x1)
    top, bottom = min(y0, y1), max(y0, y1)
    if right - left <= 0.0 or bottom - top <= 0.0:
        return None
    return (left, top, right, bottom)


def parse(reply: str) -> list[Reading]:
    """Readings the reply actually supports. `[]` for anything unusable.

    Never raises: a scan is in progress, and a malformed reply is the same
    outcome as no reader at all.
    """
    payload = _payload(reply or "")
    if payload is None:
        return []
    rows = payload.get("declarations")
    if not isinstance(rows, list):
        return []

    readings: list[Reading] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        field = row.get("field")
        text = row.get("text")
        box = _box(row.get("box"))
        if field not in FIELDS:
            continue
        if not isinstance(text, str) or not text.strip():
            continue
        if box is None:
            continue
        readings.append(Reading(field=str(field), text=text.strip(), box=box))
    return readings


__all__ = ["FIELDS", "INSTRUCTION", "Reading", "build", "parse"]
