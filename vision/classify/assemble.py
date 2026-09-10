"""Assemble the `DeclarationSet` — the one thing that crosses the wall.

    "The rules engine sits behind a wall. It receives a `DeclarationSet` and
     nothing else."                                       -- section 8

Everything upstream of this module works in pixels; everything downstream works
in law. This is the seam, and it is the last place a pixel may be touched.

**Two entry points, one output.** `from_lines` serves the photo and bulk-image
channels; `from_listing_text` serves the third input the problem statement
names — an e-commerce listing with no image at all. They produce the same type,
which is why that third channel is an afternoon's work rather than a rewrite:

    "The PS names three inputs and one is pure text from an e-commerce listing.
     If OCR is wired straight into the rules, that third channel becomes a
     rewrite instead of an afternoon's work."             -- section 3

**`raw_text` is not a convenience field.** The engine's locate-then-validate
logic asks "is this declaration anywhere on the pack?" against the whole label,
not against a single classified line. If `raw_text` were omitted, a pack whose
MRP we read but mis-classified would be reported as having no MRP at all — a
false accusation caused by our own classifier. So every line contributes to it
regardless of how it was labelled.
"""

from __future__ import annotations

from datetime import UTC, datetime

from contracts import (
    Declaration,
    DeclarationSet,
    DegradationTier,
    LabelGeometry,
    SourceChannel,
)
from vision.classify import regex_tier
from vision.classify.associate import Association, associate
from vision.classify.regex_tier import FieldGuess
from vision.measure.orientation import glyph_axis
from vision.measure.to_mm import to_mm
from vision.ocr.script import script_of_text
from vision.types import Box, OcrLine, Point, ScaleEstimate

MIN_EMIT_CONFIDENCE = 0.25
"""Below this a line becomes `other` rather than a named declaration.

It still reaches `raw_text`, so the engine can still find it when asking
whether a declaration exists. What we decline to do is *assert* which
declaration it is on evidence this thin."""


MEASURED_ON_NUMERALS = frozenset({"mrp", "net_quantity"})
"""Fields whose statutory height is the height of their FIGURES.

Rule 7(2) Table I prescribes the height of the numerals of the net quantity,
and Rule 9's price declaration attaches to the figure. On a pack reading
`Net Wt. 500 g` the words and the digits are routinely set at different sizes,
so measuring the words measures the wrong thing.

Membership here has one consequence: these two fields are measured from
`numeral_height_px` alone, and report no height at all when it is absent,
rather than falling back to the height of their own label. Every other field is
a phrase, and its own cap height is what the rules mean.
"""


def _declaration_from_line(
    line: OcrLine,
    guess: FieldGuess,
    scale: ScaleEstimate,
    *,
    rectified: bool,
    is_embossed: bool,
) -> Declaration:
    # Rule 7(2) prescribes the height of the NUMERALS. `height_for_rules_px`
    # encodes that preference on the contract, and the millimetre conversion
    # must use the same quantity or the report would show one number and the
    # verdict would rest on another.
    #
    # `glyph_axis`, not `.h`. Text running down the side of a pack has its glyph
    # height across the box's *width*; `.h` there is how far the line runs, so
    # the fallback would report a 400 px "cap height" for 3 mm print. The
    # rotation is consulted rather than inferred from the box's shape, because a
    # single upright digit is also taller than it is wide.
    height_px = line.cap_height_px or glyph_axis(line.box, line.rotation_k)

    if guess.field in MEASURED_ON_NUMERALS:
        # The figure's own height, or nothing. `numeral_height_px` is `None`
        # in two different situations and both of them mean the same thing
        # here: the line carries no digit at all -- `'MRPर:'` and `'MRP USP:'`
        # are whole crops from the ruler set, the label half of a declaration
        # whose price was proposed as a separate region -- or it carries one
        # but the figures could not be separated from the rest of the ink.
        #
        # Falling back to the line's cap height in either case measures the
        # *word* `MRP` and reports it as the price's height, which is how a
        # 5.00 mm declaration came back as 1.38 mm and a 2.50 mm one as
        # 5.32 mm: wrong in both directions, because a label's size has
        # nothing to do with its figure's. Presence still passes -- the
        # declaration is on the pack and was found -- and the height rules
        # return NO_DATA, which is what section 14's refusal to fabricate a
        # measurement means when the arithmetic rather than a model is doing
        # the fabricating.
        measurable_px: float | None = line.numeral_height_px
    else:
        # Every other field is a phrase, and its own cap height is the
        # quantity the rules mean.
        measurable_px = height_px

    height_mm, tolerance = (
        to_mm(measurable_px, scale, rectified=rectified) if measurable_px is not None else (None, None)
    )

    return Declaration(
        field=guess.field,
        text=line.text,
        script=line.script,
        box=line.box,
        height_px=height_px,
        height_mm=height_mm,
        height_mm_tolerance=tolerance,
        scale_tier=scale.tier if scale.is_measurable else None,
        ocr_confidence=max(0.0, min(1.0, line.confidence)),
        field_confidence=max(0.0, min(1.0, guess.confidence)),
        contrast_ratio=line.contrast_ratio,
        char_boxes=line.char_boxes,
        text_rotation_k=line.rotation_k,
        numeral_box=line.numeral_box,
        numeral_height_px=line.numeral_height_px,
        is_embossed=is_embossed,
    )


