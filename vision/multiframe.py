"""Several photographs of one pack, unioned into one body of evidence.

AKSHAR.md section 8b's ScanContext, and the answer to the objection that made it
urgent: *"an officer will not take care of these things — we need our system
designed so strong that it handles these kinda things too without failing."*

`vision/quality/framing.py` can now tell an officer that the declaration panel
was not in shot. That is worth having and it does not solve the problem, because
it still asks the officer to aim. This does: **one pack, two or three
photographs from different sides, the evidence unioned, and the rules evaluated
once on the union.** The officer no longer has to frame the right panel; they
have to walk round the pack, which is a thing people actually do.

---------------------------------------------------------------------------
WHY THE UNION, AND NOT A VOTE OVER PER-FRAME VERDICTS
---------------------------------------------------------------------------
The obvious alternative is to evaluate each photograph and combine the verdicts
— best status per rule. It is simpler, it needs no contract change, and it is
unsound in the one direction an enforcement tool may not be unsound in.

Take a pack whose front declares a lawful MRP and whose back carries a second,
higher one pasted over. Frame 1 passes Rule 6(3); frame 2 fails it. Best-status
wins clears the pack. Worst-status wins is no better, because it convicts every
pack whose second photograph merely failed to show a declaration the first one
did. There is no combining rule over verdicts that is right in both cases,
because the verdicts were computed against different evidence and the law is
about the package, not about the photograph.

Union the evidence and evaluate once, and both cases come out right: the engine
sees two MRPs and Rule 6(3) fires on the pack, exactly as it would if a single
photograph had caught both.

---------------------------------------------------------------------------
WHAT THE UNION MUST NOT SILENTLY MERGE
---------------------------------------------------------------------------
**Coordinates.** `contracts.Box` documents itself as living in rectified label
space. Each photograph has its own. Two boxes from two frames may overlap and it
means nothing, so every declaration is stamped with `frame_id` on the way in and
the three checks that compare boxes filter on it.

**Scale and panel geometry.** `LabelGeometry` holds one `mm_per_px`, one
`pdp_polygon`, one `label_area_cm2`. They belong to one image. The union takes
them from a single nominated frame and records which in `geometry.frame_id`
rather than averaging numbers that are not commensurable. Heights in millimetres
were already converted per declaration, at the scale of the frame each was read
from, so nothing downstream needs the set-level scalar to convert anything —
`DeclarationSet.has_scale()` is what the height rules gate on.

**Nothing is dropped.** Every declaration from every frame is in the union,
including duplicates of the same printed text seen twice. Deduplicating would be
this module deciding which reading of a price is the real one, and that is the
engine's question (Rule 6(3)) rather than ours.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from contracts import DeclarationSet, LabelGeometry
from vision.quality.framing import RULE_6_1_DECLARATIONS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

_TIER_ORDER = ("L0", "L1", "L2", "L3", "L4")
"""Best first. `degradation.assign` is the only thing that produces these."""


def best_tier(tiers: Sequence[str]) -> str:
    """The best tier among the frames, which is the tier the union actually has.

    Not the worst, and not an average. The union *contains* everything the best
    frame contained; a second, blurrier photograph beside it removes nothing.
    The tier gates `reading_supports_an_absence`, whose question is "was this
    label read well enough to say that a declaration is missing from it" — and
    if one photograph read the panel cleanly, the answer is yes regardless of
    what the others managed.
    """
    present = set(tiers)
    ranked = [tier for tier in _TIER_ORDER if tier in present]
    return ranked[0] if ranked else "L4"


def _mandatory_found(ds: DeclarationSet) -> int:
    return len({d.field for d in ds.declarations} & RULE_6_1_DECLARATIONS)


def primary_frame(sets: Sequence[DeclarationSet]) -> int:
    """Which frame's geometry the union carries.

    The declaration panel, when one of the photographs is of it: the frame
    naming the most of Rule 6(1)'s declarations. That is the frame the geometric
    rules have the most to say about, so it is the one whose `pdp_polygon` and
    `mm_per_px` are worth keeping.

    Ties break towards the frame that recovered a scale, then towards the one
    that read more, then towards the earliest — deterministic all the way down,
    because a finding that depends on iteration order is a finding you cannot
    reproduce.
    """

    def rank(index: int) -> tuple[int, int, int, int]:
        ds = sets[index]
        return (
            -_mandatory_found(ds),
            0 if ds.has_scale() else 1,
            -len(ds.declarations),
            index,
        )

    return min(range(len(sets)), key=rank)


def _merge_versions(sets: Sequence[DeclarationSet]) -> dict[str, str]:
    """One model_versions map for the union, with disagreement kept visible.

    Frames are read by the same models in the same process, so the maps are
    normally identical and collapse to one value. When they are not — a frame
    that fell back to the geometry-only detector beside one that did not — both
    values are kept. Section 14: a finding you cannot reproduce is a finding you
    cannot defend, and silently keeping the last frame's answer would make one
    of the two measurements unreproducible.
    """
    merged: dict[str, list[str]] = {}
    for ds in sets:
        for key, value in ds.model_versions.items():
            seen = merged.setdefault(key, [])
            if value not in seen:
                seen.append(value)
    return {key: " | ".join(values) for key, values in merged.items()}


def union(
    sets: Sequence[DeclarationSet], *, frame_ids: Sequence[int] | None = None
) -> DeclarationSet:
    """Combine the frames of one pack into the single set the engine judges.

    `frame_ids` numbers the photographs these sets came from, defaulting to
    their position. It is not decoration: a scan of four photographs where the
    second was rejected by B1 hands three sets to this function, and the third
    of them is still *the officer's fourth shot*. Renumbering it 2 would put a
    different photograph in front of anyone who later asked which one a
    measurement came from.

    Raises `ValueError` on an empty sequence, and on frames from different input
    channels — a photograph and an e-commerce listing are evidence about the
    same product but not about the same artefact, and unioning them would put a
    box measured in pixels beside a declaration that never had any.
    """
    if not sets:
        raise ValueError("a union needs at least one frame")

    ids = list(range(len(sets))) if frame_ids is None else list(frame_ids)
    if len(ids) != len(sets):
        raise ValueError("frame_ids must name exactly one photograph per set")

    if len(sets) == 1:
        only = sets[0]
        if ids[0] == 0:
            return only
        return only.model_copy(
            update={
                "declarations": [
                    d.model_copy(update={"frame_id": ids[0]}) for d in only.declarations
                ],
                "geometry": only.geometry.model_copy(update={"frame_id": ids[0]}),
            }
        )

    sources = {ds.source for ds in sets}
    if len(sources) > 1:
        raise ValueError(
            "cannot union frames from different channels: " + ", ".join(sorted(sources))
        )

    primary = primary_frame(sets)

    declarations = [
        declaration.model_copy(update={"frame_id": ids[index]})
        for index, ds in enumerate(sets)
        for declaration in ds.declarations
    ]

    texts = [ds.raw_text for ds in sets if ds.raw_text]

    return DeclarationSet(
        source=sets[primary].source,
        declarations=declarations,
        geometry=sets[primary].geometry.model_copy(update={"frame_id": ids[primary]}),
        # The mean rather than the best: coverage is shown to the officer as
        # "how much of what we saw did we manage to read", and the answer for
        # three photographs is the answer across three photographs.
        #
        # Rounded, and not for tidiness. `scans.coverage` is a Postgres NUMERIC
        # and a 17-significant-digit float does not survive the round trip
        # through it — 0.9722222222222222 comes back 0.972222222222222, and the
        # evidence chain then re-hashes the row to a different digest and
        # reports CONTENT_ALTERED on a record nobody touched. A mean over k
        # frames almost always needs those digits; a single ratio usually does
        # not, which is why this was latent until the union existed. See
        # `api.scanning.CHAIN_SAFE_DP`.
        coverage=round(sum(ds.coverage for ds in sets) / len(sets), 6),
        degradation_tier=best_tier([ds.degradation_tier for ds in sets]),
        captured_at=min(ds.captured_at for ds in sets),
        model_versions=_merge_versions(sets),
        raw_text="\n".join(texts) if texts else None,
        frame_count=len(sets),
    )


def geometry_for(frame_id: int, geometry: LabelGeometry) -> LabelGeometry:
    """Stamp a single frame's geometry with the frame it describes."""
    return geometry.model_copy(update={"frame_id": frame_id})


__all__ = ["best_tier", "geometry_for", "primary_frame", "union"]
