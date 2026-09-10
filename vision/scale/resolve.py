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

from vision.scale import tier_a, tier_b, tier_c
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
    allow_tier_a: bool = True,
) -> ScaleEstimate:
    """Best available scale for this photograph. Never fails.

    `raw` is the original frame — tier A searches it, because rectification
    warps to the label face and would crop a marker card lying beside the pack
    out of existence. `rectified` is what tier B measures and what every glyph
    is measured in, so both tiers return mm per *rectified* pixel.
    """
    notes: list[str] = []

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
            return found
        notes.append(
            "tier A rejected: implausible scale"
            if found is not None
            else "tier A: no acceptable reference marker"
        )

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
