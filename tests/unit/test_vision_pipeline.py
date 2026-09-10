"""The pipeline, the ladder, the classifier and identity — sections 4, 5, 8, 14.

Two claims are load-bearing here and both are testable without any model
weights, which is exactly why they are worth testing:

1.  **The system never simply fails.** Every absent model, unreadable label and
    missing marker degrades and reports a tier. `scan()` raising is a bug.
2.  **The same rulepack judges a photograph and an e-commerce listing.** The
    third input channel is the one most teams skip, and the wall between
    extraction and decision is what makes it four lines instead of a rewrite.
"""

from __future__ import annotations

import numpy as np
import pytest

from contracts import PackageContext, ParsedQuantity
from rules.engine import evaluate, summarise
from tests.unit.synthetic import blank_label, draw_marker, draw_text, on_canvas, photograph
from vision import degradation
from vision.classify import assemble, regex_tier
from vision.identify import barcode
from vision.identify.phash import hamming, matches, normalise_for_hash, phash
from vision.ocr import crosscheck, detect_text, roi, script
from vision.pipeline import scan, scan_listing_text
from vision.types import Box, OcrLine, TextRegion

LISTING = """MRP Rs. 45.00 (inclusive of all taxes)
Net Wt. 250 g
Manufactured by: Acme Foods Pvt Ltd, Bhubaneswar, Odisha 751001
Common name: Biscuits
Mfg. Date: 03/2026
Consumer care: care@acmefoods.in, 1800 123 4567"""


@pytest.fixture
def biscuit_context() -> PackageContext:
    return PackageContext(
        category="biscuits",
        net_quantity=ParsedQuantity(value=250, unit="g", base_g_ml=250.0),
    )


def _shelf_photo(*, with_marker: bool = True):
    label = blank_label()
    draw_text(label, "MRP Rs. 45.00", baseline=(60, 120), cap_px=34)
    draw_text(label, "NET WT 250 g", baseline=(60, 230), cap_px=26)
    canvas = on_canvas(label)
    if with_marker:
        draw_marker(canvas, centre=(1010, 700), edge_px=110)
    shot, _ = photograph(canvas, tilt=0.08, yaw=0.05)
    return shot


# ---------------------------------------------------------------------------
# The three exits
# ---------------------------------------------------------------------------


def test_cache_hit_short_circuits_before_any_model():
    """Exit zero. Section 4: a repeat SKU finishes in about 60 ms."""
    seen: list[object] = []

    def lookup(identity):
        seen.append(identity)
        return "scan-abc123"

    outcome = scan(_shelf_photo(), cache_lookup=lookup)

    assert outcome.exit_path == "cache_hit"
    assert outcome.cached_scan_id == "scan-abc123"
    assert outcome.declarations is None, "a cache hit must not re-extract anything"
    assert "detect" not in outcome.timings_ms, "the detector ran on a cache hit"
    assert seen and seen[0].phash is not None


def test_scan_never_raises_whatever_weights_are_on_the_machine():
    """The bundle is not in git, so a scan must survive any subset of it.

    This asserted `tier in {L2, L3, L4}` until the OCR models were actually
    fetched, and then failed with `L0` -- on a machine that had become *better*,
    not worse. The tier was never the invariant; it is an honest report of what
    ran, and pinning it made the test a statement about one laptop's
    `data/models/` rather than about the pipeline.

    What must hold everywhere is that nothing raises, the tier is a real tier,
    and a missing recogniser is *admitted* rather than passed off as a clean
    read.
    """
    from vision.ocr import roi

    outcome = scan(_shelf_photo())

    assert outcome.exit_path in {"full", "no_package"}
    assert outcome.degradation.tier in {"L0", "L1", "L2", "L3", "L4"}
    assert outcome.message

    if not roi.is_available():
        assert outcome.degradation.tier in {"L2", "L3", "L4"}, (
            "no recogniser is loadable, so the scan must report a degraded tier "
            "rather than a confident one"
        )


