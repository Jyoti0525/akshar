"""`same_panel` — Rule 8(1), declarations must be grouped on the principal
display panel.

The law treats a label as geometry, not as text. This check is why panel
segmentation is in the pipeline at all: no existing open-source project
attempts it, because none of them knows where the front of the pack is.

Rule 2(h)(ii) allows a split between what is pre-printed on the pack and what
is added later (an online-printed date or batch), so `allow_split` exempts the
declarations that are commonly overprinted.
"""

from __future__ import annotations

from contracts import Box, DeclarationSet, PackageContext
from rules.checks._common import category_blocks, declarations_for
from rules.models import CheckOutcome, Rule, Rulepack

_OVERPRINTED = frozenset({"mfg_date", "expiry_date", "batch"})
"""Fields commonly applied by an online printer after the pack is made, and so
permitted to sit apart from the pre-printed group under Rule 2(h)(ii)."""


def _point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray casting. Small and exact; no geometry dependency needed."""
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < xin:
                inside = not inside
    return inside


def _on_pdp(box: Box, polygon: list[tuple[float, float]] | None) -> bool | None:
    """True/False when we can tell, None when we cannot."""
    if box.panel_id is not None:
        return box.panel_id == "pdp"
    if polygon and len(polygon) >= 3:
        return _point_in_polygon(box.cx, box.cy, polygon)
    return None


def check(rule: Rule, ds: DeclarationSet, ctx: PackageContext, pack: Rulepack) -> CheckOutcome:
    if (blocked := category_blocks(rule, ctx)) is not None:
        return CheckOutcome.not_applicable(blocked)

    if not ds.has_pixels():
        return CheckOutcome.no_data("A text listing has no panel geometry.")

    polygon = ds.geometry.pdp_polygon
    fields = rule.target_fields()
    allow_split = rule.opt("allow_split") == "pre_printed_vs_online"

    judged = declarations_for(ds, fields)
    if allow_split:
        judged = [d for d in judged if d.field not in _OVERPRINTED]

    # Rule 8(1) is about declarations being GROUPED, and grouping is a fact
    # about one surface. On a multi-frame scan the declarations under judgement
    # may have been read from photographs of different sides of the pack, and
    # then there is no arrangement to look at: `pdp_polygon` outlines the panel
    # of one photograph, and a box from another frame sits inside or outside it
    # by accident of where that photograph's origin fell.
    #
    # NO_DATA, not PASS and not FAIL. An officer who walked round the pack has
    # not shown us the grouping; they have also not shown us a violation of it.
    if ds.is_union() and {d.frame_id for d in judged} - {ds.geometry.frame_id}:
        return CheckOutcome.no_data(
            "These declarations were read from more than one photograph, so how "
            "they are grouped on the pack cannot be judged. Photograph the "
            "declaration panel in a single frame for this rule to run."
        )

    offenders: list[str] = []
    undecided: list[str] = []

    for decl in judged:
        verdict = _on_pdp(decl.box, polygon)
        if verdict is None:
            undecided.append(decl.field)
        elif not verdict:
            offenders.append(f"{decl.field} ({decl.box.panel_id or 'off-panel'})")

    if not offenders and undecided and not polygon:
        return CheckOutcome.no_data(
            "The principal display panel was not segmented, so placement could not be judged."
        )

    if offenders:
        return CheckOutcome(
            status="FAIL",
            found=", ".join(sorted(set(offenders))),
            expected="all mandatory declarations grouped on the principal display panel",
            measured=float(len(offenders)),
            threshold=0.0,
            field_name=fields[0] if fields else None,
        )

    return CheckOutcome(
        status="PASS",
        expected="all mandatory declarations grouped on the principal display panel",
        measured=0.0,
        threshold=0.0,
        field_name=fields[0] if fields else None,
        detail=(
            "Declarations added by an online printer are permitted to sit apart "
            "under Rule 2(h)(ii)."
            if allow_split
            else None
        ),
    )
