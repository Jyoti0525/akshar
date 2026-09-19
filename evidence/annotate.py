"""The annotated photograph that goes in the report. AKSHAR.md sections 13, 6.

Section 13 asks the per-product report to carry *"the annotated photo"*, and
section 6 already reserves a place for it: the `derived_crop` tier, two years,
in the derived bucket rather than under the seven-year governance lock.

**The annotation is drawn on the rectified label, not on the camera frame, and
that is forced rather than chosen.** Every `Declaration.box` is in rectified
label space — `contracts/declarations.py` says so in as many words, because a
box in raw camera space cannot be converted to millimetres by a single scalar.
Drawing those coordinates onto the original photograph would put every rectangle
in the wrong place while looking entirely convincing, which is a worse failure
than having no picture at all.

**It is produced at scan time, never re-derived at report time.** Re-running
rectification later would find its own label quad, and a quad that differs by a
few pixels from the one the measurement used moves every box. The report must
show the frame the numbers actually came from, so the picture is made once,
beside the measurement, and stored.

**What is drawn is the numeral box, distinctly.** A height rule measures the
numerals, not the whole declaration including "(inclusive of all taxes)" — so
the report shows both the declaration it found and, inside it, the glyphs it
actually measured. A reader disputing 1.83 mm can see what was measured.

**No text from the package is drawn.** OpenCV's Hershey fonts have no
Devanagari, and a Hindi declaration rendered as boxes in an evidence exhibit is
worse than an unlabelled rectangle. Only the field name and the millimetre
figure — both ASCII by construction — are printed. The words themselves are in
the report body, where the renderer has real fonts.

Nothing here decides anything. The status colours come from verdicts computed by
`rules.engine`; this module is a pen.

---------------------------------------------------------------------------
WHY THE CAPTIONS ARE NO LONGER ON THE PHOTOGRAPH
---------------------------------------------------------------------------
Until 2026-09-19 every caption was a filled chip laid over the packaging, above
the box it named. On a rock-salt back panel that is a dozen chips stacked a few
millimetres apart, each one covering the declaration *above* the one it labels,
several of them overlapping each other, and all of them hiding the artwork a
reader is being asked to examine. The chip was invented to stay readable over
busy artwork; it succeeded, by deleting the artwork.

So the exhibit is now two panels. One is the label: boxes, the measured glyphs
inside them, and a small numbered badge in the margin beside each. The other is
a key — the same numbers, the field name in words, what was measured, and the
status — set as a list, in reading order, where nothing overlaps anything and
no caption sits on top of a declaration.

The key goes beside a portrait label and underneath a landscape one, in one to
three columns, because a declaration panel is usually wider than it is tall and
a single tall column beside it made an exhibit twice the height of the
photograph with the lower half blank.

Four further things follow from that split, and each is a decision rather than
a detail:

- **Leader lines are drawn only for FAIL and REVIEW.** A line from every box to
  every key row is twelve crossing lines, which is the clutter again in a new
  form. The boxes a finding rests on are the ones worth tracing by eye; the rest
  are found by their number.
- **The name-and-address declarations get one enclosing region.** The rules
  treat `manufacturer`, `packer`, `importer` and `consumer_care` separately and
  so does the key — but the pack prints them as one paragraph, and four adjacent
  rectangles around four lines of one address read as four separate findings.
  The region is drawn in a neutral colour and carries no status of its own,
  precisely so that grouping can never imply an accusation against a member that
  passed.
- **A badge sits outside its box, never on it.** Inside was the first attempt
  and it put a coloured disc over the first word of the declaration it was
  pointing at, which is the thing this whole restyle exists to stop doing.
- **The key's legend lists only the colours this drawing used.** The exhibit
  travels on its own — embedded in the DOCX, downloaded, photocopied — so it
  carries its own legend; but a legend naming "Contravention" on a label where
  nothing was contravened is a suggestion, not a key.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MAX_EDGE_PX = 1600
"""Longest side of the *label panel* — the photograph half of the exhibit.

Section 6 budgets roughly 40 KB for the derived crops of a scan. 1600 px keeps a
2 mm character legible at full zoom while landing in the same order of
magnitude. Larger would buy nothing: the evidence-grade original is already
stored at full resolution under its own retention rule.

The finished exhibit is wider than this, because the key panel is beside the
label rather than on top of it. That costs almost nothing in the encoded file:
the key is flat colour and ASCII text, which is the cheapest thing a JPEG can
carry, while the pixels it replaced were packaging artwork under a caption chip.
"""

BOX_COLOURS: dict[str, tuple[int, int, int]] = {
    # BGR, because this is OpenCV.
    "FAIL": (60, 60, 220),
    "REVIEW": (40, 165, 245),
    "PASS": (90, 170, 90),
    "NO_DATA": (150, 150, 150),
}
DEFAULT_COLOUR = (150, 150, 150)

CONTEXT_COLOUR = (185, 185, 185)
"""Text we read but could not name. Drawn thin, and never captioned.