def test_the_full_path_hands_back_the_frame_the_boxes_were_measured_in():
    """Section 13's exhibit depends on this, and on nothing being re-derived.

    Every `Declaration.box` is in the rectified label's coordinates. If the
    caller had to rectify again to draw them, that second call would find its own
    label quad, and a quad differing by a few pixels moves every rectangle — so
    the exhibit in the report would point at text the measurement never touched.
    The pipeline therefore returns the image it actually used.
    """
    outcome = scan(_shelf_photo())
    if outcome.exit_path != "full":
        pytest.skip("no package found in the synthetic frame on this build")

    assert outcome.rectified is not None
    assert outcome.rectified.ndim == 3


def test_a_cache_hit_carries_no_image_at_all():
    """Exit zero never rectifies, so there is nothing honest to hand back."""
    outcome = scan(_shelf_photo(), cache_lookup=lambda identity: "scan-abc123")

    assert outcome.rectified is None


def test_scan_survives_a_frame_with_nothing_in_it():
    noise = np.full((400, 600, 3), 128, dtype=np.uint8)
    outcome = scan(noise)
    assert outcome.degradation.tier == "L4"
    assert outcome.declarations is None
    # L4 still yields an identity, which is what makes the evidence record
    # worth storing at all.
    assert outcome.identity.phash is not None


def test_listing_text_runs_the_same_rules(biscuit_context, pack):
    """Section 3: the third channel is an afternoon's work, not a rewrite."""
    outcome = scan_listing_text(LISTING)
    assert outcome.declarations is not None
    assert outcome.declarations.source == "listing_text"
    assert not outcome.declarations.has_pixels()

    verdicts = evaluate(outcome.declarations, biscuit_context, pack)
    counts = summarise(verdicts)

    assert counts["FAIL"] == 0
    assert counts["PASS"] > 15, "a complete listing should satisfy most textual rules"

    # Every geometric rule must abstain, and none may FAIL.
    geometric = {
        "LMPC.MRP.NUMERAL_HEIGHT",
        "LMPC.NETQTY.NUMERAL_HEIGHT",
        "LMPC.LETTER.MIN_HEIGHT",
        "LMPC.CHAR.WIDTH_RATIO",
        "LMPC.NETQTY.EXCLUSION_ZONE",
        "LMPC.CONTRAST.NUMERALS",
    }
    for verdict in verdicts:
        if verdict.rule_id in geometric:
            assert verdict.status == "NO_DATA", (
                f"{verdict.rule_id} returned {verdict.status} on a text listing; "
                f"absence of pixels is not evidence of a violation"
            )


def test_a_listing_missing_its_mrp_fails(biscuit_context, pack):
    """The channel has to be able to find a real violation, not just pass."""
    without_mrp = "\n".join(line for line in LISTING.splitlines() if "MRP" not in line)
    outcome = scan_listing_text(without_mrp)
    assert outcome.declarations is not None

    verdicts = evaluate(outcome.declarations, biscuit_context, pack)
    failures = {v.rule_id for v in verdicts if v.status == "FAIL"}
    assert any("MRP" in rule_id for rule_id in failures), f"got {failures}"


# ---------------------------------------------------------------------------
# Degradation ladder — section 5
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"online": True, "scale_tier": "A", "coverage": 1.0, "lines_read": 6}, "L0"),
        ({"online": False, "scale_tier": "A", "coverage": 1.0, "lines_read": 6}, "L1"),
        ({"online": True, "scale_tier": "C", "coverage": 1.0, "lines_read": 6}, "L2"),
        ({"online": True, "scale_tier": "A", "coverage": 0.3, "lines_read": 6}, "L3"),
        ({"online": True, "scale_tier": "A", "coverage": 1.0, "lines_read": 0}, "L4"),
    ],
)
def test_ladder_assigns_the_documented_tier(kwargs, expected):
    assert degradation.assign(**kwargs).tier == expected


def test_the_worst_condition_wins_and_the_rest_are_still_reported():
    """An officer in a basement with no marker and a crumpled pack hits all three."""
    result = degradation.assign(online=False, scale_tier="C", coverage=0.2, lines_read=4)
    assert result.tier == "L3"
    assert len(result.reasons) == 3, result.reasons
    assert any("network" in r for r in result.reasons)
    assert any("reference object" in r for r in result.reasons)


