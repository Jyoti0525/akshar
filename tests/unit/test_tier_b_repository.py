"""Scale tier B, end to end — the tier that works without the marker card.

    "Tier A is impressive but needs a prop in every photograph, which is a
     procedure officers will forget. Tier B needs nothing: once any officer
     anywhere has measured a Parle-G 100 g pack with a marker, every subsequent
     photograph of that SKU is measurable without one."
                                        -- vision/scale/tier_b.py, section 17 M2

On 2026-09-19 that was false in the only way that matters: `estimate` was
implemented and tested, and **nothing called it and nothing fed it**. The
pipeline took a `dimension_lookup` argument that no caller ever supplied, and no
code path anywhere wrote a measured dimension back after a tier-A scan. Both
ends open, so the repository stayed empty, so the three-observation guard was
permanently tripped, so every photograph needed the card.

These tests are the closed loop: measure three times with a marker, then measure
without one. They are written against the in-memory store because the whole
point is that the arithmetic is the same in a demo and in a district.
"""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pytest

from api.repository import InMemorySkuStore, SkuRecord
from api.scanning import _dimension_lookup, _sku_dimensions, _teach_dimensions
from vision.scale import tier_b
from vision.types import ScaleEstimate


def marker(mm_per_px: float = 0.25, tier: str = "A") -> ScaleEstimate:
    return ScaleEstimate(
        tier=tier,  # type: ignore[arg-type]
        mm_per_px=mm_per_px,
        tolerance=mm_per_px * 0.02,
        method="aruco" if tier == "A" else "known_sku",
    )


def sku(**overrides) -> SkuRecord:
    base = {
        "id": uuid4(),
        "brand": "Parle",
        "variant": "G",
        "pack_size": "100 g",
        "category": "food",
        "barcode": "8901719101045",
        "phash": "ffff0000ffff0000",
    }
    return SkuRecord(**{**base, **overrides})


# ---------------------------------------------------------------------------
# What is allowed to teach
# ---------------------------------------------------------------------------


def test_a_marker_measured_quad_teaches():
    observation = tier_b.observe(
        marker(0.25), width_px=400.0, height_px=600.0, rectify_method="quad"
    )
    assert observation is not None
    assert observation.width_mm == pytest.approx(100.0)
    assert observation.height_mm == pytest.approx(150.0)


def test_tier_b_never_feeds_itself():
    """The failure that would be invisible and permanent.

    A tier-B estimate's millimetre came *out of* the stored mean. Storing it
    back would reinforce that mean and drive its spread towards zero, so the
    estimate would grow more confident the more often it was repeated — a
    measurement that has stopped measuring anything, reporting a tight
    tolerance, feeding a height rule that puts FAIL on a legal notice.
    """
    assert (
        tier_b.observe(marker(0.25, tier="B"), width_px=400.0, height_px=600.0,
                       rectify_method="quad")
        is None
    )


def test_tier_c_has_no_millimetre_to_teach():
    scale = ScaleEstimate(tier="C", mm_per_px=None, tolerance=None, method="none")
    assert (
        tier_b.observe(scale, width_px=400.0, height_px=600.0, rectify_method="quad") is None
    )


def test_a_padded_detector_crop_does_not_teach():
    """`_METHOD_TOLERANCE_MULTIPLIER` prices this at 3.5x for *reading*.

    For writing there is no acceptable price: the padding is a systematic error,
    so it would not widen the spread, it would become the mean.
    """
    for method in ("detector_box", "identity"):
        assert (
            tier_b.observe(marker(0.25), width_px=400.0, height_px=600.0,
                           rectify_method=method)  # type: ignore[arg-type]
            is None
        )


def test_an_implausible_measurement_does_not_teach():
    # A marker fit off by an order of magnitude: a two-metre biscuit packet.
    assert (
        tier_b.observe(marker(5.0), width_px=400.0, height_px=600.0, rectify_method="quad")
        is None
    )
    # ...and one off in the other direction: a 0.4 mm label.
    assert (
        tier_b.observe(marker(0.001), width_px=400.0, height_px=600.0, rectify_method="quad")
        is None
    )


def test_a_missing_scale_is_an_ordinary_outcome():
    assert tier_b.observe(None, width_px=400.0, height_px=600.0, rectify_method="quad") is None


# ---------------------------------------------------------------------------
# What an established SKU accepts
# ---------------------------------------------------------------------------


def observation(width_mm: float) -> tier_b.DimensionObservation:
    return tier_b.DimensionObservation(width_mm=width_mm, height_mm=width_mm * 1.5)


