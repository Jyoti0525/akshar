"""Scale tier B — known physical dimensions for a SKU we have seen before.

    "Tier B uses known SKU dimensions from the repository. [...] B falls out
     free once the repository fills, and it's the elegant one: the more the
     system has seen, the less it needs the marker." -- section 17, M2

This is the tier worth talking about in the viva. Tier A is impressive but
needs a prop in every photograph, which is a procedure officers will forget.
Tier B needs nothing: once any officer anywhere has measured a Parle-G 100 g
pack with a marker, every subsequent photograph of that SKU is measurable without
one. It is the same observation the cache is built on — *a violation is printed
at design time, so it is identical on every packet of that SKU* — applied to
geometry instead of verdicts.

**No database import.** The repository lives behind a `DimensionLookup`
callable supplied by the caller. `vision/` knowing about SQLAlchemy would put
a database session inside the extraction path, and the boundary test would be
right to fail it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from vision.types import Image, RectifyMethod, ScaleEstimate

_MIN_OBSERVATIONS = 3
"""Dimensions are averaged from prior tier-A scans. One observation could be a
single bad marker fit propagating forever; three is enough for a median to be
meaningful and small enough to be reached quickly."""

_METHOD_TOLERANCE_MULTIPLIER: dict[RectifyMethod, float] = {
    "quad": 1.0,
    # The detector-box crop is padded and axis-aligned, so the rectified image
    # is not exactly the label. That padding is a systematic scale error.
    "detector_box": 3.5,
    "identity": 8.0,
}


@dataclass(frozen=True, slots=True)
class SkuDimensions:
    """Physical label dimensions previously established for one SKU."""

    sku_id: str
    label_width_mm: float
    label_height_mm: float | None = None
    observations: int = 0
    """How many tier-A scans this was averaged from."""

    stddev_mm: float | None = None
    """Spread across those scans. Feeds the tolerance directly, so a SKU that
    has been measured inconsistently reports a wider REVIEW band rather than a
    falsely tight one."""


class DimensionLookup(Protocol):
    """Supplied by `api/` or the worker; `vision/` never opens a connection."""

    def __call__(self, cache_key: str) -> SkuDimensions | None: ...


def estimate(
    rectified: Image,
    *,
    cache_key: str | None,
    lookup: DimensionLookup | None,
    rectify_method: RectifyMethod = "quad",
    label_width_px: float | None = None,
) -> ScaleEstimate | None:
    """Recover `mm_per_px` from stored dimensions. None if unavailable."""
    if cache_key is None or lookup is None:
        return None

    dims = lookup(cache_key)
    if dims is None or dims.label_width_mm <= 0:
        return None
    if dims.observations < _MIN_OBSERVATIONS:
        return None

    width_px = label_width_px if label_width_px is not None else float(rectified.shape[1])
    if width_px <= 1.0:  # pragma: no cover - degenerate crop
        return None

    mm_per_px = dims.label_width_mm / width_px

    # Two sources of error: how consistently the width was measured, and how
    # well this photo's rectification recovered the label rectangle.
    relative = (
        (dims.stddev_mm / dims.label_width_mm)
        if dims.stddev_mm is not None and dims.stddev_mm > 0
        else 0.02
    )
    tolerance = mm_per_px * relative * _METHOD_TOLERANCE_MULTIPLIER.get(rectify_method, 8.0)

    return ScaleEstimate(
        tier="B",
        mm_per_px=mm_per_px,
        tolerance=tolerance,
        method="known_sku",
        detail=(
            f"Known SKU {dims.sku_id}: label width {dims.label_width_mm:.1f} mm "
            f"from {dims.observations} prior scans, measured here at "
            f"{width_px:.0f} px (rectify={rectify_method})"
        ),
    )


__all__ = ["DimensionLookup", "SkuDimensions", "estimate"]