def test_l4_is_the_only_unusable_tier():
    assert not degradation.assign(lines_read=0).is_usable
    assert degradation.assign(scale_tier="C", coverage=1.0, lines_read=5).is_usable


# ---------------------------------------------------------------------------
# Classification — section 14's hard negatives
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("MRP Rs. 45.00 (inclusive of all taxes)", "mrp"),
        ("MRP Rs. 1,250.00", "mrp"),
        ("Rs. 20 OFF", "marketing_text"),
        ("50% EXTRA FREE", "marketing_text"),
        ("Net Wt. 250 g", "net_quantity"),
        ("Drained wt. 350 g", "other"),
        ("Batch 24MRP07", "batch"),
        ("24MRP07", "batch"),
        ("8901234567890", "other"),
        ("Best before 9 months from mfg", "expiry_date"),
        ("Mfg. Date: 03/2026", "mfg_date"),
        ("Manufactured on 03/2026", "mfg_date"),
        ("Manufactured by: Acme Foods Pvt Ltd, Cuttack", "manufacturer"),
        ("Packed by: Acme Foods Pvt Ltd", "packer"),
        ("Imported by: Global Traders, Mumbai 400001", "importer"),
        ("Consumer care: 1800 123 4567", "consumer_care"),
        ("Country of origin: India", "country_of_origin"),
        ("Common name: Biscuits", "generic_name"),
        # Devanagari — Rule 9(1) permits Hindi, so these must not read as absent.
        ("अधिकतम खुदरा मूल्य 45.00", "mrp"),
        ("शुद्ध मात्रा 250 g", "net_quantity"),
        ("निर्माता: एक्मे फूड्स", "manufacturer"),
    ],
)
def test_hard_negatives_and_both_scripts(text: str, expected: str):
    assert regex_tier.classify_text(text).field == expected


def test_a_batch_code_does_not_steal_a_real_mrp_line():
    """`MRP Rs. 45.00 Batch 24MRP07` is still an MRP."""
    guess = regex_tier.classify_text("MRP Rs. 45.00 Batch 24MRP07")
    assert guess.field == "mrp"


def test_an_unlabelled_address_is_left_for_the_model_tier():
    """Regex must abstain rather than guess between four identical shapes."""
    text = "Acme Foods Pvt Ltd, Bhubaneswar, Odisha 751001"
    assert regex_tier.classify_text(text).field == "other"
    assert regex_tier.is_address_like(text)

    lines = [OcrLine(text=text, box=Box(x=0, y=0, w=100, h=10), confidence=0.9, script="latin")]
    guesses = assemble.classify_lines(lines)
    assert assemble.address_candidates(lines, guesses) == [0]


def test_every_line_reaches_raw_text_however_it_was_labelled():
    """Otherwise our own mis-classification becomes a missing declaration."""
    lines = [
        OcrLine(
            text="MRP Rs. 45.00", box=Box(x=0, y=0, w=90, h=12), confidence=0.9, script="latin"
        ),
        OcrLine(
            text="?? unreadable", box=Box(x=0, y=20, w=90, h=12), confidence=0.2, script="other"
        ),
    ]
    ds = assemble.from_lines(lines, __import__("vision.scale.tier_c", fromlist=["x"]).estimate())
    assert ds.raw_text is not None
    assert "MRP Rs. 45.00" in ds.raw_text
    assert "unreadable" in ds.raw_text


def test_a_low_confidence_reading_is_not_asserted_as_a_field():
    from vision.scale.tier_c import estimate

    lines = [
        OcrLine(
            text="MRP Rs. 45.00", box=Box(x=0, y=0, w=90, h=12), confidence=0.05, script="latin"
        )
    ]
    ds = assemble.from_lines(lines, estimate())
    assert ds.declarations[0].field == "other"
    assert "MRP" in (ds.raw_text or ""), "it must still be findable by the locate patterns"


# ---------------------------------------------------------------------------
# Identity — exit zero
# ---------------------------------------------------------------------------


