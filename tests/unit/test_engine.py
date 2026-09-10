"""Rules-engine behaviour — AKSHAR.md sections 3, 9, 13, 18.

These tests are the reason the rulepack can be edited without fear. They cover
every check type, every status including NO_DATA and REVIEW, and boundary
values on either side of each threshold.
"""

from __future__ import annotations

import pytest

from contracts import Box, PackageContext, ParsedQuantity
from rules.engine import evaluate, is_compliant, summarise
from tests.unit.conftest import make_declaration, make_set


def verdict(verdicts, rule_id):
    for v in verdicts:
        if v.rule_id == rule_id:
            return v
    raise AssertionError(f"{rule_id} not evaluated. Got: {[v.rule_id for v in verdicts]}")


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_compliant_pack_produces_no_failures(compliant_250g, biscuit_ctx, pack):
    verdicts = evaluate(compliant_250g, biscuit_ctx, pack)
    failures = [v for v in verdicts if v.status == "FAIL"]
    assert failures == [], f"unexpected failures: {[(v.rule_id, v.found) for v in failures]}"
    assert is_compliant(verdicts)


def test_every_rule_is_evaluated(compliant_250g, biscuit_ctx, pack):
    """No rule may silently vanish — a skipped rule is an unchecked law."""
    verdicts = evaluate(compliant_250g, biscuit_ctx, pack)
    evaluated = {v.rule_id for v in verdicts}
    expected = {r.id for r in pack.all_rules() if r.enabled}
    assert evaluated == expected


def test_disabled_rule_does_not_run(compliant_250g, biscuit_ctx, pack):
    """LMPC.UNIT.LITRE_SYMBOL is disputed and ships disabled (section 13c)."""
    verdicts = evaluate(compliant_250g, biscuit_ctx, pack)
    assert "LMPC.UNIT.LITRE_SYMBOL" not in {v.rule_id for v in verdicts}


# ---------------------------------------------------------------------------
# present / conditional_present
# ---------------------------------------------------------------------------


def test_missing_mrp_fails_at_high_severity(compliant_250g, biscuit_ctx, pack):
    ds = compliant_250g.model_copy(
        update={
            "declarations": [d for d in compliant_250g.declarations if d.field != "mrp"],
            "raw_text": "Net Wt. 250 g Manufactured by: Acme Foods",
        }
    )
    v = verdict(evaluate(ds, biscuit_ctx, pack), "LMPC.MRP.PRESENT")
    assert v.status == "FAIL"
    assert v.severity == "high"


def test_consumer_care_without_telephone_fails(compliant_250g, biscuit_ctx, pack):
    """Rule 6(2): a name-and-address-only check would pass packs that fail."""
    others = [d for d in compliant_250g.declarations if d.field != "consumer_care"]
    ds = compliant_250g.model_copy(
        update={
            "declarations": [
                *others,
                make_declaration("consumer_care", "Consumer care: Acme House, Cuttack", y=280),
            ],
            "raw_text": "Consumer care: Acme House, Cuttack",
        }
    )
    assert verdict(evaluate(ds, biscuit_ctx, pack), "LMPC.CARE.PRESENT").status == "FAIL"


def test_importer_required_only_when_imported(compliant_250g, pack):
    """Rule 6(1)(a) — the importer, not the country of origin.

    This rule was reversed on 2026-09-07. It used to require a country of
    origin on the pack, citing Rule 6(10A) — which is an obligation on an
    e-commerce platform to build a filter, and says nothing about a package.
    A rule that demands a declaration the law does not require is a
    false-violation generator, so the direction now runs the other way.
    """
    ctx = PackageContext(
        category="biscuits",
        net_quantity=ParsedQuantity(value=250, unit="g", base_g_ml=250.0),
    )
    assert verdict(evaluate(compliant_250g, ctx, pack), "LMPC.IMPORTER.PRESENT").status == (
        "NOT_APPLICABLE"
    )

    imported = ctx.model_copy(update={"is_imported": True})
    assert verdict(evaluate(compliant_250g, imported, pack), "LMPC.IMPORTER.PRESENT").status == (
        "FAIL"
    )


