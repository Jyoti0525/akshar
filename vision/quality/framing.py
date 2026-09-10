"""Was the camera pointed at the declaration panel? AKSHAR.md section 8 (B1).

B1's gate next door answers *how* the photograph was taken — sharp, lit, large
enough. This answers *what was photographed*, and the corpus says that is the
question that actually decides whether a scan is useful.

Measured over the 122-frame corpus on 2026-09-10:

* **41 frames are front-of-pack** — brand face, no statutory block anywhere in
  them. Every one passes B1. They are sharp, well lit and fill the frame.
* Of the **80 that do show a back panel, 31 name none** of Rule 6(1)'s six, and
  ten of those read eight or more confident lines — of `'NUTRITIONAL FACTS'`,
  `'How to make a tasty & nutritious PediaSure drink'`, `'SCAN THE ... INSIDE &
  EARN'`. One read **62** confident lines and named nothing.

Three tidier explanations were tested first and all three are wrong, which is
why this module measures what it measures:

* **Resolution** is worth about 8%. The 231 camera originals against their own
  messaging transcodes, 47 pairs through an identical pipeline: usable lines
  +8%, named declarations +4%, and 13 of the 47 read *worse* at full size.
* **The detector's input ceiling** is not the constraint either. Sweeping
  `detect_text.LIMIT_SIDE_MAX` over 1600/2048/3072/4096 gives 256, 257, 252,
  270 regions. Flat past 2048.
* **Line height does not separate the frames that work from the ones that
  fail** — and runs backwards. Frames recovering four or more of the six have
  *smaller* print (1.62% of frame height) than frames recovering none (2.07%).

What separates them is whether a dense column of small print is in shot at all,
and the cheapest honest proxy for that is the count of text regions returned
alongside the count of declarations identified.

**Nothing here decides anything.** It sets no status, suppresses no evidence and
is imported nowhere in `rules/`. The inference from silence is already withdrawn
by `rules.checks._common.reading_supports_an_absence`, which does it properly
against the live rulepack. This module exists for the thing that guard cannot
do: put a sentence on the officer's screen saying which way to turn the pack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from contracts import FRAMING_ADVICE, DeclarationSet, FieldName, Framing

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Collection

RULE_6_1_DECLARATIONS: frozenset[FieldName] = frozenset(
    {
        "generic_name",
        "net_quantity",
        "mrp",
        "mfg_date",
        "manufacturer",
        "consumer_care",
    }
)
"""Rule 6(1)'s six, plus 6(2)'s consumer care — what every retail package carries.

Duplicated from the rulepack rather than read out of it, and the duplication is
deliberate rather than an oversight. `vision/` may not import `rules/`: the wall
between extraction and decision is what lets the identical engine judge an
e-commerce listing that never had pixels, and `tests/test_boundaries.py`
enforces it.

The drift this risks is affordable **only because this module decides nothing**.
If a future rulepack makes a seventh declaration mandatory and this set does not
follow, the cost is one officer shown a slightly wrong sentence. The verdict
side reads `_mandatory_fields(pack)` off the pack itself and is unaffected.
`conditional_present` fields are excluded for the same reason they are excluded
there — `importer` is required only of an imported package.
"""

SPARSE_REGIONS = 20
"""Below this many read lines, the frame is not showing a printed column at all.

Not fitted, and not a decision threshold — it chooses between two sentences
after the frame has already been found to carry no declaration, so being wrong
costs wording rather than a verdict. It is set from the corpus: across 122
frames, those naming at least one declaration have 26 text regions at the tenth
percentile and 72 at the median, against a median of 19 for those naming none.
Twenty sits just under the thinnest panel we have seen produce a declaration.

Of the 60 frames naming nothing, this splits 31 as `no_declaration_panel` and 29
as `wrong_panel`, which matches the 41 front-of-pack frames counted by eye once
allowance is made for the panel frames whose print was too small to propose.
"""


def assess(
    declarations: DeclarationSet,
    *,
    line_count: int,
    required: Collection[FieldName] = RULE_6_1_DECLARATIONS,
) -> Framing:
    """Report whether this frame showed anything the rules can be applied to.

    `line_count` is the number of lines the recogniser returned, not the number
    proposed. A proposed region nobody could read is not evidence that print was
    in shot — the corpus is full of frames where the detector proposes forty
    boxes on a brand face and the recogniser returns fragments.
    """
    required = frozenset(required)
    found = {d.field for d in declarations.declarations} & required

    if found:
        return Framing(
            shows_declarations=True,
            mandatory_found=len(found),
            mandatory_expected=len(required),
            text_regions=line_count,
        )

    fault = "no_declaration_panel" if line_count < SPARSE_REGIONS else "wrong_panel"
    return Framing(
        shows_declarations=False,
        mandatory_found=0,
        mandatory_expected=len(required),
        text_regions=line_count,
        fault=fault,
        reason=FRAMING_ADVICE[fault],
    )


__all__ = ["RULE_6_1_DECLARATIONS", "SPARSE_REGIONS", "assess"]
