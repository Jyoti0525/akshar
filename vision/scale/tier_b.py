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

_MIN_OBSERVATIONS = 1
"""How many marker scans of a SKU unlock measurement without one.

**This was three, and three was wrong.** The reasoning was that "one
observation could be a single bad marker fit propagating forever" — true, and
it is not what a refusal fixes. Requiring three meant somebody had to
photograph *every SKU in Indian retail* three times with a calibration card
before the system would measure anything, which is not a procedure that exists.
The tier that was supposed to remove the prop had made it three times more
expensive.

The bad-fit risk is handled where it belongs, by three things that do not cost
coverage: `observe` refuses an implausible measurement outright, `admits`
refuses an outlier once there is an established mean to be an outlier from, and
`_RELATIVE_ERROR_PRIOR` below prices a single observation honestly rather than
pretending it is as good as thirty.

That last one is what makes this safe, and it is worth being exact about why.
`rules/checks/min_height_mm.py` turns a measurement within tolerance of the
threshold into **REVIEW, never FAIL** — "convicting on a 0.1 mm margin would be
dismantled in court". So a wide tolerance does not produce a wrong accusation.
It produces "officer, check this one", which is the correct output of a
measurement that is honest about its own uncertainty."""

_MIN_FOR_OUTLIER_GUARD = 3
"""And this one stays at three, for the reason the gate did not.

`admits` rejects a measurement far from the established mean. Running that off
a *single* prior observation would let one bad first fit lock a SKU against
every correct measurement that followed — permanently, silently, and worse the
longer it went unnoticed. An outlier test needs something to be an outlier
from."""

_RELATIVE_ERROR_PRIOR: dict[int, float] = {1: 0.10, 2: 0.06}
"""Assumed relative error when there are too few observations to have measured
one. Conservative rather than derived: with `n=1` there is no sample spread to
compute, and the honest response is to assume the measurement is worse than a
well-observed SKU rather than to assume it is as good.

These widen the REVIEW band; they never narrow it (see `estimate`, which takes
the larger of this and the measured spread). The failure mode is therefore
"asked an officer to check a pack that was fine", not "passed a pack that was
not" — and for a system whose whole design is about not making false
accusations, that is the direction to be wrong in."""

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
    # The larger of what we measured and what we assume for a sample this small.
    # A SKU seen once has no spread to report, and reporting none would claim a
    # 2% measurement — which is a claim about thirty photographs, not one.
    measured = (
        (dims.stddev_mm / dims.label_width_mm)
        if dims.stddev_mm is not None and dims.stddev_mm > 0
        else 0.0
    )
    relative = max(measured, _RELATIVE_ERROR_PRIOR.get(dims.observations, 0.02))
    tolerance = mm_per_px * relative * _METHOD_TOLERANCE_MULTIPLIER.get(rectify_method, 8.0)

    return ScaleEstimate(
        tier="B",
        mm_per_px=mm_per_px,
        tolerance=tolerance,
        method="known_sku",
        detail=(
            f"Known SKU {dims.sku_id}: label width {dims.label_width_mm:.1f} mm "
            f"from {dims.observations} prior scan{'' if dims.observations == 1 else 's'}"
            f"{' (few observations; tolerance widened)' if dims.observations < 3 else ''}"
            f", measured here at "
            f"{width_px:.0f} px (rectify={rectify_method})"
        ),
    )


# ---------------------------------------------------------------------------
# The other half — what is allowed to teach the repository
# ---------------------------------------------------------------------------
#
# `estimate` above spends the repository. Nothing filled it until 2026-09-19:
# the module was implemented, tested, and wired to nothing at either end, so
# every marker measurement an officer took was thrown away and tier B could
# never fire. These are the rules for putting a measurement back.

_PLAUSIBLE_LABEL_MM = (8.0, 1500.0)
"""A packaged commodity's label is not 3 mm wide and not two metres. This is a
sanity band against a catastrophically wrong marker fit, not a tolerance: a
6 mm sachet label and a cement sack are both inside it."""

_OUTLIER_SIGMA = 4.0
_OUTLIER_FLOOR = 0.05
"""How far a new observation may sit from an established mean. Four standard
deviations, or 5% of the mean, whichever is wider — the floor matters because a
SKU measured three times from near-identical photographs has a stddev close to
zero, and without it the fourth photograph from a different angle would be
rejected forever."""


@dataclass(frozen=True, slots=True)
class DimensionObservation:
    """One scan's measurement of a label, admissible for storage."""

    width_mm: float
    height_mm: float


def observe(
    scale: ScaleEstimate | None,
    *,
    width_px: float,
    height_px: float,
    rectify_method: RectifyMethod | None,
) -> DimensionObservation | None:
    """What this scan may teach the repository, or None. Never raises.

    Three refusals, and each one is a way the repository could be poisoned:

    **Only tier A teaches.** A tier-B scan must never feed itself. Its width in
    millimetres was *derived from the stored mean*, so storing it back would
    reinforce whatever that mean already was and drive the stddev towards zero
    — the estimate would grow more confident the more it was repeated, which is
    the precise shape of a measurement that has stopped measuring anything.
    Tier C has no millimetre at all.

    **Only a `quad` rectification teaches.** The detector-box path crops an
    axis-aligned box with padding around the label, so its width is the
    padding's width as much as the label's. `_METHOD_TOLERANCE_MULTIPLIER`
    already prices that at 3.5x for *reading* a stored dimension; for *writing*
    one there is no acceptable price, because the error is systematic and would
    become the mean.

    **Only a plausible number teaches.** See `_PLAUSIBLE_LABEL_MM`.
    """
    if scale is None or scale.tier != "A" or scale.mm_per_px is None:
        return None
    if rectify_method != "quad":
        return None
    if width_px <= 1.0 or height_px <= 1.0:
        return None

    width_mm = scale.mm_per_px * width_px
    height_mm = scale.mm_per_px * height_px
    low, high = _PLAUSIBLE_LABEL_MM
    if not (low <= width_mm <= high and low <= height_mm <= high):
        return None
    return DimensionObservation(width_mm=width_mm, height_mm=height_mm)


def admits(dims: SkuDimensions | None, observation: DimensionObservation) -> bool:
    """Whether an established SKU accepts this observation into its mean.

    Until `_MIN_FOR_OUTLIER_GUARD` is reached there is nothing to be an outlier from
    and everything is admitted — the band would otherwise be set by whichever
    photograph happened to arrive first. After that, a measurement far outside
    the established spread is far more likely to be a bad marker fit, a
    different pack size sharing artwork, or a photograph of the side panel than
    it is to be news about this label; it is dropped rather than averaged in,
    because averaging it in moves every future scan of the SKU.
    """
    if dims is None or dims.observations < _MIN_FOR_OUTLIER_GUARD or dims.label_width_mm <= 0:
        return True
    spread = dims.stddev_mm if dims.stddev_mm and dims.stddev_mm > 0 else 0.0
    allowed = max(_OUTLIER_SIGMA * spread, _OUTLIER_FLOOR * dims.label_width_mm)
    return abs(observation.width_mm - dims.label_width_mm) <= allowed


__all__ = [
    "DimensionLookup",
    "DimensionObservation",
    "SkuDimensions",
    "admits",
    "estimate",
    "observe",
]