# ---------------------------------------------------------------------------
# Locate, then validate — the most dangerous failure mode in the system
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "MRP Rs. 45.00 (inclusive of all taxes)",
        "MRP Rs. 1,250.00 (inclusive of all taxes)",
        "M.R.P. Rs 1,199.00 (incl. of all taxes)",
        "MRP Rs. 2,50,000.00 (inclusive of all taxes)",
        "Maximum retail price Rs. 999.50 (inclusive of all taxes)",
    ],
)
def test_mrp_above_one_thousand_is_never_reported_missing(label, biscuit_ctx, pack):
    """The bug that nearly shipped.

    An amount pattern of `\\d+(\\.\\d{1,2})?` matches 45.00 but not 1,250.00.
    Every product priced at Rs 1,000 or above would have been reported as
    having no MRP at all — a false accusation, at severity high, on a
    perfectly compliant pack.
    """
    ds = make_set(
        [make_declaration("mrp", label, height_mm=2.5, tolerance=0.15)],
        raw_text=label,
    )
    verdicts = evaluate(ds, biscuit_ctx, pack)
    assert verdict(verdicts, "LMPC.MRP.PRESENT").status == "PASS"
    assert verdict(verdicts, "LMPC.MRP.FORMAT").status == "PASS"


def test_bad_format_never_escalates_to_missing(biscuit_ctx, pack):
    """A strict pattern that fails tells you the label is WRONG.
    A strict pattern used to find the label tells you it is ABSENT.
    Those are different verdicts with different legal consequences.

    The format verdict is REVIEW rather than FAIL because this set has pixels:
    what we are judging is our own reading of the print, and OCR does not
    recover case, spacing or punctuation faithfully enough to accuse anyone of
    getting them wrong. What this test guards is unchanged and is the part that
    matters — the malformed declaration is still PRESENT, and no route exists
    from "written oddly" to "not declared"."""
    label = "MRP 45"  # locates, but is not the Rule 2(m) form
    ds = make_set([make_declaration("mrp", label, height_mm=2.5)], raw_text=label)
    verdicts = evaluate(ds, biscuit_ctx, pack)
    assert verdict(verdicts, "LMPC.MRP.PRESENT").status == "PASS"
    assert verdict(verdicts, "LMPC.MRP.FORMAT").status == "REVIEW"
    assert verdict(verdicts, "LMPC.MRP.FORMAT").severity == "medium"


def test_format_rule_is_silent_when_declaration_absent(biscuit_ctx, pack):
    ds = make_set([make_declaration("net_quantity", "Net Wt. 250 g")], raw_text="Net Wt. 250 g")
    v = verdict(evaluate(ds, biscuit_ctx, pack), "LMPC.MRP.FORMAT")
    assert v.status == "NOT_APPLICABLE"
    assert "LMPC.MRP.PRESENT" in (v.message or "")


# ---------------------------------------------------------------------------
# min_height_mm — Table I, boundaries, REVIEW band, bilingual
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("grams", "height_mm", "expected"),
    [
        (150, 1.0, "PASS"),  # <=200 g band needs 1 mm; exactly on the threshold
        (150, 0.5, "FAIL"),
        (250, 2.0, "PASS"),  # 200-500 band needs 2 mm; exactly on the threshold
        (250, 1.5, "FAIL"),
        (750, 4.0, "PASS"),  # >500 band needs 4 mm
        (750, 3.0, "FAIL"),
    ],
)
def test_table_one_bands_and_boundaries(grams, height_mm, expected, pack):
    ds = make_set(
        [
            make_declaration(
                "mrp", "MRP Rs. 45.00 (inclusive of all taxes)", height_mm=height_mm, tolerance=0.05
            ),
            make_declaration("net_quantity", f"Net Wt. {grams} g", y=40, height_mm=5.0),
        ]
    )
    ctx = PackageContext(
        category="unknown",
        net_quantity=ParsedQuantity(value=grams, unit="g", base_g_ml=float(grams)),
    )
    assert verdict(evaluate(ds, ctx, pack), "LMPC.MRP.NUMERAL_HEIGHT").status == expected