ASSOCIATION_CONFIDENCE = 0.9
"""How much of the label's own confidence an associated declaration keeps.

An association is an inference from adjacency on top of a pattern match, so it
cannot be worth as much as a line that declared the field outright. It is
scaled rather than replaced by a constant, because a label read at 0.4 and a
label read at 0.95 should not arrive at the rulepack looking alike.
"""


def _joined_line(label: OcrLine, value: OcrLine) -> OcrLine:
    """One line from a label region and the value region beside it.

    The text is joined so the rulepack's format patterns see the whole
    declaration; every *pixel* comes from the value, because the numerals are
    what the height rules measure.

    `char_boxes` are concatenated rather than taken from either side, because
    `min_width_ratio` consumes them positionally against `text` and a list
    describing only half the string would compare every character against the
    wrong glyph. When either side could not be segmented the whole list is
    dropped and Rule 7(3) returns NO_DATA, which is the same answer it gives
    for any line it cannot align -- and a great deal better than aligning it
    to the wrong glyphs.
    """
    text = f"{label.text.strip()} {value.text.strip()}"

    boxes: list[Box] = []
    if (
        len(label.char_boxes) == len(label.text)
        and len(value.char_boxes) == len(value.text)
        and label.char_boxes
        and value.char_boxes
    ):
        # A real box for the joining space, so the positional contract holds.
        # The check skips spaces, so its dimensions are never compared against
        # a threshold; they must merely be positive.
        last = label.char_boxes[-1]
        boxes = [
            *label.char_boxes,
            Box(x=last.x2, y=last.y, w=1.0, h=1.0, panel_id=last.panel_id),
            *value.char_boxes,
        ]

    x0 = min(label.box.x, value.box.x)
    y0 = min(label.box.y, value.box.y)
    x1 = max(label.box.x2, value.box.x2)
    y1 = max(label.box.y2, value.box.y2)

    return OcrLine(
        text=text,
        # The union, for the placement rules -- `same_panel` and `clear_space`
        # ask where the declaration is, and it is in both regions. No height
        # rule reads this box: they read `numeral_height_px`.
        box=Box(x=x0, y=y0, w=x1 - x0, h=y1 - y0, panel_id=value.box.panel_id),
        confidence=min(label.confidence, value.confidence),
        script=value.script,
        char_boxes=boxes,
        panel_id=value.panel_id,
        engine=value.engine,
        cap_height_px=value.cap_height_px,
        numeral_box=value.numeral_box,
        numeral_height_px=value.numeral_height_px,
        contrast_ratio=value.contrast_ratio,
        rotation_k=value.rotation_k,
    )


def classify_lines(
    lines: list[OcrLine],
    *,
    model_tier_predictions: dict[int, FieldGuess] | None = None,
) -> list[FieldGuess]:
    """Regex first, then the layout head only where regex could not resolve.

    Section 15b: *"measure before building the model."* The model's predictions
    are passed in rather than fetched, so the pipeline can run entirely without
    it and the comparison "how much does the head actually add?" is a matter of
    calling this function twice.
    """
    guesses = [regex_tier.classify_line(line) for line in lines]

    for index, prediction in (model_tier_predictions or {}).items():
        if 0 <= index < len(guesses) and guesses[index].field == "other":
            guesses[index] = prediction

    return guesses


def address_candidates(lines: list[OcrLine], guesses: list[FieldGuess]) -> list[int]:
    """Lines the layout head should look at: unresolved, but address-shaped."""
    return [
        index
        for index, (line, guess) in enumerate(zip(lines, guesses, strict=True))
        if guess.field == "other" and regex_tier.is_address_like(line.text)
    ]