Every recognised line used to get a full box with a caption, and on a back
panel that meant forty-odd red rectangles all reading "Unclassified text" --
over the nutrition table, over the cooking instructions, over single characters
the recogniser had invented. It buried the six boxes that carry the verdict and
it made the exhibit look like an accusation against the whole label.

The module docstring already had the answer: an unlabelled rectangle is better
than a mislabelled one. So unnamed text stays on the exhibit, because "this is
what we read" is part of the record and an officer needs to see how much of the
panel we understood -- but it is drawn as context rather than as a finding."""

NUMERAL_COLOUR = (255, 235, 130)
"""The measured glyphs, outlined in a colour used for nothing else."""

GROUP_COLOUR = (140, 120, 105)
"""The enclosing region drawn around an address block.

Deliberately not one of the status colours and deliberately not `CONTEXT_COLOUR`
either: a region says "the pack prints these as one paragraph" and says nothing
whatever about whether any of them complies. If this ever takes a status colour,
a grouped region would paint a passing packer's address with a failing
manufacturer's verdict."""

PANEL_COLOUR = (248, 247, 245)
"""The key's background. Near-white, so the exhibit reads as a document."""

INK_COLOUR = (44, 42, 40)
MUTED_COLOUR = (120, 118, 116)
RULE_COLOUR = (228, 226, 224)

FIELD_LABELS: dict[str, str] = {
    "mrp": "MRP",
    "net_quantity": "Net quantity",
    "mfg_date": "Date of manufacture",
    "expiry_date": "Best before / expiry",
    "manufacturer": "Manufacturer",
    "packer": "Packer",
    "importer": "Importer",
    "consumer_care": "Consumer care",
    "country_of_origin": "Country of origin",
    "generic_name": "Generic name",
    "batch": "Batch",
    "marketing_text": "Marketing text",
    # The six non-statutory names, added to `contracts` 2026-09-10 and to this
    # table 2026-09-19. Until then they fell through to
    # `name.replace("_", " ").capitalize()` and an exhibit handed to a
    # manufacturer read **"Fssai licence"**. The fallback is a safety net, not a
    # naming scheme, and `tests/unit/test_annotate_labels.py` now says so.
    "nutrition": "Nutritional information",
    "ingredients": "Ingredients",
    "storage_use": "Storage or usage instruction",
    "fssai_licence": "FSSAI licence",
    "licence": "Licence number",
    "barcode": "Barcode",
    "unit_sale_price": "Unit sale price",
    "other": "Unclassified text",
}

FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Price and quantity", ("mrp", "unit_sale_price", "net_quantity")),
    (
        "Name and address",
        ("manufacturer", "packer", "importer", "consumer_care", "country_of_origin"),
    ),
    ("Dates and batch", ("mfg_date", "expiry_date", "batch")),
    (
        "The product",
        (
            "generic_name",
            "ingredients",
            "nutrition",
            "storage_use",
            "fssai_licence",
            "licence",
            "barcode",
            "marketing_text",
        ),
    ),
)
"""How the key is ordered: by the grouping a person reading a pack already uses.

Not by severity. An exhibit that sorted its contraventions to the top would
change order between two scans of the same product, and an officer comparing
this month's exhibit against last month's would have to re-find every line. The
colour and the status word carry the severity; the order carries the label.

`tests/unit/test_annotate_labels.py` holds this to `contracts.FieldName`, so a
new field cannot quietly fall out of the key."""

ADDRESS_BLOCK: tuple[str, ...] = ("manufacturer", "packer", "importer", "consumer_care")
"""The declarations a pack prints as one paragraph, and the only ones an
enclosing region is drawn around. `country_of_origin` belongs to the same family
in the key but is usually printed somewhere else entirely, so bracketing it with
the address would draw a region across half the panel."""

_BLOCK_GAP_LINES = 1.5
_BLOCK_OVERLAP = 0.5
"""What "printed as one paragraph" means, measured.

Two address lines belong to the same block when the vertical gap between them is
no more than one and a half line heights and their horizontal extents overlap
by more than half the narrower one — which is what a paragraph is.

An earlier version took the union of *every* address declaration and rejected it
if the union enclosed too much empty space. On the Parag cheese carton that
threw the whole block away, because a consumer-care telephone number printed in
a box at the far right of the panel dragged the union across the label and over
the limit. A run of adjacent lines is the thing being looked for; measuring the
area of everything at once cannot see it.
"""


def _hex(bgr: tuple[int, int, int]) -> str:
    blue, green, red = bgr
    return f"#{red:02x}{green:02x}{blue:02x}"


STATUS_WORDS: dict[str, str] = {
    "FAIL": "Contravention",
    "REVIEW": "For examination",
    "PASS": "Checked, no contravention",
    "NO_DATA": "No conclusion",
}
"""The long form. The key panel prints the bare status token instead — `FAIL`,
`REVIEW` — because that is the word the report's verdict table uses beside it,
and an exhibit and its table that describe the same finding in two different
vocabularies is a question somebody has to answer at a hearing."""