def test_phash_survives_the_angle_it_is_meant_to_survive():
    """The spec delta in `normalise_for_hash`, asserted rather than asserted at.

    Hashing the raw frame misses the cache on the same pack photographed from a
    different angle, which is precisely the variation shop photography produces.
    """
    label = blank_label()
    draw_text(label, "MRP Rs. 45.00", baseline=(60, 120), cap_px=34)
    draw_text(label, "NET WT 250 g", baseline=(60, 230), cap_px=26)

    straight, _ = photograph(on_canvas(label), tilt=0.0, yaw=0.0)
    angled, _ = photograph(on_canvas(label), tilt=0.14, yaw=0.09)

    raw_distance = hamming(phash(straight), phash(angled))
    normalised_distance = hamming(
        phash(normalise_for_hash(straight)), phash(normalise_for_hash(angled))
    )

    assert normalised_distance < raw_distance
    assert matches(phash(normalise_for_hash(straight)), phash(normalise_for_hash(angled)))


def test_phash_separates_different_products():
    first = blank_label()
    draw_text(first, "MRP Rs. 45.00", baseline=(60, 120), cap_px=34)
    second = blank_label()
    draw_text(second, "MRP Rs. 199.00", baseline=(60, 150), cap_px=44)
    draw_text(second, "NET WT 1 kg", baseline=(60, 300), cap_px=40)

    a = phash(normalise_for_hash(photograph(on_canvas(first))[0]))
    b = phash(normalise_for_hash(photograph(on_canvas(second))[0]))
    assert not matches(a, b), "two different labels collided in the cache"


@pytest.mark.parametrize(
    ("code", "valid"),
    [
        # Check digits computed from the GS1 modulo-10 rule rather than copied
        # off a packet: 890103086527 weights to 115, so the check digit is 5.
        ("8901030865275", True),
        ("8901030865278", False),  # wrong check digit
        ("4006381333931", True),
        ("12345", False),
    ],
)
def test_barcode_checksum_is_verified(code: str, valid: bool):
    """A misread digit would key the cache to the wrong product entirely."""
    assert barcode.checksum_valid(code) is valid


# ---------------------------------------------------------------------------
# OCR support pieces
# ---------------------------------------------------------------------------


def test_roi_never_reads_more_than_its_budget():
    """The cap is a hard cap, whatever it is set to.

    Its *value* is a measured trade -- see `roi.MAX_REGIONS`, which moved from
    8 to 64 once batching made the marginal crop nearly free -- but that a cap
    exists at all is the discipline section 17 asks for, and a glare-covered
    pack proposing four hundred regions must not be able to spend four seconds
    proving it.
    """
    count = roi.MAX_REGIONS * 2
    regions = [
        TextRegion(box=Box(x=0, y=float(i * 20), w=100, h=12), score=0.9) for i in range(count)
    ]
    keep, skip = roi.rank_regions(regions)
    assert len(keep) == roi.MAX_REGIONS
    assert len(keep) + len(skip) == len(regions), "skipped regions must still be counted"


def test_regions_on_the_display_panel_are_read_first():
    pdp = [(0.0, 0.0), (200.0, 0.0), (200.0, 100.0), (0.0, 100.0)]
    on_panel = TextRegion(box=Box(x=10, y=10, w=50, h=8), score=0.5)
    off_panel = TextRegion(box=Box(x=10, y=400, w=50, h=30), score=0.99)

    keep, _ = roi.rank_regions([off_panel, on_panel], pdp_polygon=pdp, limit=1)
    assert keep == [on_panel], "a taller off-panel region outranked the declaration"


def test_script_of_text_reads_both_scripts():
    assert script.script_of_text("Net Wt. 250 g") == "latin"
    assert script.script_of_text("शुद्ध मात्रा") == "devanagari"
    assert script.script_of_text("250") == "other"


def test_crosscheck_withholds_rather_than_overrules():
    line = OcrLine(text="MRP 45.00", box=Box(x=0, y=0, w=80, h=10), confidence=0.5, script="latin")
    # No docTR installed: the absence of a second engine is not a disagreement.
    result = crosscheck.check_line(line, np.zeros((20, 80, 3), np.uint8))
    assert result.secondary is None
    assert not result.disagreed
    assert result.adjusted_confidence == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Which crops the ROI budget is spent on
# ---------------------------------------------------------------------------


def _region(height_px: float, *, y: float = 0.0) -> TextRegion:
    return TextRegion(box=Box(x=0.0, y=y, w=300.0, h=height_px), score=0.9)


