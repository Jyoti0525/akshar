"""Declarations printed plainly that the classifier could not name.

**No OCR runs in this file, and that is the point.** Every string here is
transcribed by eye from a photograph in the corpus, exactly as the printer set
it. If a declaration cannot be named when the characters are handed over
perfectly, nothing downstream of the camera is to blame: it is a defect in the
patterns or in how they are resolved, and it would survive any improvement to
capture quality.

Section 5 puts it as *"verdicts on what was read"*. The other half of that
sentence is the one this file guards — a declaration we can read but cannot
*name* is reported to an officer as a declaration the pack does not make, and
Rule 6 violations are exactly what that produces: `GENERIC.PRESENT`,
`CARE.PRESENT`, `MFR.PRESENT`, all of them accusations of omission built on our
own failure to recognise a label.

Measured 2026-09-10 against six panels across 122 photographs: 26 of 34
required declarations were named. The eight that were not are below, each with
the pack it was read off.
"""

from __future__ import annotations

import pytest

from vision.classify.regex_tier import classify_text

# ---------------------------------------------------------------------------
# The hard negative that ate Rule 6(2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "printed",
    [
        "TOLL FREE 1800-103-1644",
        "TOLL FREE NO.1800 121 0511 OR E-MAIL",
        "Toll Free: 1800 425 1969",
    ],
)
def test_a_toll_free_number_is_consumer_care_and_not_a_promotion(printed: str) -> None:
    """`free` was a promotional word, and `TOLL FREE` is how India prints a helpline.

    `_PROMOTIONAL` is a *hard negative*: it is tested before any field pattern
    and nothing downstream can recover from it. So a bare `\\bfree\\b` did not
    merely mis-rank the consumer-care declaration, it removed it, and the pack
    was reported as naming no consumer care at all under Rule 6(2).
    """
    assert classify_text(printed).field == "consumer_care"


@pytest.mark.parametrize(
    "printed",
    ["SUGAR FREE", "GLUTEN FREE OATS", "Guilt Free", "PRESERVATIVE FREE", "EXTRA VIRGIN OLIVE OIL"],
)
def test_free_and_extra_inside_an_ordinary_claim_are_not_promotions(printed: str) -> None:
    """The same word, on the front of half the packs in the shop."""
    assert classify_text(printed).field != "marketing_text"


@pytest.mark.parametrize(
    "printed",
    ["50% EXTRA FREE", "BUY 1 GET 1 FREE", "SAVE Rs. 100/-", "Rs. 20 OFF", "FREE 50 g"],
)
def test_a_real_promotion_is_still_caught(printed: str) -> None:
    """So the narrowing above cannot be satisfied by giving up on promotions.

    A promotional price attached to a legal notice as the maximum retail price
    is the most visible error this project could make.
    """
    assert classify_text(printed).field == "marketing_text"


# ---------------------------------------------------------------------------
# Resolution: the label a line opens with
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "printed",
    [
        "BATCH No., MFD. & USE BY : SEE BELOW",   # Perfetti, Juzt Jelly
        "Batch No., Mfd. & Use By Date:",         # Dabur, Odonil 400 g
    ],
)
def test_a_combined_label_is_named_for_the_declaration_it_opens_with(printed: str) -> None:
    """One line, three declarations, and rank alone always picked the same one.

    `_PRIORITY` put `expiry_date` above `batch`, so both of these classified as
    a use-by date and Rule 6(1)(c)'s batch number was reported undeclared on a
    pack whose first printed word is BATCH. Position decides now; rank breaks
    ties. The engine locates all three either way — `searchable_text` reads the
    whole label — but the exhibit captioned the box with the wrong one, and an
    officer reads the caption.
    """
    assert classify_text(printed).field == "batch"


def test_a_hint_buried_in_a_sentence_does_not_outrank_the_label_it_opens_with() -> None:
    """Bikanervala prints Rule 6(2)'s declaration and mentions a date inside it.

    `For Consumer complaints, Write (indicating Batch No. and Mfg date)` was
    classified `mfg_date` on the strength of its last two words, because
    `_DATE_OF_PHRASE` was checked ahead of the priority list entirely.
    """
    printed = "For Consumer complaints, Write (indicating Batch No. and Mfg date)"
    assert classify_text(printed).field == "consumer_care"


@pytest.mark.parametrize(
    ("printed", "field"),
    [
        # Every reason written into `_PRIORITY` still holds: these resolve at
        # the same offset, so rank decides them exactly as it did before.
        ("Packed by: Acme Foods Pvt Ltd", "packer"),
        ("Imported by: Global Traders LLP", "importer"),
        ("Manufactured by: Acme Foods Pvt Ltd, Bhubaneswar", "manufacturer"),
        ("Manufactured & Packed By: Bikanervala Foods Pvt. Ltd.", "manufacturer"),
        ("Month & Year of Manufacture: 07/2026", "mfg_date"),
        ("Date of Packaging: 02/07/2026", "mfg_date"),
        # And the line that made `batch` sit below the mandatory declarations.
        ("MRP Rs. 45.00 Batch 24MRP07", "mrp"),
    ],
)
def test_the_orderings_priority_was_written_for_are_unchanged(printed: str, field: str) -> None:
    assert classify_text(printed).field == field