LEGEND: tuple[tuple[str, str, str], ...] = (
    (STATUS_WORDS["FAIL"], "A rule was failed on this declaration.", _hex(BOX_COLOURS["FAIL"])),
    (
        STATUS_WORDS["REVIEW"],
        "The measurement fell inside the measurement error; no contravention is asserted.",
        _hex(BOX_COLOURS["REVIEW"]),
    ),
    (STATUS_WORDS["PASS"], "Every rule applied to it passed.", _hex(BOX_COLOURS["PASS"])),
    (
        "Read, not identified",
        "Text we recognised but could not attribute to a declaration. No rule was applied to it.",
        _hex(CONTEXT_COLOUR),
    ),
    (
        STATUS_WORDS["NO_DATA"],
        "Read from the label, but no rule could be applied or all returned NO_DATA.",
        _hex(DEFAULT_COLOUR),
    ),
    (
        "Glyphs measured",
        "The characters whose height was measured, inside the declaration.",
        _hex(NUMERAL_COLOUR),
    ),
    (
        "One printed block",
        "Declarations the rules judge separately and the label prints as one paragraph.",
        _hex(GROUP_COLOUR),
    ),
)
"""What the colours mean, in RGB hex, derived from the same constants that draw.

The report prints this. Keeping it here rather than in the template is the same
argument `reports/model.py` makes about the advisory block: a legend maintained
beside the renderer drifts from the pen the first time a colour is adjusted, and
a legend that mislabels an evidence exhibit is worse than none.
"""


@dataclass(frozen=True, slots=True)
class Annotation:
    """The drawn image, or an honest account of why there is not one."""

    image: Any
    available: bool
    boxes: int = 0
    """Named declarations: boxed, numbered, listed in the key, coloured by verdict."""

    context_boxes: int = 0
    """Text read but not classified: outlined thinly, never captioned."""

    regions: int = 0
    """Enclosing regions drawn around a printed block. Usually 0 or 1."""

    label_box: tuple[int, int, int, int] | None = None
    """Where the photograph sits inside the finished exhibit, as (x, y, w, h).

    The exhibit is a composite now, so "the whole frame is the package" — which
    is how `api.scanning.prepare_annotation` tells face redaction that a face on
    a rectified label is printed artwork rather than a bystander — is no longer
    the same rectangle as the image. Passing the composite's full extent instead
    would hand redaction a package box covering the key panel, which is not a
    package.
    """

    detail: str = ""


def _cv2() -> Any | None:
    try:
        import cv2
    except Exception:  # pragma: no cover - OpenCV is a hard dependency of vision/
        return None
    return cv2


def field_label(name: str) -> str:
    return FIELD_LABELS.get(name, name.replace("_", " ").capitalize())


def measurement_for(declaration: Any) -> str:
    """The millimetre line, or an empty string when nothing was measured.

    Tier C measured nothing and printing a figure would invent one.
    """
    height_mm = getattr(declaration, "height_mm", None)
    if height_mm is None:
        return ""
    tolerance = getattr(declaration, "height_mm_tolerance", None)
    if tolerance is None:
        return f"{height_mm:.2f} mm"
    return f"{height_mm:.2f} +/- {tolerance:.2f} mm"


def caption_for(declaration: Any) -> str:
    """The one-line form: field name and measurement together.

    Still the caption on the narrow path, where the label is too small for a key
    panel beside it and text has to go back onto the photograph. ASCII only —
    see the module docstring.
    """
    label = field_label(getattr(declaration, "field", "other"))
    measured = measurement_for(declaration)
    return f"{label}  {measured}" if measured else label


def _scaled(cv2: Any, image: Any) -> Any:
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= MAX_EDGE_PX:
        return image.copy()
    factor = MAX_EDGE_PX / float(longest)
    return cv2.resize(
        image,
        (max(1, round(width * factor)), max(1, round(height * factor))),
        interpolation=cv2.INTER_AREA,
    )


def _draw_caption(
    cv2: Any, canvas: Any, text: str, *, x: int, y: int, colour: Any, scale: float
) -> None:
    """A filled chip with the text on it, laid on the photograph.

    The fallback for a label too narrow to carry a key panel beside it. Filled
    rather than plain text: a caption drawn straight over packaging artwork is
    unreadable exactly where the artwork is busy, which is most of the time.
    """
    thickness = max(1, round(scale * 1.6))
    (width, height), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    pad = max(2, round(scale * 4))
    top = y - height - baseline - 2 * pad
    if top < 0:
        # No room above the box — the declaration sits at the very top of the
        # label — so the chip goes inside it rather than off the image.
        top = y
    left = max(0, min(x, canvas.shape[1] - width - 2 * pad))
    cv2.rectangle(
        canvas,
        (left, top),
        (left + width + 2 * pad, top + height + baseline + 2 * pad),
        colour,
        -1,
    )
    cv2.putText(
        canvas,
        text,
        (left + pad, top + height + pad),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (255, 255, 255),
        thickness,
        cv2.LINE_AA,
    )


# ---------------------------------------------------------------------------
# Laying out the key
# ---------------------------------------------------------------------------

