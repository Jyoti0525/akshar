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

---------------------------------------------------------------------------
SHAPE DISCRIMINATES; DISTANCE ONLY BREAKS TIES
---------------------------------------------------------------------------
Rewritten 2026-09-10 after measuring the 38 labelled declaration panels. Of the
147 values printed on them the pipeline attached 42 and **read but failed to
attach 57** -- the number was in the OCR output and was thrown away. That single
failure produced 45 of the 86 REVIEW verdicts across the set, because a rulepack
handed `'MRP'` with no figure, or `'PKD.'` with no date, can only say *"the
declaration is present but not in the prescribed form"* and ask for a human.

The first version asked one question -- *"does this fragment carry a figure at
all"* -- for two fields, and then picked the nearest candidate. Both halves were
wrong on real packs:

* **Distance is not the signal.** On `cheese.jpg` the net-quantity label joined
  to `'ALWAYS KEEP UNDER REFRIGERATION (BELOW 4C...'` because that line has the
  `4` of `4C` and its box centre sat 133 px away against 229 px for the
  `'200 g (7.05 oz)'` printed beside it.
* **The geometry of a printed table is not tidy.** Measured over those 57
  fragments, the label-to-value gap runs from -13.9 to +10.2 label heights and
  the two boxes share a row less than half the time -- the value column is
  routinely set a half-row above or below its labels.

What *is* reliable is the shape of the value. `02-2024` is a date, `L 2524` is a
code, `B52218815C` is a code, `342-00` is a price, `200 g` is a quantity. So the
patterns below are per-field and specific, ordered most-specific first, and a
fragment belongs to the first field that claims it -- which is what stops the
bare-number `mrp` pattern from eating every date and quantity on the panel.

Checked against 70 value fragments transcribed from those 38 panels: every one
is claimed by its own field, and **no pattern claims another field's value.**
`tests/unit/test_label_value_association.py` pins that table.

**What the shape test cannot do is tell a price from a pin code**, because a
bare number is a bare number. That is covered by the rule this module has always
had: only lines the classifier left as `other` are eligible, so an address is
already `manufacturer` and a helpline is already `consumer_care` before this
runs.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass

from contracts import FieldName
from vision.classify import shapes
from vision.classify.regex_tier import FieldGuess
from vision.ocr.lines import _gap, _horizontal, _line_height, _overlaps
from vision.types import Box, OcrLine

# -- what a value of each field looks like ----------------------------------

# The date grammar lives in `shapes` because `regex_tier` needs it too and
# cannot import this module -- see that file for the barcode bug that forced
# the move. Re-exported under the old private names so the patterns below
# and every reference in this file read unchanged.
_SEP = shapes.SEP
_MONTH_NAME = shapes.MONTH_NAME
_DATE_CORE = shapes.DATE_CORE
_DATE = shapes.DATE

QUANTITY_UNITS = (
    r"m?[glL]|kg|kL|mg|mcg|µg|ug|ml|mL|cl|dl|cc|"
    r"gm|gms|grams?|kgs?|litres?|liters?|ltr|"
    r"[nN]\b|nos?\b|numbers?|pcs?\b|pieces?|units?|sheets?|pulls?|tablets?|caps?"
)
"""What follows the figure in a net quantity declaration.

Rule 7 quantities are a number AND a unit -- `200 g`, `1 kg`, `2 L`, `30 N`.
That is what separates the declaration from every other number on a panel.

Duplicated from the rulepack's own quantity vocabulary rather than imported, for
the reason `vision/quality/framing.py` gives at length: `vision/` may not import
`rules/`, and `tests/test_boundaries.py` enforces it. The drift this risks is
affordable because **nothing here decides anything** -- it chooses which of two
already-read fragments to join, and the rulepack judges the joined text on its
own merits afterwards.
"""