def test_near_threshold_is_review_not_fail(pack):
    """1.9 mm +/- 0.2 against a 2.0 mm threshold is REVIEW.

    No conviction on a 0.1 mm margin — it would be dismantled in court.
    """
    ds = make_set(
        [
            make_declaration(
                "mrp", "MRP Rs. 45.00 (inclusive of all taxes)", height_mm=1.9, tolerance=0.2
            ),
            make_declaration("net_quantity", "Net Wt. 250 g", y=40, height_mm=5.0),
        ]
    )
    ctx = PackageContext(
        category="unknown", net_quantity=ParsedQuantity(value=250, unit="g", base_g_ml=250.0)
    )
    v = verdict(evaluate(ds, ctx, pack), "LMPC.MRP.NUMERAL_HEIGHT")
    assert v.status == "REVIEW"
    assert v.measured == 1.9 and v.threshold == 2.0


def test_embossed_pack_uses_the_doubled_column(pack):
    ds = make_set(
        [
            make_declaration(
                "mrp", "MRP Rs. 45.00 (inclusive of all taxes)", height_mm=2.5, tolerance=0.05
            ),
            make_declaration("net_quantity", "Net Wt. 250 g", y=40, height_mm=5.0),
        ]
    )
    ctx = PackageContext(
        category="unknown",
        declaration_style="embossed",
        net_quantity=ParsedQuantity(value=250, unit="g", base_g_ml=250.0),
    )
    # 2.5 mm clears the 2 mm normal threshold but not the 4 mm embossed one.
    assert verdict(evaluate(ds, ctx, pack), "LMPC.MRP.NUMERAL_HEIGHT").status == "FAIL"


def test_bilingual_pack_passes_if_either_script_qualifies(pack):
    """Rule 9(4): the same declaration in two scripts at two sizes is compliant
    if the larger one clears the bar. Flagging the smaller would be wrong."""
    ds = make_set(
        [
            make_declaration(
                "mrp", "MRP Rs. 45.00 (inclusive of all taxes)", height_mm=1.2, tolerance=0.05
            ),
            make_declaration(
                "mrp", "अधिकतम खुदरा मूल्य", script="devanagari", y=25, height_mm=2.6, tolerance=0.05
            ),
            make_declaration("net_quantity", "Net Wt. 250 g", y=40, height_mm=5.0),
        ]
    )
    ctx = PackageContext(
        category="unknown", net_quantity=ParsedQuantity(value=250, unit="g", base_g_ml=250.0)
    )
    assert verdict(evaluate(ds, ctx, pack), "LMPC.MRP.NUMERAL_HEIGHT").status == "PASS"


# ---------------------------------------------------------------------------
# NO_DATA — absence of evidence is not evidence of a violation
# ---------------------------------------------------------------------------


def test_tier_c_returns_no_data_not_fail(compliant_250g, biscuit_ctx, pack):
    """With no marker, the three height rules go dark and 28 of 31 still run."""
    ds = compliant_250g.model_copy(
        update={
            "geometry": compliant_250g.geometry.model_copy(
                update={"mm_per_px": None, "scale_tier": "C"}
            )
        }
    )
    verdicts = evaluate(ds, biscuit_ctx, pack)

    for rule_id in (
        "LMPC.MRP.NUMERAL_HEIGHT",
        "LMPC.NETQTY.NUMERAL_HEIGHT",
        "LMPC.LETTER.MIN_HEIGHT",
    ):
        assert verdict(verdicts, rule_id).status == "NO_DATA"

    # The plan's headline: "Twenty-eight of the thirty-one rules still run."
    # That claim is about SCALE INDEPENDENCE, so it is asserted over all 31
    # core rules regardless of the `enabled` flag. Only three rules name
    # millimetres, so twenty-eight are scale-independent by construction.
    core = pack.rules
    assert len(core) == 31
    needs_mm = [r for r in core if r.check == "min_height_mm"]
    assert len(needs_mm) == 3
    assert len(core) - len(needs_mm) == 28, "28 of 31 rules must be scale-independent"

    # And at tier C, nothing except those three goes dark for want of scale.
    dark_for_scale = {
        v.rule_id
        for v in verdicts
        if v.status == "NO_DATA" and "scale" in (v.message or "").lower()
    }
    assert dark_for_scale == {r.id for r in needs_mm}


