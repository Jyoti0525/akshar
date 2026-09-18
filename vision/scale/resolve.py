"""Pick a scale tier — A, then B, then C, and always something.

Order matters and is not arbitrary. Tier A is a direct measurement of an object
in *this* photograph; tier B is an inference from other photographs of the same
SKU. A direct measurement beats an inference even when the inference has more
observations behind it, because tier B cannot notice that this particular
packet is a different pack size of the same brand.

Tier C is not a failure branch — it is the third answer, and the one that keeps
28 of the 31 rules alive when there is no marker and no history. The function
therefore has no error return: it always yields a `ScaleEstimate`.
"""

from __future__ import annotations

from vision.scale import operator, tier_a, tier_b, tier_c
from vision.types import Image, RectifyMethod, ScaleEstimate

_MAX_PLAUSIBLE_MM_PER_PX = 2.0
"""A rectified pixel worth more than 2 mm means the label is about 40 px wide,
which is not a photograph anyone can read. Reject rather than emit."""

_MIN_PLAUSIBLE_MM_PER_PX = 0.002
"""And under 0.002 mm/px the label would be half a metre of print. Both bounds
exist because a misread marker fails loudly here rather than quietly producing
a 40 mm MRP that passes every height rule."""


def _plausible(estimate: ScaleEstimate | None) -> bool:
    if estimate is None or estimate.mm_per_px is None:
        return False
    return _MIN_PLAUSIBLE_MM_PER_PX <= estimate.mm_per_px <= _MAX_PLAUSIBLE_MM_PER_PX


_DISAGREEMENT_LIMIT = 0.15
"""How far a marker and a typed pack height may differ before the disagreement
is folded into the tolerance. Fifteen per cent is far wider than either should
be wrong on its own, so crossing it means one of them is wrong about something
structural -- a card at a different depth from the label, or a decimal point."""


def _cross_checked(marker: ScaleEstimate, typed: ScaleEstimate | None) -> ScaleEstimate:
    """Two independent measurements of the same photograph, so compare them.

    The marker wins, because it is measured from the image rather than typed.
    But when the two disagree materially, that disagreement is the best estimate
    of how wrong we might be, and burying it would be the one thing this
    codebase must not do: `95` typed as `9.5` is a factor of ten that produces
    no visible symptom at all, and a scan that saw both numbers and said nothing
    would be hiding evidence it already had.

    Note what this does NOT do: it never overrides the marker with the typed
    figure, and it never fails the scan. It widens the REVIEW band and says so
    in a sentence an officer can read.
    """
    if typed is None or typed.mm_per_px is None or marker.mm_per_px is None:
        return marker

    gap = abs(typed.mm_per_px - marker.mm_per_px) / marker.mm_per_px
    if gap <= _DISAGREEMENT_LIMIT:
        return marker

    widened = max(marker.tolerance or 0.0, marker.mm_per_px * gap)
    return ScaleEstimate(
        tier=marker.tier,
        mm_per_px=marker.mm_per_px,
        tolerance=widened,
        method=marker.method,
        detail=(
            f"{marker.detail}; the entered pack height disagrees by {gap * 100:.0f}% "
            f"(it implies {typed.mm_per_px:.4f} mm/px), so the tolerance is widened. "
            f"Check the entered height and whether the marker card lay at the same "
            f"distance from the camera as the label."
        ),
        reference_box=marker.reference_box,
    )


def resolve_scale(
    raw: Image,
    rectified: Image,
    *,
    homography: Image | None = None,
    rectify_method: RectifyMethod = "quad",
    edge_mm: float = tier_a.MARKER_EDGE_MM,
    dictionary: str = tier_a.DEFAULT_DICTIONARY,
    marker_ids: frozenset[int] | None = None,
    cache_key: str | None = None,
    lookup: tier_b.DimensionLookup | None = None,
    operator_height_mm: float | None = None,
    allow_tier_a: bool = True,
) -> ScaleEstimate:
    """Best available scale for this photograph. Never fails.

    `raw` is the original frame — tier A searches it, because rectification
    warps to the label face and would crop a marker card lying beside the pack
    out of existence. `rectified` is what tier B measures and what every glyph
    is measured in, so both tiers return mm per *rectified* pixel.

    `operator_height_mm` is the height of the photographed face, measured with a
    ruler by the person holding the pack. It sits inside tier A rather than
    beside it because it is the same kind of evidence: a known physical length
    in *this* photograph, not an inference from other photographs. It is tried
    after the marker and is used when there is no marker — which, on the 231
    millimetre-grade frames in this corpus, is all of them.
    """
    notes: list[str] = []

    typed = operator.estimate(
        rectified, height_mm=operator_height_mm, rectify_method=rectify_method
    )
    if operator_height_mm is not None and not _plausible(typed):
        notes.append(f"entered pack height {operator_height_mm:g} mm gives an implausible scale")
        typed = None

    if allow_tier_a:
        found = tier_a.estimate(
            raw,
            homography=homography,
            rectify_method=rectify_method,
            edge_mm=edge_mm,
            dictionary=dictionary,
            marker_ids=marker_ids,
        )
        if _plausible(found):
            assert found is not None
            return _cross_checked(found, typed)
        notes.append(
            "tier A rejected: implausible scale"
            if found is not None
            else "tier A: no acceptable reference marker"
        )

    if typed is not None:
        return typed

    found_b = tier_b.estimate(
        rectified,
        cache_key=cache_key,
        lookup=lookup,
        rectify_method=rectify_method,
    )
    if _plausible(found_b):
        assert found_b is not None
        return found_b
    notes.append("tier B: no stored dimensions for this SKU")

    return tier_c.estimate(detail="; ".join(notes))


__all__ = ["resolve_scale"]