ASSOCIABLE: dict[FieldName, re.Pattern[str]] = {
    "net_quantity": re.compile(
        rf"(?i)(?<![\d.])\d{{1,5}}(?:[.,]\d{{1,3}})?\s*(?:{QUANTITY_UNITS})"
    ),
    "mfg_date": re.compile(f"(?i){_DATE}"),
    "expiry_date": re.compile(f"(?i){_DATE}"),
    # A code carries BOTH letters and digits -- letters alone are a word, and
    # `FSSAI`, `ALWAYS` and `EPIP` were all claimed as batch numbers before this
    # required a digit. Two forms: one token of four or more (`B062207`,
    # `MK08D2451`), or a hyphenated one (`CE-11002`, `M-09`). The separate
    # `[A-Z]{1,2}\s\d{3,8}` form catches `L 2524`, and its prefix is capped at
    # two letters so `INS 331` in an ingredients list is not a batch number.
    "batch": re.compile(
        r"(?<![A-Za-z0-9])(?:"
        r"(?=[A-Z0-9\-]*[A-Z])(?=[A-Z0-9\-]*\d)"
        r"(?:[A-Z0-9]{4,}|[A-Z0-9]+(?:-[A-Z0-9]+)+)"
        r"|[A-Z]{1,2}\s\d{3,8}"
        r")(?![A-Za-z0-9])"
    ),
    "mrp": re.compile(r"(?<![A-Za-z0-9/.\-])\d{1,5}(?:[.,\-]\d{2})?(?:\s*/-)?(?![\d/.])"),
}
"""Fields set as a label beside a value, and what that value looks like.

Ordering matters and is `SPECIFICITY` below, not this dict's insertion order.
"""

ANCHORED: dict[FieldName, re.Pattern[str]] = {
    "net_quantity": re.compile(rf"(?i)\d{{1,5}}(?:[.,]\d{{1,3}})?\s*(?:{QUANTITY_UNITS})"),
    "mfg_date": re.compile(rf"(?i)(?:{_DATE_CORE})"),
    "expiry_date": re.compile(rf"(?i)(?:{_DATE_CORE})"),
    "batch": re.compile(
        r"(?=[A-Z0-9\-]*[A-Z])(?=[A-Z0-9\-]*\d)"
        r"(?:[A-Z0-9]{4,}|[A-Z0-9]+(?:-[A-Z0-9]+)+|[A-Z]{1,2}\s\d{3,8})"
    ),
    "mrp": re.compile(r"\d{1,5}(?:[.,\-]\d{2})?(?:\s*/-)?"),
}
"""The same shapes, anchored, with the boundary guards removed.

`ASSOCIABLE` searches a line and its guards are what make that safe: `(?![\\d])`
on the end of a date is why `342-00` is not read as one. Those same guards make
it structurally unable to see a value that has been printed hard against the
next one -- `'09-08-202308-11-2023M-09'`, where the recogniser emitted nothing
for the column gaps.

So `vision.ocr.split` consumes such a run left to right with these instead. The
guards are not needed there and would be wrong: position in the string is doing
the work the lookarounds do here, and a fragment is accepted only if the tokens
account for the entire line.

**Never use these to search, and note there is no `\\A`.** They are written for
`Pattern.match(text, offset)`, which already anchors at the offset it is given.
An `\\A` would anchor to the start of the whole string instead, so every token
after the first would fail to match and a welded row would silently come back
unsplit -- which is how this was first written.
"""

SPECIFICITY: tuple[FieldName, ...] = (
    "net_quantity",
    "mfg_date",
    "expiry_date",
    "batch",
    "mrp",
)
"""Most specific first. A fragment belongs to the first field that claims it.

`mrp` is last because a price is a bare number and a bare number is a subset of
every other value on the panel: without this order an `MRP` label takes the
packing date, the batch code and the net quantity, all of which contain one.
`mfg_date` and `expiry_date` share a pattern by construction -- nothing in the
shape of `18/05/23` says which it is, and the *label* is what decides.
"""

# -- how far a value may sit from its label ---------------------------------

GAP_RATIO = 12.0
"""How far along the line a value may sit from its label, in label heights.

Was 4.0, drawn from one pack where the gap was 3.0. Measured across the 57
values this module was failing to attach, the real gap runs to **10.2** label
heights: a printed table sets its value column at a column edge, not beside the
words, and `milksoap.jpg` puts 40 mm of yellow film between the two.

Widening this was only safe once shape did the discriminating. On its own it
would have joined an MRP label to whatever number happened to be nearest.
"""

DRIFT_RATIO = 1.5
"""How far the value's centre may sit off the label's, across the line.

Not zero, because the value column of a printed table is routinely set a half
row above or below its labels -- on `santoor.jpg` the offset is a full row, so
`FKGB013` lands beside `Mfg. Date` and `Batch No.` appears to have no value at
all. Not unbounded, because `vision.ocr.lines` already merged anything actually
on this line, so a fragment two rows away belongs to a different declaration.
"""

