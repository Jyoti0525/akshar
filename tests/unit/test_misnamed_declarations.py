"""Three ways a line was given a name that was not its own.

All three were reported from live testing on 2026-09-19 and all three were then
measured on real text: 739 distinct lines read off the 38 labelled panels and
9,771 read off the 469-frame corpus, classified before and after.

**These are precision defects, and precision is the thing this project has.**
A wrong name does not merely lose a declaration -- it puts a box on the
officer's exhibit asserting something the pack does not say. A consumer-care
sentence labelled `FSSAI licence`, a manufacturer's name labelled a
manufacturing date: both are the system speaking with confidence about a pack
it has misread, which is worse than saying nothing.

No OCR runs here. Every string is what the recogniser actually returned,
copied out of those two dumps, so a failure in this file is a failure in the
patterns and nowhere else.
"""

from __future__ import annotations

import pytest

from vision.classify.regex_tier import classify_text

# ---------------------------------------------------------------------------
# 1. A licence caption is not a licence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # ghee.jpg. Four words clipped out of "quote the Batch No. and License
        # No., please" -- a consumer-care sentence, named an FSSAI licence.
        "License No., pleas",
        "Lic No. scn the R cod ande",
        "By Addrtused PrdcessA Lic. No.",
        "For Manufacturer'sLic No. see first",
        "leter identifies te packaging unit & Lic. No.",
        "M,N.LIc.No",
    ],
)
def test_a_licence_phrase_with_no_number_after_it_is_not_a_licence(text: str) -> None:
    assert classify_text(text).field != "fssai_licence"


@pytest.mark.parametrize(
    "text",
    [
        "Lic. No. 10012022001320",  # cheese.jpg
        "Lic No.10015043001129LOT No.",  # jimjam.jpg
        "Lic.No.12019013000386",  # sugar.jpg
        "Lic. No.001504300129",  # goodday.jpg
        "/ssCIf Lic, No. 10015022003936",  # udadpapad.jpg -- caption mangled
        "LIC. NO.: 10U12U1200066",  # two marks where the pattern allowed one
        "LIC. No.-1001404700042",
        "LICN0.10030210",  # the O read as a zero
        "ssaiLicense No.1001404700153",  # welded to the word before it
        "OLIC NO 1012013",
        "ANLIC. NO.10104",
        "FSSAI",
    ],
)
def test_a_licence_printed_on_a_pack_is_still_named(text: str) -> None:
    assert classify_text(text).field == "fssai_licence"


def test_a_public_notice_is_not_a_licence() -> None:
    """`PUBLIC NOTICE` carries the letters `lic no`, which is why the phrase
    once needed a word boundary in front of it. The boundary was refusing real
    licences welded to the word before them; the digit refuses this instead,
    and refuses it for the reason that actually distinguishes the two."""
    assert classify_text("PUBLIC NOTICE").field != "fssai_licence"
    assert classify_text("METALLIC NOTES").field != "fssai_licence"


# ---------------------------------------------------------------------------
# 2. A manufacturer is a person, not a date
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # pickle.jpg. `MKD` is `MKTD` with the t dropped by OCR, and the veto
        # could not see a role word between the conjunction and the `by`.
        ("MFD & MKD By", "manufacturer"),
        ("Mfd. & Mktd. by:", "manufacturer"),
        ("Mfd. & Mktd. By:", "manufacturer"),
        ("Manufactured for:", "manufacturer"),
        ("MANUFACTURED FOR:LIC. No.10013022002253", "manufacturer"),
        # Found by nobody before: five marketer declarations that were `other`.
        ("Mkt By: HINDUSTAN UNILEVER", "manufacturer"),
        ("Mkt. by: PepsiCo India Holdings PM. Ld", "manufacturer"),
        ("Mktby Tata Consumer Products", "manufacturer"),
        ("MKT.BY:", "manufacturer"),
        ("Manufacturer's Address or Cal our Customer Care Executive", "consumer_care"),
    ],
)
def test_a_line_naming_a_person_is_not_named_a_date(text: str, expected: str) -> None:
    assert classify_text(text).field == expected