def test_the_budget_goes_to_declaration_sized_print_not_the_brand_name():
    """The failure that `DECLARATION_BAND_MM` exists for.

    Ranked on pixel height alone -- which is what this did -- the eight crops
    are spent on the largest print, and on a retail pack that is the brand, the
    flavour and the promotional copy. Measured on the ruler set:
    `protein_powder_400g` read `'8]'`, a stray glyph and `'2'` at the cap of 8,
    while the same photograph at a cap of 40 gave up `'Net Quantity:'`,
    `'Bach No:'` and `'USE BY:'`. The recogniser was never the problem.
    """
    brand = _region(200.0)          # 21 mm of brand name
    declaration = _region(28.0)     # 2.9 mm, squarely a declaration
    fine_print = _region(9.0)       # 0.95 mm, an undersized one

    keep, _ = roi.rank_regions(
        [brand, declaration, fine_print], limit=2, mm_per_px=0.105
    )

    assert brand not in keep, "the brand name took a crop the declaration needed"
    assert declaration in keep
    assert fine_print in keep


def test_print_below_the_legal_minimum_is_still_read():
    """The band starts at 0.8 mm, under Rule 7(3)'s 1 mm, and that is the point.

    A declaration printed too small is the violation the tool exists to catch.
    A band that began at the legal minimum would rank it last, leave it unread,
    and report a *missing* declaration rather than an undersized one -- turning
    a precise FAIL into a vague one, in the manufacturer's favour.
    """
    undersized = _region(8.0)  # 0.84 mm: illegal, and readable
    brand = _region(300.0)

    keep, _ = roi.rank_regions([brand, undersized], limit=1, mm_per_px=0.105)

    assert keep == [undersized]


def test_a_generous_pack_is_not_punished_for_it():
    """Out of band is a preference, not a filter.

    A pack that prints its MRP at 15 mm is complying handsomely. If nothing
    sits inside the band there is still a budget to spend, and it must be spent
    on the nearest thing rather than on nothing.
    """
    large = _region(143.0)   # 15 mm
    huge = _region(400.0)    # 42 mm

    keep, skip = roi.rank_regions([huge, large], limit=1, mm_per_px=0.105)

    assert keep == [large], "the near miss should outrank the billboard"
    assert skip == [huge]


def test_without_a_scale_the_ordering_is_the_old_one():
    """Tier C recovers no millimetre, and the ranking must still work.

    Falling back to height is not ideal -- it is the behaviour this band was
    introduced to fix -- but it is the only ordering available when there is no
    scale, and it must not raise or silently drop every region.
    """
    tall, short = _region(200.0), _region(20.0)

    keep, _ = roi.rank_regions([tall, short], limit=1, mm_per_px=None)

    assert keep == [tall]


# --------------------------------------------------------------------------
# how large the detector's input has to be
# --------------------------------------------------------------------------


def test_without_a_scale_the_frame_is_not_thrown_away():
    """This asserted the opposite until 2026-09-10, and the opposite was wrong.

    The old rule was "tiers B and C have no millimetre, so nothing changes for
    them" -- `input_side` returned the 640 px floor. The reasoning was sound and
    the conclusion was backwards: a 4032 px photograph was then detected at a
    **6.3x downscale**, so the 1 mm print Rule 7(3) exists to measure fell below
    a pixel, was never proposed, never read and never classified. Not knowing
    how small the print is, is a reason to keep resolution rather than discard
    it.

    Measured over fifteen corpus frames: 640 px found 15 declarations, 2048 px
    found 23 (+53%), for 21.7 ms -> 225 ms of detection. Section 4 budgets
    110 ms and that breaks it -- affordably, because tier C is exactly the state
    where the three `min_height_mm` rules already return NO_DATA, so the budget
    is protecting a measurement that is not being taken.
    """
    large = np.zeros((3072, 3072, 3), dtype=np.uint8)
    assert detect_text.input_side(large, None) == detect_text.LIMIT_SIDE_MAX
    assert detect_text.input_side(large, 0.0) == detect_text.LIMIT_SIDE_MAX