def test_scale_free_rules_still_run_at_tier_c(pack):
    """min_width_ratio and clear_space compare pixels against pixels."""
    narrow = [Box(x=10 + i * 8, y=10, w=2, h=16) for i in range(6)]
    ds = make_set(
        [
            make_declaration(
                "net_quantity",
                "250 g",
                char_boxes=narrow,
                numeral_box=Box(x=10, y=10, w=24, h=16, panel_id="pdp"),
            ),
        ],
        mm_per_px=None,
    )
    ctx = PackageContext(
        category="unknown", net_quantity=ParsedQuantity(value=250, unit="g", base_g_ml=250.0)
    )
    v = verdict(evaluate(ds, ctx, pack), "LMPC.CHAR.WIDTH_RATIO")
    assert v.status == "FAIL"  # 2/16 = 0.125, below one third
    assert v.measured is not None and v.measured < 0.34


def test_listing_text_channel_skips_geometry_and_keeps_the_rest(pack):
    """The same engine, no pixels at all. This is why the wall exists."""
    listing = (
        "Acme Biscuits 250 g. MRP Rs. 45.00 (inclusive of all taxes). "
        "Net Wt. 250 g. Manufactured by Acme Foods Pvt Ltd, Bhubaneswar. "
        "Consumer care 1800 123 4567. Mfg 03/2026. Common name: Biscuits"
    )
    ds = make_set(
        [
            make_declaration("mrp", "MRP Rs. 45.00 (inclusive of all taxes)", panel=None),
            make_declaration("net_quantity", "Net Wt. 250 g", panel=None),
            make_declaration("manufacturer", "Manufactured by Acme Foods Pvt Ltd", panel=None),
            make_declaration("mfg_date", "Mfg 03/2026", panel=None),
            make_declaration("generic_name", "Common name: Biscuits", panel=None),
            make_declaration("consumer_care", "Consumer care 1800 123 4567", panel=None),
        ],
        source="listing_text",
        mm_per_px=None,
        raw_text=listing,
    )
    ctx = PackageContext(
        category="biscuits", net_quantity=ParsedQuantity(value=250, unit="g", base_g_ml=250.0)
    )
    verdicts = evaluate(ds, ctx, pack)

    for rule_id in ("LMPC.MRP.NUMERAL_HEIGHT", "LMPC.PDP.ON_PANEL", "LMPC.CHAR.WIDTH_RATIO"):
        assert verdict(verdicts, rule_id).status == "NO_DATA"

    assert verdict(verdicts, "LMPC.MRP.PRESENT").status == "PASS"
    assert verdict(verdicts, "LMPC.MRP.FORMAT").status == "PASS"
    assert verdict(verdicts, "LMPC.NETQTY.SI_UNITS").status == "PASS"


# ---------------------------------------------------------------------------
# Applicability gates
# ---------------------------------------------------------------------------


def test_small_pack_is_wholly_exempt(compliant_250g, pack):
    """Rule 26(a): 10 g or less."""
    ctx = PackageContext(
        category="biscuits", net_quantity=ParsedQuantity(value=8, unit="g", base_g_ml=8.0)
    )
    verdicts = evaluate(compliant_250g, ctx, pack)
    assert all(v.status == "NOT_APPLICABLE" for v in verdicts)


def test_over_25kg_is_out_of_scope_but_cement_is_not(compliant_250g, pack):
    """Rule 3(a): cement and fertiliser stay in scope to 50 kg."""
    food = PackageContext(
        category="food", net_quantity=ParsedQuantity(value=30, unit="kg", base_g_ml=30_000.0)
    )
    assert all(v.status == "NOT_APPLICABLE" for v in evaluate(compliant_250g, food, pack))

    cement = PackageContext(
        category="cement", net_quantity=ParsedQuantity(value=30, unit="kg", base_g_ml=30_000.0)
    )
    assert any(v.status != "NOT_APPLICABLE" for v in evaluate(compliant_250g, cement, pack))


def test_industrial_consumer_is_out_of_scope(compliant_250g, pack):
    """Rule 3(b)."""
    ctx = PackageContext(category="biscuits", consumer_type="industrial")
    assert all(v.status == "NOT_APPLICABLE" for v in evaluate(compliant_250g, ctx, pack))