def test_everything_is_admitted_before_there_is_anything_to_be_an_outlier_from():
    assert tier_b.admits(None, observation(100.0))
    dims = tier_b.SkuDimensions(sku_id="x", label_width_mm=100.0, observations=2, stddev_mm=0.1)
    assert tier_b.admits(dims, observation(180.0))


def test_an_outlier_against_an_established_sku_is_dropped_not_averaged():
    """A different pack size sharing artwork, or a photograph of the side panel.

    Averaging it in would move every future scan of this SKU, which is how one
    bad frame becomes a wrong millimetre on somebody else's notice.
    """
    dims = tier_b.SkuDimensions(
        sku_id="x", label_width_mm=100.0, observations=6, stddev_mm=1.0
    )
    assert not tier_b.admits(dims, observation(140.0))
    assert tier_b.admits(dims, observation(102.0))


def test_a_very_consistent_sku_does_not_reject_every_later_photograph():
    """The 5% floor. Three near-identical photographs give a stddev near zero,
    and four sigma of nearly nothing would lock the SKU against its own fourth
    measurement forever."""
    dims = tier_b.SkuDimensions(
        sku_id="x", label_width_mm=100.0, observations=3, stddev_mm=0.0001
    )
    assert tier_b.admits(dims, observation(103.0))
    assert not tier_b.admits(dims, observation(120.0))


# ---------------------------------------------------------------------------
# The store — Welford, and what the count means
# ---------------------------------------------------------------------------


def test_three_marker_scans_fill_the_repository():
    store = InMemorySkuStore()
    record = store.add(sku())
    for width in (100.0, 102.0, 101.0):
        store.record_dimensions(record.id, width_mm=width, height_mm=width * 1.5)

    filled = store.by_id(record.id)
    assert filled is not None
    assert filled.label_mm_observations == 3
    assert filled.label_w_mm == pytest.approx(101.0)
    assert filled.label_h_mm == pytest.approx(151.5)
    # Sample standard deviation of 100, 102, 101.
    assert filled.label_w_mm_stddev == pytest.approx(1.0)


def test_a_hand_seeded_dimension_is_replaced_rather_than_averaged():
    """It was never measured, so it has no weight to carry.

    A fixture or a spreadsheet import arrives with `label_mm_observations = 0`.
    Treating that as one observation would put a number nobody measured into
    the mean, and — worse — would let it count towards the three that unlock
    the tier.
    """
    store = InMemorySkuStore()
    record = store.add(sku(label_w_mm=999.0, label_h_mm=999.0))
    store.record_dimensions(record.id, width_mm=100.0, height_mm=150.0)

    filled = store.by_id(record.id)
    assert filled is not None
    assert filled.label_w_mm == pytest.approx(100.0)
    assert filled.label_mm_observations == 1


def test_one_observation_reports_no_spread_rather_than_a_perfect_one():
    """`None`, never `0.0`. A zero spread reads as a perfectly measured SKU and
    would produce a tolerance of nothing — a confident FAIL from one photo."""
    store = InMemorySkuStore()
    record = store.add(sku())
    store.record_dimensions(record.id, width_mm=100.0, height_mm=150.0)
    filled = store.by_id(record.id)
    assert filled is not None and filled.label_w_mm_stddev is None


def test_two_observations_are_still_not_enough_to_measure_against():
    store = InMemorySkuStore()
    record = store.add(sku())
    for _ in range(2):
        store.record_dimensions(record.id, width_mm=100.0, height_mm=150.0)

    lookup = _dimension_lookup(store)
    assert (
        tier_b.estimate(
            np.zeros((600, 400, 3), dtype=np.uint8),
            cache_key="barcode:8901719101045",
            lookup=lookup,
        )
        is None
    )


# ---------------------------------------------------------------------------
# The loop closed: measure three times with a marker, then without one
# ---------------------------------------------------------------------------


def test_the_fourth_photograph_needs_no_marker_card():
    store = InMemorySkuStore()
    record = store.add(sku())
    for width in (100.0, 101.0, 99.0):
        store.record_dimensions(record.id, width_mm=width, height_mm=width * 1.5)

    estimate = tier_b.estimate(
        np.zeros((600, 400, 3), dtype=np.uint8),
        cache_key="barcode:8901719101045",
        lookup=_dimension_lookup(store),
        rectify_method="quad",
    )
    assert estimate is not None
    assert estimate.tier == "B"
    # 100 mm over 400 px.
    assert estimate.mm_per_px == pytest.approx(0.25)
    assert estimate.tolerance is not None and estimate.tolerance > 0
    assert "3 prior scans" in estimate.detail