def test_a_small_frame_is_never_upscaled_into_detail_it_does_not_have():
    """The clamp has two ends and the lower one matters just as much.

    Feeding a 480 px photograph to a 2048 px detector input invents nothing and
    costs three times the time, so the frame's own long side is the ceiling and
    `LIMIT_SIDE` remains the floor.
    """
    small = np.zeros((480, 640, 3), dtype=np.uint8)
    medium = np.zeros((1448, 1086, 3), dtype=np.uint8)

    assert detect_text.input_side(small, None) == detect_text.LIMIT_SIDE
    assert detect_text.input_side(medium, None) == 1448
    assert detect_text.LIMIT_SIDE <= detect_text.input_side(medium, None) <= detect_text.LIMIT_SIDE_MAX


def test_the_input_is_sized_so_the_smallest_legal_print_is_findable():
    """The derivation itself, on a frame where the ceiling does not bind.

    3072 px across 200 mm. A 1 mm capital is a line about 1.5 mm tall, and
    DBNet needs `MIN_LINE_PX_AT_INPUT` to find a line, so the input must give
    that line ten pixels. Nothing here is fitted; the span is measured, the
    1 mm is Rule 7(3), and the ten pixels came from the dev-corpus sweep.
    """
    frame = np.zeros((3072, 3072, 3), dtype=np.uint8)
    span_mm = 200.0

    side = detect_text.input_side(frame, span_mm / 3072)

    assert detect_text.LIMIT_SIDE < side < detect_text.LIMIT_SIDE_MAX
    line_px = (side / span_mm) * detect_text.SMALLEST_STATUTORY_CAP_MM * detect_text.LINE_TO_CAP
    assert line_px >= detect_text.MIN_LINE_PX_AT_INPUT


def test_the_ruler_framing_asks_for_more_than_the_ceiling_allows():
    """A measured shortfall, pinned so it cannot be forgotten.

    The 40 ruler frames are 3072 px across about 322 mm. Sizing the input for
    1 mm print would need roughly 2150 px; the latency ceiling is
    `LIMIT_SIDE_MAX`. So on those photographs a 1 mm declaration reaches the
    detector about 9.5 px tall against a measured floor of 10 -- findable
    sometimes, not reliably.

    **This is a fact about the framing, not a bug.** 2 mm print, which is 14 of
    the 20 SKUs, clears the floor comfortably at the same ceiling. Only the
    1 mm SKUs sit under it, and the honest fixes are a closer photograph or a
    higher ceiling once browser latency has actually been measured -- not a
    quieter test.
    """
    frame = np.zeros((3072, 3072, 3), dtype=np.uint8)
    span_mm = 3072 * 0.105

    side = detect_text.input_side(frame, 0.105)
    assert side == detect_text.LIMIT_SIDE_MAX

    def line_px(cap_mm: float) -> float:
        return (side / span_mm) * cap_mm * detect_text.LINE_TO_CAP

    assert line_px(1.0) < detect_text.MIN_LINE_PX_AT_INPUT
    assert line_px(2.0) >= detect_text.MIN_LINE_PX_AT_INPUT


def test_a_pack_photographed_close_does_not_pay_for_resolution_it_needs():
    """Fill the frame with one panel and 640 is already enough.

    This is the half of the derivation that saves time rather than spending it:
    the input tracks the millimetres in shot, so a close photograph is cheap.
    """
    frame = np.zeros((3072, 3072, 3), dtype=np.uint8)

    # 3072 px across 90 mm -- an officer holding the phone near the label.
    assert detect_text.input_side(frame, 90.0 / 3072) == detect_text.LIMIT_SIDE


def test_the_input_is_capped_however_wide_the_shot():
    """Detector cost grows with the square of this, and the budget is a browser."""
    frame = np.zeros((4000, 4000, 3), dtype=np.uint8)

    # A metre of shelf in frame. Recall would want an enormous input; latency
    # does not get to be sacrificed for it.
    assert detect_text.input_side(frame, 1000.0 / 4000) == detect_text.LIMIT_SIDE_MAX


def test_the_cap_is_not_below_the_floor():
    """Guards the two constants against being edited into contradiction."""
    assert detect_text.LIMIT_SIDE_MAX >= detect_text.LIMIT_SIDE