MIN_LABEL_PX_FOR_KEY = 420
"""Below this the label is a crop rather than a panel, a key beside it would be
wider than the evidence, and captions go back on the photograph."""

KEY_FRACTION = 0.46
"""The key's width as a fraction of the label's. Wide enough for "Storage or
usage instruction" and a status token on one line at a readable size."""

MIN_KEY_PX = 340

MAX_KEY_COLUMNS = 3
"""Past three the rows are too narrow for "Storage or usage instruction" and
the exhibit is a spreadsheet."""

MAX_KEY_COLUMNS_BESIDE = 2
"""Lower, because beside a portrait label every extra column is width the
photograph does not get. Three of them put a 600 px label next to 1020 px of
list, which is a table with a picture attached rather than an exhibit."""


def _boxed(declarations: Sequence[Any]) -> tuple[list[Any], list[Any]]:
    """Split into (named, unnamed), dropping anything without geometry.

    A declaration reaches here from a pydantic model or, on a replayed cache
    hit, from something looser. Every read is a `getattr` with a default for
    that reason.
    """
    named: list[Any] = []
    unnamed: list[Any] = []
    for declaration in declarations:
        if getattr(declaration, "box", None) is None:
            continue
        if getattr(declaration, "field", "other") == "other":
            unnamed.append(declaration)
        else:
            named.append(declaration)
    return named, unnamed


def _ordered(named: Sequence[Any]) -> list[tuple[str, list[Any]]]:
    """Group into families in `FAMILIES` order, each family in reading order."""
    rank = {
        field: (index, position)
        for index, (_title, fields) in enumerate(FAMILIES)
        for position, field in enumerate(fields)
    }
    titles = {field: title for title, fields in FAMILIES for field in fields}

    grouped: dict[str, list[Any]] = {}
    for declaration in named:
        grouped.setdefault(titles.get(declaration.field, "Other declarations"), []).append(
            declaration
        )

    def order(declaration: Any) -> tuple[int, int, float]:
        # Position inside the family first, then down the label: two
        # declarations of the same kind read top to bottom.
        family, position = rank.get(declaration.field, (len(FAMILIES), 0))
        return (family, position, float(declaration.box.y))

    out: list[tuple[str, list[Any]]] = []
    for title, _fields in (*FAMILIES, ("Other declarations", ())):
        rows = grouped.get(title)
        if rows:
            out.append((title, sorted(rows, key=order)))
    return out


def _address_region(named: Sequence[Any], factor: float) -> tuple[int, int, int, int] | None:
    """The longest run of address lines the label prints one under another.

    `None` when no two of them are adjacent — which is the common case on a
    front panel, and on a back panel where the address and the consumer-care
    telephone number are printed at opposite ends.
    """
    boxes = sorted((d.box for d in named if d.field in ADDRESS_BLOCK), key=lambda b: b.y)
    if len(boxes) < 2:
        return None

    def adjacent(above: Any, below: Any) -> bool:
        gap = below.y - (above.y + above.h)
        overlap = min(above.x + above.w, below.x + below.w) - max(above.x, below.x)
        narrower = max(1.0, min(above.w, below.w))
        return (
            gap <= max(above.h, below.h) * _BLOCK_GAP_LINES
            and overlap > narrower * _BLOCK_OVERLAP
        )

    best: list[Any] = []
    run = [boxes[0]]
    for box in boxes[1:]:
        if adjacent(run[-1], box):
            run.append(box)
        else:
            best = run if len(run) > len(best) else best
            run = [box]
    best = run if len(run) > len(best) else best

    if len(best) < 2:
        return None

    left = min(b.x for b in best)
    top = min(b.y for b in best)
    right = max(b.x + b.w for b in best)
    bottom = max(b.y + b.h for b in best)
    return (
        round(left * factor),
        round(top * factor),
        round((right - left) * factor),
        round((bottom - top) * factor),
    )


def _fitted(cv2: Any, texts: Sequence[str], *, width: int, scale: float, thickness: int) -> float:
    """One scale that fits every string in `texts`, so the key is not ragged."""
    trial = scale
    while trial > 0.36:
        if all(
            cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, trial, thickness)[0][0] <= width
            for text in texts
        ):
            return trial
        trial -= 0.03
    return 0.36


def _wrapped(cv2: Any, text: str, *, width: int, scale: float, thickness: int, limit: int) -> list:
    """Break on spaces to fit `width`, in at most `limit` lines.

    The summary line used to be ellipsised, which on a narrow key produced
    "6 line(s) read but n..." on a document that is supposed to account for
    everything the recogniser saw.
    """
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        fits = cv2.getTextSize(candidate, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)[0][0] <= width
        if fits or not current:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) == limit:
            break
    if current and len(lines) < limit:
        lines.append(current)
    if not lines:
        return [""]
    lines[-1] = _clipped(cv2, lines[-1], width=width, scale=scale, thickness=thickness)
    return lines


