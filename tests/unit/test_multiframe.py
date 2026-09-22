"""One pack, several photographs — AKSHAR.md section 8b's ScanContext.

These tests are almost entirely about the ways a union could **invent a
violation**, because that is the failure mode this feature introduces and none
of the others matter beside it. An officer who walks round the pack must not
thereby make a compliant package fail; if that can happen, the feature is worse
than the framing hint it replaces.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from contracts import Box, LabelGeometry
from rules.checks._common import measured_for
from rules.engine import evaluate
from tests.unit.conftest import make_declaration, make_set
from vision.multiframe import best_tier, primary_frame, union


def verdict(verdicts, rule_id):
    for v in verdicts:
        if v.rule_id == rule_id:
            return v
    raise AssertionError(f"{rule_id} not evaluated")


# ---------------------------------------------------------------------------
# The union itself
# ---------------------------------------------------------------------------


def test_every_declaration_survives_and_is_stamped_with_its_photograph():
    front = make_set([make_declaration("mrp", "MRP Rs. 45.00")])
    back = make_set([make_declaration("net_quantity", "Net Wt. 250 g")])

    merged = union([front, back])

    assert merged.frame_count == 2
    assert [d.frame_id for d in merged.declarations] == [0, 1]
    assert {d.field for d in merged.declarations} == {"mrp", "net_quantity"}


def test_a_single_frame_is_returned_untouched():
    """The union must be a no-op on one photograph, not a rebuild of it."""
    only = make_set([make_declaration("mrp", "MRP Rs. 45.00")])
    assert union([only]) is only
    assert union([only]).frame_count == 1
    assert not union([only]).is_union()


def test_frame_ids_name_the_officers_shot_not_the_position_in_the_list():
    """A rejected frame must not renumber the ones after it.

    Four photographs where the second is unusable hands three sets to `union`,
    and the last of them is still the officer's fourth shot. Renumbering it
    would put a different photograph in front of anyone who later asked which
    one a measurement came from.
    """
    merged = union(
        [make_set([make_declaration("mrp", "MRP Rs. 45.00")]) for _ in range(3)],
        frame_ids=[0, 2, 3],
    )
    assert [d.frame_id for d in merged.declarations] == [0, 2, 3]


def test_frames_from_different_channels_are_refused():
    photo = make_set([make_declaration("mrp", "MRP Rs. 45.00")])
    listing = make_set([make_declaration("mrp", "MRP Rs. 45.00")], source="listing_text")
    with pytest.raises(ValueError, match="different channels"):
        union([photo, listing])


def test_an_empty_union_is_an_error_not_an_empty_set():
    with pytest.raises(ValueError, match="at least one frame"):
        union([])


def test_the_tier_is_the_best_frames_and_not_the_worst():
    """A blurrier second photograph removes nothing from the first one."""
    assert best_tier(["L3", "L0", "L2"]) == "L0"
    good = make_set([make_declaration("mrp", "MRP Rs. 45.00")], tier="L0")
    poor = make_set([make_declaration("batch", "B12")], tier="L3")
    assert union([poor, good]).degradation_tier == "L0"


def test_the_geometry_comes_from_the_declaration_panel():
    """`pdp_polygon` and `mm_per_px` belong to ONE photograph — say which."""
    face = make_set([make_declaration("marketing_text", "DELICIOUS")])
    panel = make_set(
        [
            make_declaration("mrp", "MRP Rs. 45.00"),
            make_declaration("net_quantity", "Net Wt. 250 g"),
            make_declaration("manufacturer", "Manufactured by Acme"),
        ]
    )
    assert primary_frame([face, panel]) == 1
    assert union([face, panel]).geometry.frame_id == 1


def test_captured_at_is_the_earliest_shot():
    now = datetime.now(UTC)
    first = make_set([make_declaration("mrp", "MRP Rs. 45.00")])
    second = make_set([make_declaration("batch", "B12")])
    first = first.model_copy(update={"captured_at": now})
    second = second.model_copy(update={"captured_at": now + timedelta(seconds=30)})
    assert union([second, first]).captured_at == now


def test_disagreeing_model_versions_are_kept_rather_than_overwritten():
    a = make_set([make_declaration("mrp", "MRP Rs. 45.00")])
    b = make_set([make_declaration("batch", "B12")])
    b = b.model_copy(update={"model_versions": {**b.model_versions, "detector": "geometry"}})
    merged = union([a, b])
    assert merged.model_versions["detector"] == "test | geometry"


# ---------------------------------------------------------------------------
# The point of the whole thing: evidence from one frame answers for the pack
# ---------------------------------------------------------------------------


def test_a_declaration_found_only_in_the_second_photograph_is_found(pack, biscuit_ctx):
    """The officer photographed the front; the MRP was on the back."""
    front = make_set(
        [make_declaration("generic_name", "Biscuits")],
        raw_text="CRUNCHY BISCUITS DELICIOUS",
    )
    back = make_set(
        [make_declaration("mrp", "MRP Rs. 45.00 (inclusive of all taxes)", height_mm=2.4)],
        raw_text="MRP Rs. 45.00 (inclusive of all taxes)",
    )

    alone = evaluate(front, biscuit_ctx, pack)
    together = evaluate(union([front, back]), biscuit_ctx, pack)

    assert verdict(alone, "LMPC.MRP.PRESENT").status != "PASS"
    assert verdict(together, "LMPC.MRP.PRESENT").status == "PASS"


def test_a_height_measured_in_a_calibrated_frame_survives_an_uncalibrated_one(
    pack, biscuit_ctx
):
    """One shot had the marker card in it; the rules must still get millimetres."""
    uncalibrated = make_set(
        [make_declaration("generic_name", "Biscuits")], mm_per_px=None
    )
    calibrated = make_set(
        [
            make_declaration(
                "net_quantity",
                "Net Wt. 250 g",
                height_mm=2.6,
                tolerance=0.15,
                numeral_box=Box(x=60, y=40, w=24, h=16, panel_id="pdp"),
                numeral_height_px=16,
            )
        ]
    )
    merged = union([uncalibrated, calibrated])
    assert merged.has_scale()
    assert verdict(
        evaluate(merged, biscuit_ctx, pack), "LMPC.NETQTY.NUMERAL_HEIGHT"
    ).status == "PASS"


def test_has_scale_does_not_reach_past_geometry_on_a_single_frame():
    """Tier C on one photograph means tier C, whatever a caller set by hand."""
    single = make_set([make_declaration("mrp", "MRP Rs. 45.00", height_mm=2.4)])
    single = single.model_copy(
        update={"geometry": LabelGeometry(mm_per_px=None, scale_tier="C")}
    )
    assert not single.has_scale()


# ---------------------------------------------------------------------------
# The three ways a union could fabricate a violation
# ---------------------------------------------------------------------------


def test_text_from_another_photograph_never_intrudes_on_a_clear_space(pack, biscuit_ctx):
    """Rule 8(1)'s proviso is about print NEXT TO the figure.

    Each photograph has its own rectified coordinate space, so a line from the
    second frame sits inside the first frame's exclusion zone by arithmetic
    coincidence and nothing else. This check is 40% of the blocking FAILs on the
    field corpus; multiplying its chances by the number of shots taken would be
    the single most expensive mistake available here.
    """
    panel = make_set(
        [
            make_declaration(
                "net_quantity",
                "Net Wt. 250 g",
                x=100,
                y=100,
                w=80,
                h=16,
                height_mm=2.6,
                numeral_box=Box(x=140, y=100, w=30, h=16, panel_id="pdp"),
            )
        ]
    )
    # Placed exactly where it would crowd the figure above — but photographed
    # from the other side of the pack.
    elsewhere = make_set(
        [make_declaration("marketing_text", "SPECIAL OFFER", x=100, y=124, w=80, h=14)]
    )

    merged = union([panel, elsewhere])
    assert verdict(
        evaluate(merged, biscuit_ctx, pack), "LMPC.NETQTY.EXCLUSION_ZONE"
    ).status == "PASS"

    # ... and the same two boxes in ONE photograph still fail, so the filter
    # has not disarmed the rule.
    one_frame = make_set(panel.declarations + elsewhere.declarations)
    assert verdict(
        evaluate(one_frame, biscuit_ctx, pack), "LMPC.NETQTY.EXCLUSION_ZONE"
    ).status == "FAIL"


def test_one_price_read_twice_is_not_a_pasted_over_price(pack, biscuit_ctx):
    """Rule 6(3), and the check a union could most easily be made to lie with.

    Photograph the same MRP twice, misread one digit, and a naive union hands
    the engine exactly the evidence Rule 6(3) punishes — two contradicting
    prices — on a pack that printed one. REVIEW is the honest answer: we cannot
    tell a misread from a second price, and the contract provides REVIEW for
    precisely that.
    """
    first = make_set([make_declaration("mrp", "MRP Rs. 45.00")])
    second = make_set([make_declaration("mrp", "MRP Rs. 46.00")])

    result = verdict(evaluate(union([first, second]), biscuit_ctx, pack), "LMPC.MRP.OVERSTICKER")
    assert result.status == "REVIEW"
    assert "different photographs" in result.message


def test_two_prices_in_ONE_photograph_still_fail(pack, biscuit_ctx):  # noqa: N802 - the capital is the point: ONE frame, not across frames
    """The pasted-over MRP is the demo case; it must survive the fix above."""
    both = make_set(
        [
            make_declaration("mrp", "MRP Rs. 45.00"),
            make_declaration("mrp", "MRP Rs. 60.00", y=60),
        ]
    )
    assert verdict(evaluate(both, biscuit_ctx, pack), "LMPC.MRP.OVERSTICKER").status == "FAIL"

    # And it still fails when that photograph is one of several.
    merged = union([both, make_set([make_declaration("batch", "B12")])])
    assert verdict(evaluate(merged, biscuit_ctx, pack), "LMPC.MRP.OVERSTICKER").status == "FAIL"


def test_the_same_price_read_twice_is_not_a_contradiction_at_all(pack, biscuit_ctx):
    first = make_set([make_declaration("mrp", "MRP Rs. 45.00")])
    second = make_set([make_declaration("mrp", "MRP Rs. 45.00")])
    assert verdict(
        evaluate(union([first, second]), biscuit_ctx, pack), "LMPC.MRP.OVERSTICKER"
    ).status == "PASS"


def test_grouping_cannot_be_judged_across_photographs_of_different_sides(
    pack, biscuit_ctx
):
    """Rule 8(1) is about arrangement, and arrangement is a fact about a surface."""
    front = make_set([make_declaration("mrp", "MRP Rs. 45.00", height_mm=2.4)])
    back = make_set([make_declaration("net_quantity", "Net Wt. 250 g", height_mm=2.6)])
    result = verdict(evaluate(union([front, back]), biscuit_ctx, pack), "LMPC.PDP.ON_PANEL")
    assert result.status == "NO_DATA"
    assert "more than one photograph" in result.message


# ---------------------------------------------------------------------------
# Measurement: one photograph per field, so more care never means more FAILs
# ---------------------------------------------------------------------------


def test_a_measurement_is_taken_from_the_best_calibrated_photograph():
    """Not from all of them with the worst reading kept.

    Every measurement check in `rules/checks` iterates and keeps the worst
    outcome. Across frames that means three shots give three chances for one
    soft crop to produce a FAIL — an officer taking more care making the pack
    look worse.
    """
    tier_c = make_set([make_declaration("mrp", "MRP Rs. 45.00")], mm_per_px=None)
    tier_a = make_set([make_declaration("mrp", "MRP Rs. 45.00", height_mm=2.4)])

    merged = union([tier_c, tier_a])
    assert len(merged.by_field("mrp")) == 2
    chosen = measured_for(merged, ("mrp",))
    assert [d.frame_id for d in chosen] == [1]
    assert chosen[0].height_mm == 2.4


def test_measured_for_is_a_no_op_on_a_single_photograph():
    single = make_set(
        [
            make_declaration("mrp", "MRP Rs. 45.00", height_mm=2.4),
            make_declaration("mrp", "MRP Rs. 60.00", y=60, height_mm=1.1),
        ]
    )
    assert len(measured_for(single, ("mrp",))) == 2


def test_a_short_declaration_still_fails_when_it_is_the_best_reading(pack, biscuit_ctx):
    """The reduction must not become a way for a violation to escape."""
    face = make_set([make_declaration("generic_name", "Biscuits")], mm_per_px=None)
    panel = make_set(
        [
            make_declaration(
                "net_quantity",
                "Net Wt. 250 g",
                height_mm=0.9,
                tolerance=0.15,
                numeral_height_px=6,
                numeral_box=Box(x=60, y=40, w=24, h=6, panel_id="pdp"),
            )
        ]
    )
    result = verdict(
        evaluate(union([face, panel]), biscuit_ctx, pack), "LMPC.NETQTY.NUMERAL_HEIGHT"
    )
    assert result.status == "FAIL"


# ---------------------------------------------------------------------------
# `reading_supports_an_absence` gets stronger, which is the quiet win
# ---------------------------------------------------------------------------


def test_three_thin_photographs_together_can_support_an_absence(pack, biscuit_ctx):
    """One frame naming two of six withdraws its own absences. Three do not.

    `reading_supports_an_absence` refuses to call a declaration missing when
    fewer than half the mandatory set was located, because then the silence is
    ours. A union locates more, so the guard lifts — which is the union earning
    its place rather than merely not breaking anything.
    """
    thin = [
        make_set([make_declaration("mrp", "MRP Rs. 45.00", height_mm=2.4)]),
        make_set([make_declaration("net_quantity", "Net Wt. 250 g", height_mm=2.6)]),
        make_set([make_declaration("manufacturer", "Manufactured by Acme Foods, Cuttack")]),
        make_set([make_declaration("generic_name", "Common name: Biscuits")]),
    ]
    single = verdict(evaluate(thin[0], biscuit_ctx, pack), "LMPC.DATE.PRESENT")
    merged = verdict(evaluate(union(thin), biscuit_ctx, pack), "LMPC.DATE.PRESENT")

    assert single.status in ("REVIEW", "NO_DATA")
    assert merged.status == "FAIL"