BESIDE_BACKTRACK_FRAC = 0.25
"""How far a value may overlap its label along the reading axis and still count
as printed beside it. DBNet pads its proposals and a label and the figure beside
it routinely come back a few pixels into each other."""

STACK_ALIGN_FRAC = 0.5
"""How much of the narrower box must lie within the wider one's span for a value
printed *underneath* its label to count as belonging to it."""

STACK_GAP_RATIO = 3.0
"""Line spacing a stacked pair may be separated by.

Three rather than 1.5: a label with its value set under it is often separated by
the label's own second line (`MRP` / `(incl. of all taxes)` / `140.00`). Past
three the next declaration has begun.
"""


@dataclass(frozen=True, slots=True)
class Association:
    """One label region and the value region it belongs to."""

    label: int
    value: int
    field: FieldName
    reason: str


def claims(field: FieldName, text: str) -> bool:
    """Does `field` own this fragment, given every more specific field said no?"""
    pattern = ASSOCIABLE.get(field)
    if pattern is None or not pattern.search(text):
        return False
    for other in SPECIFICITY:
        if other == field:
            return True
        if {field, other} == {"mfg_date", "expiry_date"}:
            continue  # one shape; the label decides which
        if ASSOCIABLE[other].search(text):
            return False
    return True


def _carries_value(text: str, field: FieldName) -> bool:
    return claims(field, text)


def _stacked(label: Box, value: Box) -> bool:
    """Is `value` printed directly under (or over) `label`, and aligned to it?"""
    if _horizontal(label) != _horizontal(value):
        return False
    horizontal = _horizontal(label)
    # "Under" along the reading axis means overlapping *across* it, which is the
    # opposite of what `_overlaps` tests for two fragments of one line, so the
    # flag is inverted for both questions asked here.
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
    """Is `value` printed on (or within a row of) the same line as `label`?"""
    if _horizontal(label) != _horizontal(value):
        return False
    horizontal = _horizontal(label)
    height = max(_line_height(label), _line_height(value))
    if height <= 0:
        return False

    # Across the reading axis: the value's centre may drift by up to a row, so a
    # value column set slightly high still belongs to its labels. `_overlaps` is
    # not enough on its own -- half of the real pairs do not overlap at all.
    drift = abs((value.cy - label.cy) if horizontal else (value.cx - label.cx))
    if drift > height * DRIFT_RATIO:
        return False

    gap = _gap(label, value, horizontal=horizontal)
    return -height * BESIDE_BACKTRACK_FRAC <= gap <= height * GAP_RATIO


def _distance(a: Box, b: Box) -> float:
    return abs(a.cx - b.cx) + abs(a.cy - b.cy)


_MONTHS = {
    name: number
    for number, name in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1
    )
}

_NUMERIC_DATE = re.compile(rf"(\d{{1,4}}){_SEP}(\d{{1,2}})(?:{_SEP}(\d{{2,4}}))?")
_NAMED_DATE = re.compile(
    rf"(\d{{0,2}})\s*[./\-]?\s*({_MONTH_NAME})\s*[.\-/]?\s*(\d{{2,4}})", re.I
)
"""`23/SEP/2025` puts a separator between the day and the month name, so the
day is not simply adjacent to it. Without that optional mark the match begins
at `SEP` and the day is silently lost -- which still orders correctly against
another month, and would quietly mis-order two dates in the same month."""


def _date_key(text: str) -> tuple[int, int, int] | None:
    """A sortable (year, month, day) for a date fragment, or `None`.

    Deliberately forgiving and deliberately not a `datetime`. It exists to
    answer one question -- which of two dates is later -- and a fragment that
    cannot answer it returns `None` rather than a guess. Day is 0 where the
    pack printed only a month and year, which orders it before any day in that
    month and is the conservative direction for the only comparison made.
    """
    named = _NAMED_DATE.search(text)
    if named:
        day, month_name, year = named.groups()
        month = _MONTHS.get(month_name[:3].upper())
        if month:
            return (_full_year(year), month, int(day or 0))

    numeric = _NUMERIC_DATE.search(text)
    if numeric:
        first, second, third = numeric.groups()
        if third is None:  # MM/YYYY or MM/YY
            return (_full_year(second), int(first), 0)
        return (_full_year(third), int(second), int(first))
    return None


def _full_year(value: str) -> int:
    year = int(value)
    return year if year > 99 else 2000 + year


