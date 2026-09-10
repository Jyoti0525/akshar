"""The verdicts this system is not entitled to reach, and why.

Every test here was written from a defect measured on the field corpus on
2026-09-10, after a real scan of a Keventer frozen-food pack came back
"Non-compliant" with findings that were about our own reading rather than about
the pack. They are grouped by the kind of claim being made, because the kinds
fail differently:

*   **"It is not declared"** requires that we read the label well enough for an
    absence to mean anything. Guarded since 2026-09-09 by
    `reading_supports_an_absence`.
*   **"It is declared, but printed wrongly"** requires that we read *that
    declaration* faithfully. From a photograph we cannot, and the measurement
    recorded below says so.
*   **"It is printed too small"** is the one claim the project exists to make,
    and the tests here fix its direction: Rule 7(2)'s tables are floors, not
    targets.
*   **An instrument** is calibrated against known values before it is allowed
    to accuse anyone.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from contracts import Box, DeclarationSet, Verdict
from rules.checks import (
    clear_space,
    conditional_present,
    min_height_mm,
    present,
    regex,
    symbol_case,
)
from rules.engine import is_compliant
from rules.loader import cached_rulepack
from tests.unit.test_check_sweep import CONTEXT as CTX
from tests.unit.test_check_sweep import NOW, declaration, declaration_set
from vision.classify.regex_tier import classify_text
from vision.measure.contrast import _relative_luminance, contrast_ratio

pack = cached_rulepack()


def _rule(rule_id: str):
    return next(r for r in pack.all_rules(True) if r.id == rule_id)


# ---------------------------------------------------------------------------
# Rule 7(2) is a FLOOR.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("height_mm", [1.0, 1.4, 3.0, 12.0])
def test_numerals_taller_than_the_table_requires_are_compliant(height_mm: float) -> None:
    """Table I gives a MINIMUM. Taller is lawful and must never be reported.

    A 5 g sachet sits in the `<= 200 g/ml` band, which requires 1 mm. Printing
    the MRP at 3 mm is a manufacturer being generous, not a contravention, and
    a check written with `==` or with a ceiling would report every well-printed
    pack in the country.
    """
    ds = declaration_set(
        declaration("mrp", "MRP Rs. 45.00", height_mm=height_mm),
        declaration("net_quantity", "Net Wt. 5 g", height_mm=2.0),
    )

    outcome = min_height_mm.check(_rule("LMPC.MRP.NUMERAL_HEIGHT"), ds, CTX, pack)

    assert outcome.status == "PASS", f"{height_mm} mm against a 1 mm floor: {outcome.expected}"


def test_numerals_below_the_floor_still_fail() -> None:
    """The other direction, so the test above cannot be satisfied by a stub."""
    ds = declaration_set(
        declaration("mrp", "MRP Rs. 45.00", height_mm=0.4),
        declaration("net_quantity", "Net Wt. 5 g", height_mm=2.0),
    )

    assert min_height_mm.check(_rule("LMPC.MRP.NUMERAL_HEIGHT"), ds, CTX, pack).status == "FAIL"


def test_a_measurement_inside_our_own_error_is_review_not_fail() -> None:
    """0.9 mm against a 1 mm floor is our tolerance, not their contravention."""
    ds = declaration_set(
        declaration("mrp", "MRP Rs. 45.00", height_mm=0.9, height_mm_tolerance=0.15),
        declaration("net_quantity", "Net Wt. 5 g", height_mm=2.0),
    )

    assert min_height_mm.check(_rule("LMPC.MRP.NUMERAL_HEIGHT"), ds, CTX, pack).status == "REVIEW"


@pytest.mark.parametrize(
    ("net_quantity", "expected"),
    [("Net Wt. 5 g", "PASS"), ("Net Wt. 300 g", "PASS"), ("Net Wt. 900 g", "FAIL")],
)
def test_the_band_is_keyed_on_net_quantity_not_on_the_pack(
    net_quantity: str, expected: str
) -> None:
    """The same 3 mm numeral is lawful at 5 g and at 300 g and unlawful at 900 g.

    Nothing about the photograph changes between these three. Table I bands on
    the declared quantity, and `rules/checks/min_height_mm.py` calls getting
    that backwards the most consequential error available in this project.
    """
    ds = declaration_set(
        declaration("mrp", "MRP Rs. 45.00", height_mm=3.0),
        declaration("net_quantity", net_quantity, height_mm=2.0),
    )

    assert min_height_mm.check(_rule("LMPC.MRP.NUMERAL_HEIGHT"), ds, CTX, pack).status == expected


# ---------------------------------------------------------------------------
# "Printed wrongly" is a claim about print, judged on OCR output.
# ---------------------------------------------------------------------------


def test_a_format_mismatch_is_review_on_a_photograph_and_fail_on_a_listing() -> None:
    """The same text, the same rule, two channels, two verdicts -- deliberately.

    On the image channel every difference we can see between the printed form
    and the prescribed one is a difference our recogniser also invents. The
    corpus read `Serving size` as `'Servingsize'` and `For C.A. No.` as
    `'ForCA. No.'`. Per-declaration OCR confidence does not separate the two
    populations -- format FAILs ran to a median of 0.84 and a maximum of 1.00,
    format PASSes down to 0.75 -- so there is nothing honest to threshold on.
    The finding is kept, at REVIEW, where a human resolves it.

    On `listing_text` there is no recogniser between us and the characters, so
    the same mismatch is assertable. That is section 8's wall paying for
    itself: one engine, one rulepack, and the strength of the claim following
    the quality of the evidence.
    """
    label = "MRP 45"  # locates as an MRP; not the Rule 2(m) form
    rule = _rule("LMPC.MRP.FORMAT")

    photo = declaration_set(declaration("mrp", label), raw_text=label)
    listing = DeclarationSet(
        source="listing_text",
        declarations=[declaration("mrp", label)],
        raw_text=label,
        captured_at=NOW,
    )

    assert regex.check(rule, photo, CTX, pack).status == "REVIEW"
    assert regex.check(rule, listing, CTX, pack).status == "FAIL"


def test_a_format_check_reads_the_same_evidence_the_locate_step_did() -> None:
    """`locate` searches the label; `strict_text` searched one fragment.

    A date declaration split across two detected regions -- `MFD*` classified
    `mfg_date`, `06/2026` classified `other` -- located on the label and was
    then judged on `'MFD*'`, so a compliant pack was failed for a malformed
    date we had in fact read. Three corpus frames failed in exactly this way.
    """
    ds = declaration_set(
        declaration("mfg_date", "MFD*"),
        declaration("other", "06/2026"),
        raw_text="MFD* 06/2026",
    )

    outcome = regex.check(_rule("LMPC.DATE.FORMAT"), ds, CTX, pack)

    assert outcome.status == "PASS"
    assert "06/2026" in (outcome.found or "")
    assert "more than one region" in (outcome.detail or "")


# ---------------------------------------------------------------------------
# A rulepack must not contradict itself.
# ---------------------------------------------------------------------------


def test_the_litre_symbol_is_not_reported_by_the_case_rule_either() -> None:
    """`LMPC.UNIT.LITRE_SYMBOL` ships disabled because BIPM accepts `L`.

    `LMPC.UNIT.SYMBOL_CASE` reached the same symbol through its own lower-case
    list and failed `Net Content: 1L (905 g)` regardless -- an Amul ghee tin,
    and every litre pack in the country. A decision taken once has to hold
    however the symbol is reached.
    """
    ds = declaration_set(declaration("net_quantity", "Net Content: 1L (905 g)"))

    assert symbol_case.check(_rule("LMPC.UNIT.SYMBOL_CASE"), ds, CTX, pack).status == "PASS"


def test_a_genuinely_mis_cased_symbol_is_still_reported() -> None:
    """`250 ML` is still wrong, so the exemption above is not a blanket one."""
    ds = declaration_set(declaration("net_quantity", "Net Wt. 250 ML"))

    outcome = symbol_case.check(_rule("LMPC.UNIT.SYMBOL_CASE"), ds, CTX, pack)

    assert outcome.status == "FAIL"
    assert "ML" in (outcome.found or "")


def test_an_advisory_failure_does_not_make_a_package_non_compliant() -> None:
    """`250 ML` must not carry the same headline as a missing MRP.

    The unit-symbol and numeration rules ship `advisory: true` for exactly this
    reason, and `api/analytics.py` already excluded them from every published
    count. `is_compliant` did not, so the scan screen and the dashboard could
    disagree about the same scan.
    """

    def verdict(status: str, *, advisory: bool) -> Verdict:
        return Verdict(
            rule_id="LMPC.UNIT.SYMBOL_CASE" if advisory else "LMPC.MRP.PRESENT",
            rule_ref="NS Rules Third Schedule" if advisory else "Rule 6(1)(e)",
            status=status,
            severity="low" if advisory else "high",
            message="synthetic",
            expected="synthetic",
            advisory=advisory,
        )

    assert is_compliant([verdict("PASS", advisory=False), verdict("FAIL", advisory=True)])
    assert not is_compliant([verdict("FAIL", advisory=False)])


# ---------------------------------------------------------------------------
# A phrasing we cannot match is a declaration we report absent.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("printed", "field"),
    [
        # Rule 6(1)(d). `Date of Packaging` is printed on a very large share of
        # Indian food packs and matched nothing at all.
        ("Date of Packaging: 02/07/2026", "mfg_date"),
        ("Packaging Date: 02/2026", "mfg_date"),
        ("Date of Import: 07/2026", "mfg_date"),
        ("Month & Year of Manufacture: 07/2026", "mfg_date"),
        # Rule 6(1)(b), as a pack actually prints it.
        ("NAME OF COMMODITY: Micro Double Bed Sheet", "generic_name"),
        # Rule 6(2).
        ("In case of any complaint, contact:", "consumer_care"),
        ("REACH US: At marketed by address", "consumer_care"),
        # Rule 6(1)(c), where the detector put the value in another region.
        ("B.NO.:", "batch"),
        # Rule 6(1)(a): one entity that is both.
        ("Manufactured & Packed by: Amul", "manufacturer"),
    ],
)
def test_phrasings_printed_on_real_packs_are_classified(printed: str, field: str) -> None:
    assert classify_text(printed).field == field


def test_manufactured_by_is_a_person_and_date_of_manufacture_is_a_date() -> None:
    """The pair that ordering alone cannot separate.

    `manufacturer` sits above `mfg_date` in the priority list so that
    "Manufactured by: Acme Foods" is not read as a date. That same order sent
    "Month & Year of Manufacture" to `manufacturer`. The deciding word falls
    before the shared stem in one and after it in the other, so neither
    ordering can serve both.
    """
    assert classify_text("Manufactured by: Acme Foods Pvt Ltd").field == "manufacturer"
    assert classify_text("Imported by: ABC Traders").field == "importer"
    assert classify_text("Date of Mfg: 07/2026").field == "mfg_date"


def test_product_name_is_not_accepted_as_the_generic_name() -> None:
    """Rule 6(1)(b) requires the COMMON OR GENERIC name.

    "Product Name" introduces the brand -- "Dark Fantasy Yumfills" -- and
    accepting it would turn a real contravention into a pass. A locate pattern
    may be too narrow, which costs a false accusation we can see and correct;
    it may not be too wide, which costs a violation nobody ever hears about.
    """
    assert classify_text("Product Name: Dark Fantasy Yumfills").field != "generic_name"


def test_the_classifier_and_the_rulepack_share_one_definition_of_generic_name() -> None:
    """They had two, and the two had diverged.

    `vision/classify/regex_tier.py` keeps a local pattern table for fields the
    rulepack has no locate pattern for, and `generic_name` was in it by
    accident: the local copy still read `(common|generic) name` while the pack
    had grown `Name of Commodity`. The engine then reported the declaration
    present while the extractor classified the line `other`, so the report
    showed no such declaration on a pack that had one.
    """
    from vision.classify.regex_tier import _LOCAL_PATTERNS, _RULEPACK_LOCATE

    assert "generic_name" in _RULEPACK_LOCATE
    assert "generic_name" not in _LOCAL_PATTERNS


# ---------------------------------------------------------------------------
# An instrument is calibrated before it is allowed to accuse anyone.
# ---------------------------------------------------------------------------


def _published_wcag_ratio(foreground: int, background: int) -> float:
    """The WCAG 2.1 ratio for two greys -- the known answer."""
    a = float(_relative_luminance(np.full((1, 1, 3), foreground, np.uint8))[0, 0])
    b = float(_relative_luminance(np.full((1, 1, 3), background, np.uint8))[0, 0])
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


@pytest.mark.parametrize(
    ("ink", "paper"),
    [(0, 255), (0, 235), (60, 255), (110, 255), (150, 255), (255, 0), (200, 40)],
)
def test_the_contrast_estimator_returns_the_published_value(ink: int, paper: int) -> None:
    """Rule 9(1)(b) is enforced on this number, so it has to be the real one.

    It was not. The estimator took the MEAN luminance of the binarised ink and
    of the background ring, and at the pixel sizes a 1 mm character occupies in
    a shop photograph both samples are dominated by the anti-aliased edge: the
    ink mean is pulled towards the paper and the ring mean towards the ink.
    Black on white, published ratio 21.0, came back as 13.66 -- a 35%
    understatement, with the bias running 11%-35% across the range.

    On 1178 declarations from the field corpus the estimator never once
    exceeded 10.35 and put 68% of them below the 3.0 threshold, so two thirds
    of all printed matter on legible retail packaging was being reported
    illegible under Rule 9(1)(b). The tolerance here is 10% because a rendered
    glyph is not a mathematical ideal; the defect being guarded against was
    three times that and one-directional.
    """
    image = np.full((64, 320, 3), paper, np.uint8)
    cv2.putText(
        image, "MRP 145.00", (8, 48), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (ink,) * 3, 3, cv2.LINE_AA
    )

    measured = contrast_ratio(image)

    assert measured is not None
    assert measured == pytest.approx(_published_wcag_ratio(ink, paper), rel=0.10)


# ---------------------------------------------------------------------------
# Rule 8(1) proviso: what counts as printed information.
# ---------------------------------------------------------------------------


def test_a_stray_character_is_not_printed_information() -> None:
    """B2 has no trained weights, so some proposals are one character of noise.

    The corpus reported `13 intrusion(s): 14; s; a` against the net quantity
    exclusion zone. An `s` does not crowd a declaration, and a manufacturer
    cannot be asked to answer for our segmentation.
    """
    ds = declaration_set(
        declaration("net_quantity", "500 g", box=Box(x=200, y=200, w=120, h=40)),
        declaration("other", "s", box=Box(x=400, y=205, w=8, h=12)),
    )

    assert clear_space.check(_rule("LMPC.NETQTY.EXCLUSION_ZONE"), ds, CTX, pack).status == "PASS"


def test_real_printed_matter_in_the_zone_is_still_reported() -> None:
    """So the filter above cannot be satisfied by ignoring everything."""
    ds = declaration_set(
        declaration("net_quantity", "500 g", box=Box(x=200, y=200, w=120, h=40)),
        declaration("other", "NO ARTIFICIAL COLOURS", box=Box(x=340, y=205, w=180, h=30)),
    )

    assert clear_space.check(_rule("LMPC.NETQTY.EXCLUSION_ZONE"), ds, CTX, pack).status == "FAIL"


def test_a_declarations_own_label_does_not_crowd_it() -> None:
    """`Net Wt.` beside `500 g` is one declaration, not an intrusion on itself.

    `vision.classify.associate` joins a label to the figure beside it and
    demotes the label to `other`. The demoted fragment then sat inside the
    subject's own box, which a numeral-box anchor does not exclude, and was
    counted as printed information crowding the declaration it belongs to.
    """
    ds = declaration_set(
        declaration("net_quantity", "Net Wt. 500 g", box=Box(x=200, y=200, w=240, h=40)),
        declaration("other", "Net Wt.", box=Box(x=200, y=200, w=100, h=40)),
    )

    assert clear_space.check(_rule("LMPC.NETQTY.EXCLUSION_ZONE"), ds, CTX, pack).status == "PASS"


# ---------------------------------------------------------------------------
# "It is not declared" — four ways we said it about a pack that declared it
#
# All four measured 2026-09-10 over 122 field photographs, where the presence
# rules produced 48 of 100 blocking FAILs.
# ---------------------------------------------------------------------------



def _a_label_read_well_enough():
    """Enough of Rule 6(1)'s six that `reading_supports_an_absence` stands aside.

    That guard refuses to report ANY declaration missing when fewer than half
    of the six mandatory ones were found, which is right and is tested
    elsewhere. A fixture testing a different question has to clear it first, or
    it measures the guard instead of the rule.
    """
    return (
        declaration("mrp", "MRP Rs. 45.00"),
        declaration("net_quantity", "Net Wt. 100 g"),
        declaration("manufacturer", "Manufactured by: Acme Foods Pvt Ltd"),
        declaration("mfg_date", "Mfg. Date: 06/2026"),
    )


def test_a_label_the_recogniser_dropped_one_character_from_is_still_located() -> None:
    """A Mattel carton, read at 0.93 confidence, and the MRP reported undeclared.

    The recogniser returned `'Maximum Retai Price: {149.00'` for `Maximum
    Retail Price: \u20b9 149.00`, printed in the largest type on the panel.
    `mrp_locate` spells `retail`; `Retai` is not `retail`; Rule 6(1)(e) was
    reported absent. One character.
    """
    text = "Toy No : 41940 Maximum Retai Price: {149.00 (inclusive of all taxes)"
    ds = declaration_set(declaration("other", text), raw_text=text)

    assert present.check(_rule("LMPC.MRP.PRESENT"), ds, CTX, pack).status == "PASS"


@pytest.mark.parametrize(
    ("rule_id", "printed"),
    [
        ("LMPC.NETQTY.PRESENT", "ADMTFACE orc a 189 NET QOUANTITY 100g"),   # inserted O
        ("LMPC.CARE.PRESENT", "CONSUME CARE OFICE GREEN CENTRE 1800 209 0102"),  # dropped R
        ("LMPC.MFR.PRESENT", "USR (per g) Maketed By: NDSPIRATION FOP"),     # dropped r
    ],
)
def test_one_mis_read_character_does_not_make_a_declaration_absent(
    rule_id: str, printed: str
) -> None:
    """Three more, each a mandatory declaration and each genuinely printed."""
    ds = declaration_set(declaration("other", printed), raw_text=printed)
    assert present.check(_rule(rule_id), ds, CTX, pack).status == "PASS"


def test_the_tolerance_does_not_reach_a_pack_that_declares_nothing() -> None:
    """So it cannot be satisfied by finding a declaration in any text at all.

    Short words are excluded outright -- at three characters one edit reaches
    `mrs`, `map` and `nut` -- and longer ones must be within a single edit of a
    word the pattern itself spells.
    """
    text = "STORE IN A COOL DRY PLACE. NO ARTIFICIAL COLOURS. BEST ENJOYED CHILLED."
    ds = declaration_set(declaration("other", text), raw_text=text)

    assert present.check(_rule("LMPC.MRP.PRESENT"), ds, CTX, pack).status != "PASS"
    assert present.check(_rule("LMPC.NETQTY.PRESENT"), ds, CTX, pack).status != "PASS"


def test_the_tolerance_is_not_extended_to_a_listing() -> None:
    """No recogniser stood between us and those characters, so nothing is forgiven.

    Section 8's wall again: the strength of a claim follows the quality of the
    evidence, and a listing's text is exactly what the seller typed.
    """
    text = "Maximum Retai Price: 149.00"
    listing = DeclarationSet(
        source="listing_text",
        declarations=[declaration("other", text)],
        raw_text=text,
        captured_at=NOW,
    )
    assert present.check(_rule("LMPC.MRP.PRESENT"), listing, CTX, pack).status != "PASS"


def test_declaring_where_a_pack_was_made_does_not_make_it_an_import() -> None:
    """`LMPC.IMPORTER.PRESENT` triggered on any country of origin whatsoever.

    Seven of 121 frames raised a high-severity finding that no importer was
    named. Four of them print `PRODUCT OF INDIA` or `MADE IN INDIA` on the face
    of the pack, and one is a Mattel carton reading `Country of Origin :
    INDIA` directly above the declaration column. Rule 6(1)(a)'s importer limb
    is conditioned on the package being imported, and a domestic origin is
    evidence against that, not for it.
    """
    for printed in ("Country of Origin : INDIA", "MADE IN INDIA", "PRODUCT OF INDIA"):
        ds = declaration_set(
            declaration("country_of_origin", printed),
            *_a_label_read_well_enough(),
            raw_text=printed,
        )
        outcome = conditional_present.check(_rule("LMPC.IMPORTER.PRESENT"), ds, CTX, pack)
        assert outcome.status == "NOT_APPLICABLE", printed


def test_a_foreign_origin_still_asks_for_the_importer() -> None:
    """So the carve-out above cannot be satisfied by never asking at all."""
    printed = "Country of Origin : GERMANY"
    ds = declaration_set(
        declaration("country_of_origin", printed),
        *_a_label_read_well_enough(),
        raw_text=printed,
    )

    assert conditional_present.check(
        _rule("LMPC.IMPORTER.PRESENT"), ds, CTX, pack
    ).status == "FAIL"


def test_an_officer_who_says_it_is_imported_is_still_believed() -> None:
    """`also_when_context` survives the new carve-out.

    A pack can be imported and silent about it; the officer knows and the
    listing knows. That override is the reason the flag exists.
    """
    printed = "MADE IN INDIA"
    ds = declaration_set(
        declaration("country_of_origin", printed),
        *_a_label_read_well_enough(),
        raw_text=printed,
    )
    imported = CTX.model_copy(update={"is_imported": True})

    assert conditional_present.check(
        _rule("LMPC.IMPORTER.PRESENT"), ds, imported, pack
    ).status == "FAIL"


def test_an_uncaptioned_generic_name_is_referred_and_not_reported() -> None:
    """Rule 6(1)(b) does not require the word "Commodity" anywhere.

    23 of 121 frames were failed for an undeclared generic name. A besan pack
    prints `Chana Besan`, a battery card `AA 1015 R6P BATTERIES`, a namkeen
    `Crunchy Spicy Potato Noodles` -- the generic name in substance, in display
    type, with no caption on it. We can only find a declaration by its label,
    so "not declared" is a statement about our vocabulary rather than about the
    pack.
    """
    text = "Bikano Aloo Bhujia Crunchy Spicy Potato Noodles NAMKEEN NET WEIGHT: 20 g MRP 5.00"
    ds = declaration_set(
        declaration("net_quantity", "NET WEIGHT: 20 g"),
        declaration("mrp", "MRP 5.00"),
        declaration("manufacturer", "Manufactured by: Bikanervala Foods Pvt Ltd"),
        declaration("mfg_date", "PKD: 24/04/26"),
        declaration("consumer_care", "Consumer care: 1800 103 1644"),
        raw_text=text,
    )

    assert present.check(_rule("LMPC.GENERIC.PRESENT"), ds, CTX, pack).status == "REVIEW"


def test_a_captioned_generic_name_still_passes() -> None:
    """And the caption we can read is still read."""
    text = "Commodity :  Pure Camphor  Net Contents : 100 g"
    ds = declaration_set(declaration("generic_name", "Commodity :"), raw_text=text)

    assert present.check(_rule("LMPC.GENERIC.PRESENT"), ds, CTX, pack).status == "PASS"


def test_an_uncaptioned_generic_name_is_still_a_finding_on_a_listing() -> None:
    """There is no caption problem in a text listing; a field is there or it is not."""
    text = "Bikano Aloo Bhujia 20 g MRP 5.00"
    listing = DeclarationSet(
        source="listing_text",
        declarations=[
            declaration("mrp", "MRP 5.00"),
            declaration("net_quantity", "20 g"),
            *_a_label_read_well_enough(),
        ],
        raw_text=text,
        captured_at=NOW,
    )
    assert present.check(_rule("LMPC.GENERIC.PRESENT"), listing, CTX, pack).status == "FAIL"


def test_a_format_finding_quotes_the_declaration_and_not_a_slice_of_the_pack() -> None:
    """`strict_text` falls back to the whole label, and `found` quoted its first 120 characters.

    The Mattel carton's MRP finding read `'2-10\\n7+\\nFSC\\nMX\\nFSC* C161542 ...'`
    -- the top-left corner of the box, naming nothing an officer could check
    and not the declaration the finding is about.
    """
    text = (
        "2-10 7+ FSC MX FSC* C161542 BAVTRCKP or MC 684173-A Colors and decorations "
        "may vary. For Customer complaints: Call at 1800 209 0102 "
        "Maximum Retail Price 149 (inclusive of all taxes)"
    )
    ds = declaration_set(declaration("other", text), raw_text=text)

    outcome = regex.check(_rule("LMPC.MRP.FORMAT"), ds, CTX, pack)
    assert outcome.status == "REVIEW"
    assert outcome.found is not None
    assert "Maximum Retail Price" in outcome.found
    assert "FSC" not in outcome.found