def test_the_lookup_resolves_by_phash_when_there_is_no_barcode():
    """Barcode first, then pHash — `_resolve_sku`'s order, reused deliberately.

    Two resolution orders would let a pack be measured against one SKU's stored
    label and judged against another SKU's cached verdicts.
    """
    store = InMemorySkuStore()
    record = store.add(sku(barcode=None))
    for _ in range(3):
        store.record_dimensions(record.id, width_mm=100.0, height_mm=150.0)

    lookup = _dimension_lookup(store)
    assert lookup("phash:ffff0000ffff0000") is not None
    assert lookup("barcode:0000000000000") is None


def test_an_unknown_sku_looks_up_to_nothing_rather_than_raising():
    lookup = _dimension_lookup(InMemorySkuStore())
    assert lookup("barcode:8901719101045") is None
    assert lookup("phash:0123456789abcdef") is None
    assert lookup("nonsense") is None


def test_a_seeded_dimension_is_visible_but_not_measurable():
    """`_sku_dimensions` reports it, `estimate` refuses it. Both are right:
    the product page shows what is on file; the measurement does not use it."""
    seeded = sku(label_w_mm=100.0, label_h_mm=150.0)
    dims = _sku_dimensions(seeded)
    assert dims is not None and dims.label_width_mm == 100.0
    assert dims.observations == 0
    assert (
        tier_b.estimate(
            np.zeros((600, 400, 3), dtype=np.uint8),
            cache_key="k",
            lookup=lambda _key: dims,
        )
        is None
    )


# ---------------------------------------------------------------------------
# The write-back, and the queue it goes on
# ---------------------------------------------------------------------------


class Outcome:
    def __init__(self, scale, rectify_method="quad", rectified=True):
        self.scale = scale
        self.rectify_method = rectify_method
        self.rectified = np.zeros((600, 400, 3), dtype=np.uint8) if rectified else None


def sent():
    messages: list[tuple[str, str, dict]] = []

    def enqueue(task: str, *, queue: str, **kwargs):
        messages.append((task, queue, kwargs))

    return messages, enqueue


def test_a_marker_scan_records_what_it_measured():
    from workers.broker import QUEUE_BULK

    messages, enqueue = sent()
    _teach_dimensions(Outcome(marker(0.25)), sku(), enqueue)

    assert len(messages) == 1
    task, queue, kwargs = messages[0]
    assert task == "record_sku_dimensions"
    # The low lane, with `bump_scan_count`: it is an UPDATE of the same row for
    # every packet of this SKU on the shelf.
    assert queue == QUEUE_BULK
    assert kwargs["width_mm"] == pytest.approx(100.0)
    assert kwargs["height_mm"] == pytest.approx(150.0)


def test_an_unrecognised_pack_teaches_nothing():
    """There is no row to teach. The same dependency the verdict cache has."""
    messages, enqueue = sent()
    _teach_dimensions(Outcome(marker(0.25)), None, enqueue)
    assert messages == []


def test_a_tier_b_scan_does_not_write_its_own_answer_back():
    messages, enqueue = sent()
    _teach_dimensions(Outcome(marker(0.25, tier="B")), sku(), enqueue)
    assert messages == []


def test_an_outlier_scan_of_a_known_sku_is_not_enqueued():
    messages, enqueue = sent()
    established = sku(label_w_mm=100.0, label_mm_observations=8, label_w_mm_stddev=1.0)
    # 0.35 mm/px over 400 px is 140 mm against an established 100 mm.
    _teach_dimensions(Outcome(marker(0.35)), established, enqueue)
    assert messages == []


def test_nothing_is_enqueued_when_there_is_no_queue():
    """The unit-test and offline paths pass `enqueue=None`; this must not raise."""
    _teach_dimensions(Outcome(marker(0.25)), sku(), None)


def test_a_scan_that_never_rectified_teaches_nothing():
    messages, enqueue = sent()
    _teach_dimensions(Outcome(marker(0.25), rectified=False), sku(), enqueue)
    assert messages == []


def test_the_actor_exists_on_the_queue_the_caller_names():
    """`api.deps.resources.enqueue` asserts the lane rather than applying it, so
    a task named here and declared elsewhere fails at the call site."""
    from workers import tasks
    from workers.broker import QUEUE_BULK

    assert tasks.record_sku_dimensions.queue_name == QUEUE_BULK