def test_wholesale_carton_needs_only_three_declarations(compliant_250g, pack):
    """Rule 24 — the gate most teams miss.

    Run retail rules against a wholesale carton and every scan produces four
    false violations.
    """
    ctx = PackageContext(
        category="biscuits",
        package_type="wholesale",
        net_quantity=ParsedQuantity(value=250, unit="g", base_g_ml=250.0),
    )
    verdicts = evaluate(compliant_250g, ctx, pack)
    assert verdict(verdicts, "LMPC.MRP.PRESENT").status == "NOT_APPLICABLE"
    assert verdict(verdicts, "LMPC.DATE.PRESENT").status == "NOT_APPLICABLE"
    assert verdict(verdicts, "LMPC.MFR.PRESENT").status == "PASS"
    assert verdict(verdicts, "LMPC.NETQTY.PRESENT").status == "PASS"


def test_bidi_needs_no_date_or_mrp(compliant_250g, pack):
    """Rule 6(1) provisos A and C."""
    ctx = PackageContext(
        category="bidi", net_quantity=ParsedQuantity(value=100, unit="g", base_g_ml=100.0)
    )
    verdicts = evaluate(compliant_250g, ctx, pack)
    assert verdict(verdicts, "LMPC.DATE.PRESENT").status == "NOT_APPLICABLE"
    assert verdict(verdicts, "LMPC.MRP.PRESENT").status == "NOT_APPLICABLE"


# ---------------------------------------------------------------------------
# Remaining check types
# ---------------------------------------------------------------------------


def test_banned_qualifier_in_quantity(biscuit_ctx, pack):
    ds = make_set(
        [make_declaration("net_quantity", "Net Wt. minimum 250 g")],
        raw_text="Net Wt. minimum 250 g",
    )
    assert verdict(evaluate(ds, biscuit_ctx, pack), "LMPC.QTY.BANNED_WORDS").status == "FAIL"


def test_magnitude_rule_catches_both_ends(pack):
    ctx = PackageContext(category="unknown")
    low = make_set([make_declaration("net_quantity", "Net Wt. 0.5 kg")])
    high = make_set([make_declaration("net_quantity", "Net Wt. 1500 g")])
    ok = make_set([make_declaration("net_quantity", "Net Wt. 500 g")])
    assert verdict(evaluate(low, ctx, pack), "LMPC.QTY.UNIT_MAGNITUDE").status == "FAIL"
    assert verdict(evaluate(high, ctx, pack), "LMPC.QTY.UNIT_MAGNITUDE").status == "FAIL"
    assert verdict(evaluate(ok, ctx, pack), "LMPC.QTY.UNIT_MAGNITUDE").status == "PASS"


def test_unit_symbol_case_flags_capital_ml_as_advisory(pack):
    ds = make_set([make_declaration("net_quantity", "Net Vol. 250 ML")], raw_text="Net Vol. 250 ML")
    ctx = PackageContext(category="unknown")
    v = verdict(evaluate(ds, ctx, pack), "LMPC.UNIT.SYMBOL_CASE")
    assert v.status == "FAIL"
    assert v.severity == "low" and v.advisory is True


def test_proper_name_units_keep_their_capital(pack):
    ds = make_set([make_declaration("net_quantity", "Rated 50 N")], raw_text="Rated 50 N")
    assert (
        verdict(
            evaluate(ds, PackageContext(category="unknown"), pack), "LMPC.UNIT.SYMBOL_CASE"
        ).status
        == "PASS"
    )


def test_dual_mrp_sticker_is_flagged(pack):
    ds = make_set(
        [
            make_declaration("mrp", "MRP Rs. 45.00 (inclusive of all taxes)", height_mm=2.5),
            make_declaration("mrp", "MRP Rs. 60.00 (inclusive of all taxes)", y=60, height_mm=2.5),
            make_declaration("net_quantity", "Net Wt. 250 g", y=40, height_mm=2.5),
        ]
    )
    ctx = PackageContext(
        category="unknown", net_quantity=ParsedQuantity(value=250, unit="g", base_g_ml=250.0)
    )
    assert verdict(evaluate(ds, ctx, pack), "LMPC.MRP.OVERSTICKER").status == "FAIL"