def _clipped(cv2: Any, text: str, *, width: int, scale: float, thickness: int) -> str:
    """Last resort for a single over-long string: ellipsise it in ASCII."""
    if cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)[0][0] <= width:
        return text
    clipped = text
    while clipped:
        clipped = clipped[:-1]
        candidate = clipped + "..."
        if cv2.getTextSize(candidate, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)[0][0] <= width:
            return candidate
    return ""


def _put(
    cv2: Any, canvas: Any, text: str, *, x: int, y: int, scale: float, colour: Any, thickness: int
) -> None:
    """Text by its top-left corner rather than its baseline, which is how every
    caller here thinks about it."""
    (_w, height), _baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    cv2.putText(
        canvas,
        text,
        (x, y + height),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        colour,
        thickness,
        cv2.LINE_AA,
    )


def _muted(colour: tuple[int, int, int], toward: tuple[int, int, int], amount: float) -> tuple:
    return tuple(round(c * (1.0 - amount) + t * amount) for c, t in zip(colour, toward, strict=True))


# ---------------------------------------------------------------------------
# The pen
# ---------------------------------------------------------------------------


def draw(
    image: Any,
    declarations: Sequence[Any],
    *,
    statuses: Mapping[str, str] | None = None,
) -> Annotation:
    """Draw the label and, beside it, the key that says what was marked.

    `statuses` maps a field name to the worst status any countable verdict
    reached for it, and only chooses a colour. A field with no verdict — because
    no rule covers it, or every rule returned NO_DATA — is drawn grey, which is
    the truthful appearance: we found the text and reached no conclusion about
    it.
    """
    cv2 = _cv2()
    if cv2 is None:  # pragma: no cover
        return Annotation(image=None, available=False, detail="OpenCV is not installed")
    if image is None:
        return Annotation(image=None, available=False, detail="no rectified label to draw on")

    import numpy as np

    label = _scaled(cv2, image)
    factor = label.shape[1] / float(max(1, image.shape[1]))
    statuses = statuses or {}

    label_h, label_w = label.shape[:2]
    # Everything scales with the image, so a 700 px crop and a 1600 px label get
    # the same apparent line weight.
    stroke = max(2, round(label_w / 450.0))

    named, unnamed = _boxed(declarations)
    families = _ordered(named)
    numbers = {id(d): n for n, d in enumerate((d for _t, rows in families for d in rows), start=1)}

    # -- the photograph ----------------------------------------------------
    # Unnamed text first, so the declarations that carry verdicts are drawn
    # over it rather than under it.
    for declaration in unnamed:
        box = declaration.box
        cv2.rectangle(
            label,
            (round(box.x * factor), round(box.y * factor)),
            (round((box.x + box.w) * factor), round((box.y + box.h) * factor)),
            CONTEXT_COLOUR,
            max(1, stroke - 1),
        )

    # The printed block, under the declaration boxes: it is context for them,
    # not a finding of its own.
    region = _address_region(named, factor)
    if region is not None:
        margin = max(3, stroke * 2)
        rx, ry, rw, rh = region
        cv2.rectangle(
            label,
            (max(0, rx - margin), max(0, ry - margin)),
            (min(label_w - 1, rx + rw + margin), min(label_h - 1, ry + rh + margin)),
            GROUP_COLOUR,
            max(1, stroke - 1),
        )

    colours: dict[int, tuple[int, int, int]] = {}
    for declaration in named:
        box = declaration.box
        x, y = round(box.x * factor), round(box.y * factor)
        w = max(1, round(box.w * factor))
        h = max(1, round(box.h * factor))
        colour = BOX_COLOURS.get(statuses.get(declaration.field, ""), DEFAULT_COLOUR)
        colours[id(declaration)] = colour
        cv2.rectangle(label, (x, y), (x + w, y + h), colour, stroke)

        numerals = getattr(declaration, "numeral_box", None)
        if numerals is not None:
            cv2.rectangle(
                label,
                (round(numerals.x * factor), round(numerals.y * factor)),
                (
                    round((numerals.x + numerals.w) * factor),
                    round((numerals.y + numerals.h) * factor),
                ),
                NUMERAL_COLOUR,
                max(1, stroke - 1),
            )

    # -- the narrow path ---------------------------------------------------
    # A crop too small to carry a key beside it keeps the old behaviour rather
    # than losing its captions altogether.
    if label_w < MIN_LABEL_PX_FOR_KEY or not named:
        text_scale = max(0.35, label_w / 1900.0)
        for declaration in named:
            box = declaration.box
            _draw_caption(
                cv2,
                label,
                caption_for(declaration),
                x=round(box.x * factor),
                y=round(box.y * factor),
                colour=colours[id(declaration)],
                scale=text_scale,
            )
        return Annotation(
            image=label,
            available=True,
            boxes=len(named),
            context_boxes=len(unnamed),
            regions=1 if region is not None else 0,
            label_box=(0, 0, label_w, label_h),
            detail="captioned on the label: too narrow for a key panel",
        )

    # -- the key -----------------------------------------------------------
    #
    # Where the key goes is decided by the label's shape, and it matters more
    # than it sounds. A declaration panel is usually wider than it is tall, and
    # a key stacked in one tall column beside it produced an exhibit twice as
    # tall as the photograph with the lower half of it blank paper. So the key
    # is a block of columns, placed beside a portrait label and underneath a
    # landscape one, sized to leave as little dead paper as a list of eighteen
    # rows allows.
    beside = label_h >= label_w
    if beside:
        columns_wanted = 1
        col_w = max(MIN_KEY_PX, round(label_w * KEY_FRACTION))
    else:
        columns_wanted = max(2, min(MAX_KEY_COLUMNS, label_w // (MIN_KEY_PX + 60)))
        col_w = label_w // columns_wanted

    pad = max(8, round(col_w / 26.0))
    base = max(0.42, min(0.86, col_w / 560.0))
    thin = max(1, round(base * 1.4))
    bold = thin + 1

    # Big enough to read the number on a printed page, small enough that it
    # sits in the margin beside a 2 mm line of type rather than swallowing it.
    badge_r = max(10, round(label_w / 85.0))
    line_h = cv2.getTextSize("Mg", cv2.FONT_HERSHEY_SIMPLEX, base, thin)[0][1]
    chip = round(line_h * 1.9)

    heading_h = round(line_h * 2.4)
    row_h = round(line_h * 2.9)

    def token_for(declaration: Any) -> str:
        return statuses.get(declaration.field, "") or "NO DATA"

    status_w = max(
        cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, base * 0.8, thin)[0][0]
        for text in {*(token_for(d) for d in named), "NO DATA"}
    )
    name_w = col_w - chip - status_w - 4 * pad
    name_scale = _fitted(
        cv2,
        [field_label(d.field) for d in named],
        width=name_w,
        scale=base,
        thickness=bold,
    )

    used_colours: list[tuple[str, tuple[int, int, int]]] = []

    def remember(name: str, colour: tuple[int, int, int]) -> None:
        if all(existing != colour for _label, existing in used_colours):
            used_colours.append((name, colour))

    for declaration in named:
        status = statuses.get(declaration.field, "")
        remember(STATUS_WORDS.get(status, STATUS_WORDS["NO_DATA"]), colours[id(declaration)])
        if getattr(declaration, "numeral_box", None) is not None:
            remember("Glyphs measured", NUMERAL_COLOUR)
    if unnamed:
        remember("Read, not identified", CONTEXT_COLOUR)
    if region is not None:
        remember("One printed block", GROUP_COLOUR)

    # -- what goes in the columns, and how tall each piece is ---------------
    items: list[tuple[str, Any, int]] = []
    for title, rows in families:
        items.append(("heading", title, heading_h))
        items.extend(("row", declaration, row_h) for declaration in rows)
    body_h = sum(height for _kind, _payload, height in items)

    def pack(capacity: int) -> list[list[tuple[str, Any, int]]]:
        """Greedy, with two rules that keep a column break from reading badly.

        A heading is never left at the foot of a column with nothing under it,
        and a family that has to be split repeats its heading -- so a reader
        who starts at the top of the second column is not looking at rows whose
        subject was printed somewhere else.
        """
        packed: list[list[tuple[str, Any, int]]] = [[]]
        used = 0
        title = ""
        for kind, payload, height in items:
            if kind == "heading":
                title = str(payload)
            needed = height + (row_h if kind == "heading" else 0)
            if packed[-1] and used + needed > capacity:
                packed.append([])
                used = 0
                if kind == "row" and title:
                    packed[-1].append(("heading", f"{title} (cont.)", heading_h))
                    used += heading_h
            packed[-1].append((kind, payload, height))
            used += height
        return packed

    def legend_height(columns: int) -> int:
        rows = -(-len(used_colours) // max(1, columns))
        return round(line_h * 1.9) * (rows + 1) + pad

    summary = f"{len(named)} declaration(s) identified"
    if unnamed:
        summary += f", {len(unnamed)} line(s) read but not identified"

    # -- how many columns, and how tall ------------------------------------
    summary_lines = _wrapped(
        cv2,
        summary,
        width=col_w * columns_wanted - 2 * pad,
        scale=base * 0.72,
        thickness=thin,
        limit=2,
    )
    header_h = round(line_h * 2.2) + len(summary_lines) * round(line_h * 1.6) + pad

    columns = columns_wanted
    if beside:
        capacity = label_h - header_h - legend_height(columns) - 3 * pad
        while columns < MAX_KEY_COLUMNS_BESIDE and (
            capacity < row_h * 3 or len(pack(capacity)) > columns
        ):
            columns += 1
            capacity = label_h - header_h - legend_height(columns) - 3 * pad
        if capacity < row_h * 3 or len(pack(capacity)) > columns:
            # A short label with a long list: taller than the photograph after
            # all. Let the canvas grow rather than drop a row.
            capacity = max(row_h * 3, -(-body_h // columns) + heading_h + row_h)
    else:
        capacity = max(row_h * 3, -(-body_h // columns) + heading_h + row_h)
    while len(pack(capacity)) > columns:
        capacity += row_h

    packed = pack(capacity)
    columns = max(1, len(packed))
    # Trim to what the columns actually came to. `capacity` is an upper bound
    # chosen before packing, and on a label with one declaration on it the
    # difference was three empty rows of paper under the list.
    capacity = max(row_h, max(sum(h for _k, _p, h in column) for column in packed))
    block_w = col_w * columns
    legend_h = legend_height(columns)
    block_h = header_h + capacity + legend_h + 3 * pad
    if beside:
        # Keep the legend on the foot of the panel rather than floating it in
        # the middle of a tall one.
        block_h = max(block_h, label_h)

    if beside:
        canvas_w, canvas_h = label_w + block_w, max(label_h, block_h)
        block_x, block_y = label_w, 0
    else:
        canvas_w, canvas_h = max(label_w, block_w), label_h + block_h
        block_x, block_y = 0, label_h

    canvas = np.full((canvas_h, canvas_w, 3), PANEL_COLOUR, dtype=np.uint8)
    canvas[0:label_h, 0:label_w] = label
    if beside:
        cv2.line(canvas, (label_w, 0), (label_w, canvas_h - 1), RULE_COLOUR, 1)
    else:
        cv2.line(canvas, (0, label_h), (canvas_w - 1, label_h), RULE_COLOUR, 1)

    # -- where every row's chip will land ----------------------------------
    #
    # Worked out before anything is drawn, so a leader line can be laid down
    # first and the key's text can go on top of it. Drawn in the other order,
    # the line for a contravention was ruled straight through the heading.
    anchors: dict[int, tuple[int, int]] = {}
    top = block_y + header_h + pad
    for index, column in enumerate(packed):
        cursor = top
        for kind, payload, height in column:
            if kind == "row":
                anchors[id(payload)] = (
                    block_x + index * col_w + pad,
                    cursor + round((height - chip) / 2) + chip // 2,
                )
            cursor += height

    # -- leader lines, for the findings only -------------------------------
    for declaration in named:
        if statuses.get(declaration.field) not in ("FAIL", "REVIEW"):
            continue
        anchor = anchors.get(id(declaration))
        if anchor is None:  # pragma: no cover - every named row gets one
            continue
        box = declaration.box
        if beside:
            start = (
                min(label_w - 1, round((box.x + box.w) * factor)),
                round((box.y + box.h / 2.0) * factor),
            )
        else:
            start = (
                round((box.x + box.w / 2.0) * factor),
                min(label_h - 1, round((box.y + box.h) * factor)),
            )
        cv2.line(
            canvas,
            start,
            anchor,
            _muted(colours[id(declaration)], PANEL_COLOUR, 0.6),
            max(1, stroke - 1),
            cv2.LINE_AA,
        )

    # -- the header --------------------------------------------------------
    y = block_y + pad
    _put(
        cv2,
        canvas,
        "MARKED ON THIS LABEL",
        x=block_x + pad,
        y=y,
        scale=base * 0.92,
        colour=INK_COLOUR,
        thickness=bold,
    )
    y += round(line_h * 2.2)
    for line in summary_lines:
        _put(
            cv2,
            canvas,
            line,
            x=block_x + pad,
            y=y,
            scale=base * 0.72,
            colour=MUTED_COLOUR,
            thickness=thin,
        )
        y += round(line_h * 1.6)

    # -- the columns -------------------------------------------------------
    for index, column in enumerate(packed):
        left = block_x + index * col_w + pad
        right = block_x + (index + 1) * col_w - pad
        y = top
        for kind, payload, height in column:
            if kind == "heading":
                _put(
                    cv2,
                    canvas,
                    str(payload).upper(),
                    x=left,
                    y=y + round(line_h * 0.7),
                    scale=base * 0.68,
                    colour=MUTED_COLOUR,
                    thickness=thin,
                )
                rule_y = y + height - round(line_h * 0.45)
                cv2.line(canvas, (left, rule_y), (right, rule_y), RULE_COLOUR, 1)
                y += height
                continue

            declaration = payload
            colour = colours[id(declaration)]
            chip_x, chip_y = left, y + round((height - chip) / 2)
            cv2.rectangle(canvas, (chip_x, chip_y), (chip_x + chip, chip_y + chip), colour, -1)
            digits = str(numbers[id(declaration)])
            (dw, dh), _b = cv2.getTextSize(digits, cv2.FONT_HERSHEY_SIMPLEX, base * 0.62, bold)
            cv2.putText(
                canvas,
                digits,
                (chip_x + (chip - dw) // 2, chip_y + (chip + dh) // 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                base * 0.62,
                (255, 255, 255),
                bold,
                cv2.LINE_AA,
            )
            _put(
                cv2,
                canvas,
                _clipped(
                    cv2,
                    field_label(declaration.field),
                    width=name_w,
                    scale=name_scale,
                    thickness=bold,
                ),
                x=left + chip + pad,
                y=y + round(line_h * 0.35),
                scale=name_scale,
                colour=INK_COLOUR,
                thickness=bold,
            )

            token = token_for(declaration)
            (tw, _th), _b = cv2.getTextSize(token, cv2.FONT_HERSHEY_SIMPLEX, base * 0.8, thin)
            _put(
                cv2,
                canvas,
                token,
                x=right - tw,
                y=y + round(line_h * 0.45),
                scale=base * 0.8,
                colour=colour,
                thickness=thin,
            )

            measured = measurement_for(declaration) or "no scale: not measured"
            _put(
                cv2,
                canvas,
                _clipped(
                    cv2,
                    measured,
                    width=right - left - chip - pad,
                    scale=base * 0.72,
                    thickness=thin,
                ),
                x=left + chip + pad,
                y=y + round(line_h * 1.75),
                scale=base * 0.72,
                colour=MUTED_COLOUR,
                thickness=thin,
            )
            y += height

    # -- badges, last, and outside the box they number ----------------------
    #
    # Inside the box was the first attempt, and it put a coloured disc over the
    # first word of the declaration it was pointing at, which is the thing this
    # whole restyle exists to stop doing.
    placed: list[tuple[int, int]] = []
    for declaration in named:
        box = declaration.box
        cy = round((box.y + box.h / 2.0) * factor)
        cx = round(box.x * factor) - badge_r - stroke
        while any(abs(cx - px) < badge_r * 2 and abs(cy - py) < badge_r * 2 for px, py in placed):
            cx -= badge_r * 2 + 2
        cx = max(badge_r, min(label_w - badge_r - 1, cx))
        cy = max(badge_r, min(label_h - badge_r - 1, cy))
        placed.append((cx, cy))

        cv2.circle(canvas, (cx, cy), badge_r, colours[id(declaration)], -1)
        cv2.circle(canvas, (cx, cy), badge_r, (255, 255, 255), max(1, stroke // 2))
        digits = str(numbers[id(declaration)])
        (dw, dh), _b = cv2.getTextSize(digits, cv2.FONT_HERSHEY_SIMPLEX, base * 0.55, bold)
        cv2.putText(
            canvas,
            digits,
            (cx - dw // 2, cy + dh // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            base * 0.55,
            (255, 255, 255),
            bold,
            cv2.LINE_AA,
        )

    # -- the legend, naming only the colours this drawing used --------------
    y = block_y + block_h - legend_h + pad
    _put(
        cv2,
        canvas,
        "WHAT THE COLOURS MEAN",
        x=block_x + pad,
        y=y,
        scale=base * 0.68,
        colour=MUTED_COLOUR,
        thickness=thin,
    )
    y += round(line_h * 1.9)
    swatch = round(line_h * 1.1)
    per_column = max(1, -(-len(used_colours) // columns))
    for index, (name, colour) in enumerate(used_colours):
        column, row = divmod(index, per_column)
        left = block_x + column * col_w + pad
        row_y = y + row * round(line_h * 1.9)
        cv2.rectangle(canvas, (left, row_y), (left + swatch, row_y + swatch), colour, -1)
        _put(
            cv2,
            canvas,
            _clipped(cv2, name, width=col_w - swatch - 3 * pad, scale=base * 0.66, thickness=thin),
            x=left + swatch + pad,
            y=row_y,
            scale=base * 0.66,
            colour=INK_COLOUR,
            thickness=thin,
        )

    return Annotation(
        image=canvas,
        available=True,
        boxes=len(named),
        context_boxes=len(unnamed),
        regions=1 if region is not None else 0,
        label_box=(0, 0, label_w, label_h),
    )



def _attr(verdict: Any, name: str, default: Any = None) -> Any:
    """Verdicts reach here as pydantic models from the route and as dicts from a
    replayed cache hit. One accessor rather than two code paths."""
    if isinstance(verdict, dict):
        return verdict.get(name, default)
    return getattr(verdict, name, default)


def statuses_from(verdicts: Sequence[Any]) -> dict[str, str]:
    """Worst countable status per field. FAIL beats REVIEW beats the rest.

    **Advisory and suppressed verdicts are excluded** — the same three counting
    rules `api/analytics.py` and `reports/model.py` keep. A `250 ML` painting the
    net-quantity box red would tell an officer, in the most immediate way a
    document can, that a formatting note is a contravention.
    """
    rank = {"FAIL": 0, "REVIEW": 1, "PASS": 2, "NO_DATA": 3}
    worst: dict[str, str] = {}
    for verdict in verdicts:
        name = _attr(verdict, "field")
        if not name:
            continue
        if _attr(verdict, "advisory", False) or _attr(verdict, "suppressed_by"):
            continue
        status = _attr(verdict, "status", "")
        if status not in rank:
            continue
        if name not in worst or rank[status] < rank[worst[name]]:
            worst[name] = status
    return worst


__all__ = [
    "ADDRESS_BLOCK",
    "BOX_COLOURS",
    "FAMILIES",
    "FIELD_LABELS",
    "GROUP_COLOUR",
    "LEGEND",
    "MAX_EDGE_PX",
    "STATUS_WORDS",
    "Annotation",
    "caption_for",
    "draw",
    "field_label",
    "measurement_for",
    "statuses_from",
]
