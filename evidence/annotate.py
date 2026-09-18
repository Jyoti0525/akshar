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
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MAX_EDGE_PX = 1600
"""Longest side of the stored annotation.

Section 6 budgets roughly 40 KB for the derived crops of a scan. This is one
composited image instead of four to eight separate ones, and 1600 px keeps a
2 mm character legible at full zoom while landing in the same order of
magnitude. Larger would buy nothing: the evidence-grade original is already
stored at full resolution under its own retention rule.
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
    "barcode": "Barcode",
    "unit_sale_price": "Unit sale price",
    "other": "Unclassified text",
}


def _hex(bgr: tuple[int, int, int]) -> str:
    blue, green, red = bgr
    return f"#{red:02x}{green:02x}{blue:02x}"


LEGEND: tuple[tuple[str, str, str], ...] = (
    ("Contravention", "A rule was failed on this declaration.", _hex(BOX_COLOURS["FAIL"])),
    (
        "For examination",
        "The measurement fell inside the measurement error; no contravention is asserted.",
        _hex(BOX_COLOURS["REVIEW"]),
    ),
    ("Checked, no contravention", "Every rule applied to it passed.", _hex(BOX_COLOURS["PASS"])),
    (
        "Read, not identified",
        "Text we recognised but could not attribute to a declaration. No rule was applied to it.",
        _hex(CONTEXT_COLOUR),
    ),
    (
        "No conclusion",
        "Read from the label, but no rule could be applied or all returned NO_DATA.",
        _hex(DEFAULT_COLOUR),
    ),
    (
        "Glyphs measured",
        "The characters whose height was measured, inside the declaration.",
        _hex(NUMERAL_COLOUR),
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
    """Named declarations: boxed, captioned, coloured by verdict."""

    context_boxes: int = 0
    """Text read but not classified: outlined thinly, never captioned."""

    detail: str = ""


def _cv2() -> Any | None:
    try:
        import cv2
    except Exception:  # pragma: no cover - OpenCV is a hard dependency of vision/
        return None
    return cv2


def field_label(name: str) -> str:
    return FIELD_LABELS.get(name, name.replace("_", " ").capitalize())


def caption_for(declaration: Any) -> str:
    """The one line printed above a box. ASCII only — see the module docstring."""
    label = field_label(getattr(declaration, "field", "other"))
    height_mm = getattr(declaration, "height_mm", None)
    if height_mm is None:
        return label
    tolerance = getattr(declaration, "height_mm_tolerance", None)
    if tolerance is None:
        return f"{label}  {height_mm:.2f} mm"
    return f"{label}  {height_mm:.2f} +/- {tolerance:.2f} mm"


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
    """A filled chip with the text on it.

    Filled rather than plain text laid on the photograph: a caption drawn
    straight over packaging artwork is unreadable exactly where the artwork is
    busy, which is most of the time.
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


def draw(
    image: Any,
    declarations: Sequence[Any],
    *,
    statuses: Mapping[str, str] | None = None,
) -> Annotation:
    """Draw every declaration box on a copy of the rectified label.

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

    canvas = _scaled(cv2, image)
    factor = canvas.shape[1] / float(max(1, image.shape[1]))
    statuses = statuses or {}

    # Everything scales with the image, so a 700 px crop and a 1600 px label get
    # the same apparent line weight.
    stroke = max(2, round(canvas.shape[1] / 450.0))
    text_scale = max(0.35, canvas.shape[1] / 1900.0)

    # Unnamed text first, so the declarations that carry verdicts are drawn
    # over it rather than under it.
    context = 0
    for declaration in declarations:
        box = getattr(declaration, "box", None)
        if box is None or getattr(declaration, "field", "other") != "other":
            continue
        cv2.rectangle(
            canvas,
            (round(box.x * factor), round(box.y * factor)),
            (round((box.x + box.w) * factor), round((box.y + box.h) * factor)),
            CONTEXT_COLOUR,
            max(1, stroke - 1),
        )
        context += 1

    drawn = 0
    for declaration in declarations:
        box = getattr(declaration, "box", None)
        if box is None or getattr(declaration, "field", "other") == "other":
            continue
        x = round(box.x * factor)
        y = round(box.y * factor)
        w = max(1, round(box.w * factor))
        h = max(1, round(box.h * factor))
        colour = BOX_COLOURS.get(statuses.get(declaration.field, ""), DEFAULT_COLOUR)
        cv2.rectangle(canvas, (x, y), (x + w, y + h), colour, stroke)

        numerals = getattr(declaration, "numeral_box", None)
        if numerals is not None:
            cv2.rectangle(
                canvas,
                (round(numerals.x * factor), round(numerals.y * factor)),
                (
                    round((numerals.x + numerals.w) * factor),
                    round((numerals.y + numerals.h) * factor),
                ),
                NUMERAL_COLOUR,
                max(1, stroke - 1),
            )

        _draw_caption(
            cv2, canvas, caption_for(declaration), x=x, y=y, colour=colour, scale=text_scale
        )
        drawn += 1

    return Annotation(image=canvas, available=True, boxes=drawn, context_boxes=context)


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
    "BOX_COLOURS",
    "FIELD_LABELS",
    "LEGEND",
    "MAX_EDGE_PX",
    "Annotation",
    "caption_for",
    "draw",
    "field_label",
    "statuses_from",
]