def _unswap_dates(found: list[Association], lines: list[OcrLine]) -> list[Association]:
    """An expiry is after a manufacture date. Where it is not, they are swapped.

    `mfg_date` and `expiry_date` share one shape by construction -- nothing in
    `18/12/22` says which it is -- so the pairing separates them by distance,
    and on a coded strip printed as two columns that is a coin toss. On
    `goodday.jpg` it came up tails: `PKD.` took `18/12/22` and `USE BY` took
    `19/06/22`, both wrong, and the officer was shown a pack that expired six
    months before it was made.

    Chronology is the one fact available that distance is not. It is applied
    only where both fields were filled by association and both fragments parse,
    because that is the only situation this ambiguity arises in -- and only to
    swap, never to drop: if the dates are already in order nothing happens, and
    a pack genuinely printing an impossible pair keeps both values so the
    report shows what is on it.
    """
    by_field = {a.field: a for a in found}
    mfg, expiry = by_field.get("mfg_date"), by_field.get("expiry_date")
    if mfg is None or expiry is None:
        return found

    made, expires = _date_key(lines[mfg.value].text), _date_key(lines[expiry.value].text)
    if made is None or expires is None or expires >= made:
        return found

    note = " (the two dates were in the wrong order and have been exchanged)"
    swapped = {
        id(mfg): dataclasses.replace(mfg, field="expiry_date", reason=mfg.reason + note),
        id(expiry): dataclasses.replace(expiry, field="mfg_date", reason=expiry.reason + note),
    }
    return [swapped.get(id(a), a) for a in found]


def associate(lines: list[OcrLine], guesses: list[FieldGuess]) -> list[Association]:
    """Pair each value-less field label with the value printed beside it.

    Only lines the classifier left as `other` are eligible as values, so this
    never takes a declaration away from a field that claimed one outright.

    **Pairs are assigned globally, nearest first**, rather than by walking the
    labels in order. On `goodday.jpg` the coded strip prints `PKD.`, `USE BY` and
    `LOT No.` down one column against `19/06/22`, `18/12/22` and `B062207` down
    another; taking each label's nearest free candidate in index order lets the
    first label win a value that sits closer to the second. Sorting every
    eligible pair by distance and assigning greedily gives each label the value
    actually printed against it, and gives the same answer whichever order the
    detector happened to return the regions in.
    """
    candidates: list[tuple[float, int, int, FieldName, str]] = []

    for i, (line, guess) in enumerate(zip(lines, guesses, strict=True)):
        if guess.field not in ASSOCIABLE:
            continue
        if _carries_value(line.text, guess.field):
            continue  # the value is already on this line; nothing to join

        for j, other in enumerate(lines):
            if j == i or guesses[j].field != "other":
                continue
            if other.rotation_k != line.rotation_k:
                continue
            if not _carries_value(other.text, guess.field):
                continue
            beside = _beside(line.box, other.box)
            if not beside and not _stacked(line.box, other.box):
                continue
            candidates.append(
                (
                    _distance(line.box, other.box),
                    i,
                    j,
                    guess.field,
                    "beside it" if beside else "under it",
                )
            )

    # Nearest pair first; ties break on the label then the value index so that
    # two runs over one photograph agree. Section 14: a finding you cannot
    # reproduce is a finding you cannot defend.
    candidates.sort(key=lambda c: (c[0], c[1], c[2]))

    used_labels: set[int] = set()
    used_values: set[int] = set()
    found: list[Association] = []
    for _, label_index, value_index, field, where in candidates:
        if label_index in used_labels or value_index in used_values:
            continue
        used_labels.add(label_index)
        used_values.add(value_index)
        found.append(
            Association(
                label=label_index,
                value=value_index,
                field=field,
                reason=(
                    f"{field} label {lines[label_index].text.strip()!r} was read as its "
                    f"own region; {lines[value_index].text.strip()!r} is printed {where} "
                    f"and has the shape of a {field.replace('_', ' ')} value"
                ),
            )
        )

    return sorted(_unswap_dates(found, lines), key=lambda a: a.label)


__all__ = [
    "ASSOCIABLE",
    "BESIDE_BACKTRACK_FRAC",
    "DRIFT_RATIO",
    "GAP_RATIO",
    "SPECIFICITY",
    "STACK_ALIGN_FRAC",
    "STACK_GAP_RATIO",
    "Association",
    "associate",
    "claims",
]