def test_lawful_reduced_price_sticker_passes(pack):
    ds = make_set(
        [
            make_declaration("mrp", "MRP Rs. 60.00 (inclusive of all taxes)", height_mm=2.5),
            make_declaration("mrp", "MRP Rs. 45.00 (inclusive of all taxes)", y=60, height_mm=2.5),
            make_declaration("net_quantity", "Net Wt. 250 g", y=40, height_mm=2.5),
        ]
    )
    ctx = PackageContext(
        category="unknown",
        sticker_or_overprint_detected=True,
        net_quantity=ParsedQuantity(value=250, unit="g", base_g_ml=250.0),
    )
    assert verdict(evaluate(ds, ctx, pack), "LMPC.MRP.OVERSTICKER").status == "PASS"


def test_declaration_off_the_principal_panel_fails(compliant_250g, biscuit_ctx, pack):
    moved = [
        d.model_copy(update={"box": d.box.model_copy(update={"panel_id": "back"})})
        if d.field == "mrp"
        else d
        for d in compliant_250g.declarations
    ]
    ds = compliant_250g.model_copy(update={"declarations": moved})
    assert verdict(evaluate(ds, biscuit_ctx, pack), "LMPC.PDP.ON_PANEL").status == "FAIL"


def test_contrast_below_threshold_fails_and_dealer_rule_suppresses(pack):
    ds = make_set(
        [
            make_declaration(
                "mrp", "MRP Rs. 45.00 (inclusive of all taxes)", height_mm=2.5, contrast=1.2
            ),
            make_declaration("net_quantity", "Net Wt. 250 g", y=40, height_mm=2.5, contrast=9.0),
        ]
    )
    ctx = PackageContext(
        category="unknown",
        sticker_or_overprint_detected=True,
        net_quantity=ParsedQuantity(value=250, unit="g", base_g_ml=250.0),
    )
    verdicts = evaluate(ds, ctx, pack)
    defaced = verdict(verdicts, "LMPC.MRP.DEFACED")
    assert defaced.status == "FAIL"
    assert defaced.respondent == "dealer"

    # One measurement, one verdict.
    suppressed = verdict(verdicts, "LMPC.CONTRAST.NUMERALS")
    assert suppressed.status == "NOT_APPLICABLE"
    assert suppressed.suppressed_by == "LMPC.MRP.DEFACED"


def _pack_size_status(pack, category: str, grams: float) -> str:
    ds = make_set([make_declaration("net_quantity", f"Net Wt. {grams:g} g")])
    ctx = PackageContext(
        category=category,
        net_quantity=ParsedQuantity(value=grams, unit="g", base_g_ml=float(grams)),
    )
    return verdict(evaluate(ds, ctx, pack), "LMPC.PACK.STANDARD_SIZE").status


@pytest.mark.parametrize(
    ("category", "grams", "expected"),
    [
        # Second Schedule entry 2: biscuits 25, 50, 75, 100, 150, 200, 250, 300,
        # "and thereafter in multiples of 100 g up to 1 kg"
        ("biscuits", 250, "PASS"),
        ("biscuits", 400, "PASS"),  # inside the "+100 to 1000" run
        ("biscuits", 1000, "PASS"),  # the ceiling itself
        ("biscuits", 237, "FAIL"),  # a real violation
        # entry 14: salt "below 50 g in multiples of 10 g", then literals
        ("salt", 30, "PASS"),  # below 50, multiple of 10
        ("salt", 35, "FAIL"),  # below 50, NOT a multiple of 10
        ("salt", 750, "PASS"),
        # entry 11: milk powder "below 50 g no restriction"
        ("milk_powder", 37, "PASS"),
        ("milk_powder", 200, "PASS"),
        ("milk_powder", 320, "FAIL"),
        # entry 18: cement — 40 kg is white cement only, accepted unconditionally
        ("cement", 40000, "PASS"),
        ("cement", 50000, "PASS"),
        ("cement", 33000, "FAIL"),
        # entry 19(c): base paint "no restriction above 4 litre"
        ("base_paint", 5000, "PASS"),
        ("base_paint", 925, "PASS"),
        ("base_paint", 1200, "FAIL"),
    ],
)
def test_second_schedule_grammar(pack, category, grams, expected):
    """The Second Schedule, gazette-verified from GSR 202(E) pp. 29-32.

    Now that the schedule is read in full rather than extracted, a mismatch is
    a FAIL rather than a REVIEW.
    """
    assert _pack_size_status(pack, category, grams) == expected