# ---------------------------------------------------------------------------
# Labels a pack prints that matched nothing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("printed", "field"),
    [
        # Rule 6(1)(b), Mattel carton. Named zero times across 122 photographs.
        ("Commodity :  Toy", "generic_name"),
        ("COMMODITY: Biscuits", "generic_name"),
        # Rule 6(1)(d), Bikanervala. `pack\\w*` takes packing and packaging but
        # not the abbreviation the pack actually prints.
        ("DATE OF PKG.:", "mfg_date"),
        # Rule 6(2), Dabur. `care cell` was covered; `Consumer Cell` was not.
        ("Regd. Office & Consumer Cell:", "consumer_care"),
        # Rule 6(1)(a), Catch. The `manufactur\\w*` stem was reporting an
        # address as a date.
        ("Manufacturing Address of PL: +91-022-48328862", "manufacturer"),
    ],
)
def test_a_label_a_pack_actually_prints_is_named(printed: str, field: str) -> None:
    assert classify_text(printed).field == field


def test_name_of_commodity_still_reaches_the_same_field_as_the_bare_label() -> None:
    """Both phrasings, one field — the divergence this pattern already cost us once."""
    assert classify_text("NAME OF COMMODITY:").field == "generic_name"
    assert classify_text("Commodity:").field == "generic_name"


def test_product_name_is_still_not_the_generic_name() -> None:
    """Widening `generic_name_locate` must not have swept the brand in with it.

    `Product Name: Dark Fantasy Yumfills` introduces the brand where Rule
    6(1)(b) requires the generic name. Accepting it turns a real violation into
    a pass, and that is the one direction of error a locate pattern may not
    take.
    """
    assert classify_text("Product Name: Dark Fantasy Yumfills").field != "generic_name"


# ---------------------------------------------------------------------------
# A price with no caption on it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("printed", ["₹ 90/-", "₹90/-", "Rs. 45/-", "₹ 149.00"])
def test_a_price_declared_without_a_caption_is_still_the_price(printed: str) -> None:
    """Kissan prints `₹ 90/-` on the lid and Mattel prints `₹ 149.00` in a column.

    Rule 6(1)(e) is satisfied by the declaration however it is introduced, and
    before this neither matched anything: the pack was reported as declaring no
    retail sale price at all.
    """
    assert classify_text(printed).field == "mrp"


@pytest.mark.parametrize("printed", ["₹ 0.45/g", "₹575.00/kg", "₹ 1.05/g"])
def test_a_unit_sale_price_is_not_the_retail_sale_price(printed: str) -> None:
    """Printed directly beside the MRP, and it is a different figure.

    `₹ 90/-  ₹ 0.45/g` is one jam lid. Reading the second as the maximum retail
    price would put the wrong number on an enforcement record, so the trailing
    per-unit suffix disqualifies it.
    """
    assert classify_text(printed).field != "mrp"


@pytest.mark.parametrize("printed", ["8901207046780", "BD4885", "A6090724", "R 1623 00:40"])
def test_a_bare_code_is_not_read_as_a_price(printed: str) -> None:
    """The widening above has to stop at things that merely contain digits.

    A barcode, a batch code and a coding-line timestamp all sit within a few
    millimetres of the price on these packs.
    """
    assert classify_text(printed).field != "mrp"


# ---------------------------------------------------------------------------
# What the contract does and does not model
# ---------------------------------------------------------------------------


def test_marketed_by_is_recorded_under_the_field_the_contract_has() -> None:
    """`Marketed by` has no field of its own, deliberately.

    Rule 6(1)(a) requires the manufacturer, packer or importer; `FieldName`
    carries those three and no `marketer`, and `manufacturer_locate` names
    `marketed by` and `mktd. by` among its forms. A Mattel carton declaring
    both `Marketed by : MATTEL TOYS (INDIA) PVT. LTD.` and `Manufactured by :
    PARKSONS CARTAMUNDI PVT.LTD.` therefore reports two `manufacturer`
    declarations rather than one of each.

    That is a modelling limit and it is recorded here rather than quietly
    tolerated: 6(1)(a) is satisfied either way, so it produces no false
    verdict, but an officer reading the exhibit sees the marketer captioned as
    a manufacturer. Distinguishing them is a contract change.
    """
    assert classify_text("Marketed by : MATTEL TOYS (INDIA) PVT. LTD.").field == "manufacturer"
    assert classify_text("Manufactured by : PARKSONS CARTAMUNDI PVT.LTD.").field == "manufacturer"