def from_lines(
    lines: list[OcrLine],
    scale: ScaleEstimate,
    *,
    source: SourceChannel = "photo",
    coverage: float = 0.0,
    degradation_tier: DegradationTier = "L0",
    pdp_polygon: list[Point] | None = None,
    label_area_cm2: float | None = None,
    rectified: bool = True,
    is_embossed: bool = False,
    model_versions: dict[str, str] | None = None,
    captured_at: datetime | None = None,
    model_tier_predictions: dict[int, FieldGuess] | None = None,
) -> DeclarationSet:
    """Build the engine's only input from recognised lines."""
    guesses = classify_lines(lines, model_tier_predictions=model_tier_predictions)

    # A label read as its own region, and the figure printed beside it, are one
    # declaration. See `vision.classify.associate`.
    joined: dict[int, Association] = {}
    demoted: set[int] = set()
    for pair in associate(lines, guesses):
        joined[pair.value] = pair
        # The label must stop claiming the field, or the pack now declares its
        # MRP twice and `LMPC.MRP.NO_DUPLICATE` fires against a compliant
        # label for a split our own detector introduced.
        demoted.add(pair.label)

    declarations: list[Declaration] = []
    for index, (line, guess) in enumerate(zip(lines, guesses, strict=True)):
        if not line.text.strip():
            continue

        pair = joined.get(index)
        if pair is not None:
            line = _joined_line(lines[pair.label], line)
            guess = FieldGuess(
                pair.field,
                guesses[pair.label].confidence * ASSOCIATION_CONFIDENCE,
                pair.reason,
            )
        elif index in demoted:
            # Its text still reaches `raw_text`, so the engine can still find
            # the declaration when asking whether one exists.
            guess = FieldGuess("other", guess.confidence, f"joined to a figure beside it: {guess.reason}")

        effective = (
            guess
            if guess.confidence >= MIN_EMIT_CONFIDENCE
            else FieldGuess("other", guess.confidence, guess.reason)
        )
        declarations.append(
            _declaration_from_line(
                line, effective, scale, rectified=rectified, is_embossed=is_embossed
            )
        )

    return DeclarationSet(
        source=source,
        declarations=declarations,
        geometry=LabelGeometry(
            label_area_cm2=label_area_cm2,
            pdp_polygon=pdp_polygon,
            mm_per_px=scale.mm_per_px,
            mm_per_px_tolerance=scale.tolerance,
            rectified=rectified,
            scale_tier=scale.tier,
        ),
        coverage=max(0.0, min(1.0, coverage)),
        degradation_tier=degradation_tier,
        captured_at=captured_at or datetime.now(UTC),
        model_versions=model_versions or {},
        # Every line, including the ones we declined to name. See module docstring.
        raw_text="\n".join(line.text for line in lines if line.text.strip()) or None,
    )


def from_listing_text(
    text: str,
    *,
    model_versions: dict[str, str] | None = None,
    captured_at: datetime | None = None,
) -> DeclarationSet:
    """The third input channel: an e-commerce listing, no image, no pixels.

    Every geometric rule returns NO_DATA here — `has_pixels()` is False and the
    engine handles it — while presence, format, unit-symbol and schedule rules
    all run unchanged. That is the payoff of the extraction/decision wall, and
    it is worth demonstrating live: the same 31 rules, the same rulepack, no
    image anywhere.
    """
    lines: list[OcrLine] = []
    for row, raw in enumerate(text.splitlines()):
        stripped = raw.strip()
        if not stripped:
            continue
        lines.append(
            OcrLine(
                text=stripped,
                # A synthetic box. It is never measured: `has_pixels()` is
                # False for this channel, so no geometric rule reads it.
                box=Box(x=0.0, y=float(row * 20), w=float(max(len(stripped), 1)), h=10.0),
                confidence=1.0,
                script=script_of_text(stripped),
                engine="listing_text",
            )
        )

    guesses = classify_lines(lines)
    declarations = [
        Declaration(
            field=guess.field,
            text=line.text,
            script=line.script,
            box=line.box,
            height_px=line.box.h,
            height_mm=None,
            scale_tier=None,
            ocr_confidence=1.0,
            field_confidence=guess.confidence,
        )
        for line, guess in zip(lines, guesses, strict=True)
    ]

    return DeclarationSet(
        source="listing_text",
        declarations=declarations,
        geometry=LabelGeometry(scale_tier="C"),
        coverage=1.0 if declarations else 0.0,
        # L2: no geometry is available, but everything textual works. This is
        # the listing channel's normal state, not a degraded one.
        degradation_tier="L2",
        captured_at=captured_at or datetime.now(UTC),
        model_versions=model_versions or {"channel": "listing_text"},
        raw_text=text,
    )


__all__ = [
    "ASSOCIATION_CONFIDENCE",
    "MIN_EMIT_CONFIDENCE",
    "address_candidates",
    "classify_lines",
    "from_lines",
    "from_listing_text",
]