def test_fourth_schedule_is_a_list_of_exceptions(pack):
    """A commodity absent from the Fourth Schedule is governed by Rule 12(1),
    so it is NOT_APPLICABLE here — silence is not prohibition.

    Biscuits, cement, salt and tea are NOT in the Fourth Schedule. An earlier
    draft inferred them into it, which would have produced verdicts with no
    legal basis at all.
    """
    for category in ("biscuits", "cement", "salt", "tea"):
        ds = make_set([make_declaration("net_quantity", "Net Wt. 250 g")])
        ctx = PackageContext(
            category=category,
            net_quantity=ParsedQuantity(value=250, unit="g", base_g_ml=250.0),
        )
        v = verdict(evaluate(ds, ctx, pack), "LMPC.QTY.UNIT_BY_COMMODITY")
        assert v.status == "NOT_APPLICABLE", f"{category} is not a Fourth Schedule exception"


def test_fourth_schedule_unit_mismatch_now_fails(pack):
    """Ready-made garments must be declared by NUMBER (entry 22).

    Declaring them by weight is a violation, and the table is gazette-verified,
    so this is FAIL rather than REVIEW.
    """
    ds = make_set([make_declaration("net_quantity", "Net Wt. 250 g")])
    ctx = PackageContext(
        category="ready_made_garments",
        net_quantity=ParsedQuantity(value=250, unit="g", base_g_ml=250.0),
    )
    v = verdict(evaluate(ds, ctx, pack), "LMPC.QTY.UNIT_BY_COMMODITY")
    assert v.status == "FAIL"
    assert "number" in (v.expected or "")


def test_ice_cream_carries_its_amendment(pack):
    """Fourth Schedule entry 15.

    The 2011 principal text says ice cream is declared by VOLUME. The gazette's
    own footnote records that GSR 748(E) of 24-10-2011 substituted WEIGHT with
    effect from 01-07-2012. Current law is weight, and the rulepack must encode
    the amended position, not the printed one.
    """
    entry = pack.tables["unit_by_commodity"]["entries"]["ice_cream"]
    assert entry["unit"] == "weight"
    assert "748" in entry["note"]


def test_unlisted_commodity_is_not_applicable_not_a_violation(pack):
    ds = make_set([make_declaration("net_quantity", "Net Wt. 237 g")])
    ctx = PackageContext(
        category="obscure_thing",
        net_quantity=ParsedQuantity(value=237, unit="g", base_g_ml=237.0),
    )
    assert verdict(evaluate(ds, ctx, pack), "LMPC.PACK.STANDARD_SIZE").status == "NOT_APPLICABLE"


def test_devanagari_digits_flagged_as_advisory(pack):
    ds = make_set(
        [make_declaration("net_quantity", "Net Wt. ५०० g", script="devanagari")],
        raw_text="Net Wt. ५०० g",
    )
    v = verdict(evaluate(ds, PackageContext(category="unknown"), pack), "LMPC.NUM.DIGIT_FORM")
    assert v.status == "FAIL" and v.advisory is True


# ---------------------------------------------------------------------------
# Ordering and summary
# ---------------------------------------------------------------------------


def test_verdicts_are_ordered_worst_first(compliant_250g, pack):
    ds = compliant_250g.model_copy(
        update={
            "declarations": [d for d in compliant_250g.declarations if d.field != "mrp"],
            "raw_text": "Net Wt. 250 g",
        }
    )
    verdicts = evaluate(ds, PackageContext(category="biscuits"), pack)
    statuses = [v.status for v in verdicts]
    rank = {"FAIL": 0, "REVIEW": 1, "NO_DATA": 2, "NOT_APPLICABLE": 3, "PASS": 4}
    assert statuses == sorted(statuses, key=lambda s: rank[s])


def test_summarise_counts_every_status(compliant_250g, biscuit_ctx, pack):
    counts = summarise(evaluate(compliant_250g, biscuit_ctx, pack))
    assert sum(counts.values()) == len([r for r in pack.all_rules() if r.enabled])