@pytest.mark.parametrize(
    "text",
    [
        # sugar.jpg, both of them. Running prose whose subject is a commodity.
        "reliable growers and manufacturers to",
        "Our products are processed and packed with",
        "Deightfully reamy, and packed with",
    ],
)
def test_a_sentence_mentioning_manufacture_is_not_a_manufacturing_date(text: str) -> None:
    """The stem was bare, so the plural agent noun matched it and so did
    `packed with`. A *manufacturer* is a person and can never be a date; what
    follows `packed` says which of the two the word meant."""
    assert classify_text(text).field != "mfg_date"


@pytest.mark.parametrize(
    "text",
    [
        "PACKED ON 09-08-2023",  # udadpapad.jpg
        "MFD 12/2024",  # camlinbrush.jpg
        "PKD: 27/DEC/2024",  # ghee.jpg
        "MANUFACTURED ON :",  # bajaj.jpg
        "Mfg. Date: 11-2023",  # santoor.jpg
        "Month & Year of Packing",  # rice.jpg
        "Date of Pkg.:",  # cheese.jpg
        "MFD:12/23",  # gillete.jpg
        "Month of Pkd. : 30SEP-20",  # milksoap.jpg
    ],
)
def test_the_dates_the_packs_actually_print_are_still_dates(text: str) -> None:
    """The vetoes above are narrow on purpose. Every one of these was read off
    a panel in the labelled set and every one is a Rule 6(1)(d) declaration."""
    assert classify_text(text).field == "mfg_date"


# ---------------------------------------------------------------------------
# 3. The caption guard that was not guarding
# ---------------------------------------------------------------------------


def test_a_declaration_caption_still_blocks_a_non_statutory_name() -> None:
    """`_DECLARATION_CAPTION` is called "the whole safety of this block" in its
    own docstring, and its `manufactur` entry was word-bounded at both ends --
    so it matched the word `manufactur`, which nothing prints, and not
    `Manufactured`, which everything does. Across 10,510 real lines it fired
    once; completed, it fires 56 times."""
    guessed = classify_text("MANUFACTURED FOR:LIC. No.10013022002253").field
    assert guessed != "fssai_licence"


# ---------------------------------------------------------------------------
# 4. A licence number is not a date
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # The line off the face serum carton, exactly as the recogniser
        # returned it. It was boxed on the officer's exhibit as "Date of
        # manufacture, 1.39 mm".
        "Mfg. Lic. No.: JK/21-22/C0S-8/334",
        "Mfg Licence No: KA/123/2020",
        "Manufacturing Lic. No. ABC/12/34",
    ],
)
def test_a_manufacturing_licence_is_not_a_manufacturing_date(text: str) -> None:
    assert classify_text(text).field == "licence"


def test_a_cosmetics_licence_is_not_called_an_fssai_licence() -> None:
    """Different statute, different issuing authority. Putting the words
    "FSSAI licence" on an exhibit beside a State cosmetics licence number is
    the sort of error that gets a notice set aside."""
    assert classify_text("Mfg. Lic. No.: JK/21-22/COS-8/334").field != "fssai_licence"
    assert classify_text("Lic. No. 10012022001320").field == "fssai_licence"


def test_a_licence_number_on_a_line_with_a_real_declaration_loses() -> None:
    """The caption guard is what keeps a non-statutory name from swallowing a
    declaration printed beside it, and widening it for `lic` must not open
    that door."""
    assert classify_text("Net Wt 500 g Lic No 12345678901234").field == "net_quantity"
    assert classify_text("MRP Rs 45 Lic No AB/12/34").field == "mrp"


def test_the_dates_on_those_same_packs_are_still_dates() -> None:
    assert classify_text("Mfg. Date: 11-2023").field == "mfg_date"
    assert classify_text("MFD 12/2024").field == "mfg_date"
