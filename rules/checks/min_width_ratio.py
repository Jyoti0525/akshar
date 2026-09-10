"""`min_width_ratio` — Rule 7(3) proviso. SCALE-FREE.

"the width of the letter or numeral shall not be less than one third of its
height" -- so this compares PIXELS AGAINST PIXELS. It needs no marker, no
calibration card, no scale recovery and no millimetres at all.

That makes it one of the two rules that survive total failure of scale
recovery, and it is our safety net: if the geometry gamble in week 1 does not
pay off, this and `clear_space` still give an enforcement tool that checks
something no competing project checks, straight from the bare act.

Characters whose glyph is legitimately narrow are excluded -- `1`, `i`, `I`,
`l` and punctuation -- because flagging the `1` in "1 kg" would fire on
essentially every label in India, and a rule that fires on everything is a rule
being read wrong.
"""

from __future__ import annotations

from contracts import Box, Declaration, DeclarationSet, PackageContext, VerdictStatus
from rules.checks._common import category_blocks, measured_for
from rules.models import CheckOutcome, Rule, Rulepack


def _ratio(decl: Declaration, box: Box) -> float:
    """Width over height *of the glyph*, which is not always of the box.

    Where the declaration runs down the side of the pack, a character's height
    lies across the box's width. Dividing the box's own sides there inverts the
    ratio -- a 6x18 `5` reads 3.0 rather than 0.33 -- and a check that inverts
    is worse than a check that abstains, because it reports PASS on exactly the
    characters the proviso was written to catch.
    """
    width, height = decl.glyph_size(box)
    return width / height if height > 0 else 0.0


def check(rule: Rule, ds: DeclarationSet, ctx: PackageContext, pack: Rulepack) -> CheckOutcome:
    if (blocked := category_blocks(rule, ctx)) is not None:
        return CheckOutcome.not_applicable(blocked)

    if not ds.has_pixels():
        return CheckOutcome.no_data("A text listing has no character geometry.")

    required = float(rule.opt("ratio", 1.0 / 3.0))
    excluded = set(rule.opt("exclude_chars") or [])
    fields = rule.target_fields()

    declarations = measured_for(ds, fields)
    if not declarations:
        return CheckOutcome.no_data("Declaration not read; its absence is reported separately.")

    narrowest: float | None = None
    narrowest_char: str | None = None
    measured_any = False

    for decl in declarations:
        if not decl.char_boxes:
            continue
        # char_boxes is positional against the declaration text; zip stops at
        # the shorter of the two, which is the safe behaviour when the OCR
        # engine returned fewer boxes than characters.
        for ch, box in zip(decl.text, decl.char_boxes, strict=False):
            if ch.isspace() or ch in excluded:
                continue
            measured_any = True
            r = _ratio(decl, box)
            if narrowest is None or r < narrowest:
                narrowest, narrowest_char = r, ch

    if not measured_any or narrowest is None:
        # No character-level geometry. Say so rather than guessing: this check
        # is cheap to be honest about because two dozen others still ran.
        return CheckOutcome.no_data(
            "The OCR engine returned no character-level boxes, so width could not be measured."
        )

    status: VerdictStatus = "PASS" if narrowest >= required else "FAIL"
    return CheckOutcome(
        status=status,
        found=f"{narrowest:.3f} (character {narrowest_char!r})",
        expected=f">= {required:.3f} of the character height",
        measured=narrowest,
        threshold=required,
        field_name=fields[0] if fields else None,
        detail="Compared in pixels; this check needs no scale recovery.",
    )
