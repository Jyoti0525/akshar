"""Naming what the pack prints, when the recogniser mangles how it prints it.

    "it must read everything present on image to know better about image"

That was the ask, and the first thing measuring it produced was a correction to
the assumption underneath it. Of the eight labelled panels whose generic name
went unfound on 2026-09-19, **six had it read** -- clearly enough for a person
to see -- and the terms were already in the lexicon. What stood between them
was the gap between what a printer sets and what a recogniser returns:

    LIP BALM             read  'LIPBALM'
    SANITARY PADS        read  'SCENTED SANTARYPADS'
    SENDHA NAMAK         read  'Mt (Sondha Namak)'
    Product: Brush Pen   read  'Producd: Brush Pen (Assorted Shades)'
    Consumer Care Cell   read  'Consumerare Ce:Te Manager Adresso.'

A word gap is a guess the recogniser makes from pixel spacing, and display type
is where it guesses wrong. So this file is in two halves: the matching that
tolerates that, and the four guards that stop the tolerance being spent on
things that are not declarations.

No OCR runs here. Every string is what the recogniser actually returned.
"""

from __future__ import annotations

import pytest

from vision.classify import commodity
from vision.classify.regex_tier import FieldGuess, classify_text
from vision.types import Box, OcrLine


def _line(text: str, *, cap: float | None = 20.0, y: float = 0.0, x: float = 0.0) -> OcrLine:
    return OcrLine(
        text=text,
        box=Box(x=x, y=y, w=200.0, h=24.0),
        confidence=0.9,
        script="latin",
        cap_height_px=cap,
    )


def _other(n: int) -> list[FieldGuess]:
    return [FieldGuess("other", 0.1, "") for _ in range(n)]


# ---------------------------------------------------------------------------
# What OCR does to a printed word
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("read_as", "term"),
    [
        ("LIPBALM", "lip balm"),  # lipbalm.jpg -- the space is gone
        ("SCENTED SANTARYPADS", "sanitary pads"),  # whisper.jpg -- space and an I
        ("Mt (Sondha Namak)", "sendha namak"),  # rocksalt.jpg -- one letter wrong
        ("Coconut Mik", "coconut milk"),  # corpus -- one letter dropped
        ("Producd: Brush Pen (Assorted Shades)", "brush pen"),  # camlinbrush.jpg
    ],
)
def test_a_commodity_is_found_through_the_way_it_was_read(read_as: str, term: str) -> None:
    assert commodity.match(read_as) == term


def test_a_term_is_still_matched_on_whole_tokens_only() -> None:
    """Welding words together is allowed; starting or ending inside one is not.
    That is the word-boundary rule restated in a form that survives a lost gap.
    """
    assert commodity.match("OPEN HERE") is None
    assert commodity.match("SHARPENER") == "sharpener"
    assert commodity.match("BALL POINT PEN") == "ball point pen"


def test_short_terms_are_matched_exactly_and_never_approximately() -> None:
    """`salt`, `soap`, `ghee`, `tea` and `pen` are one edit from a dozen
    ordinary words each. Everything under six characters is exact."""
    assert commodity.match("SALT") == "salt"
    assert commodity.match("SILT") is None
    assert commodity.match("SALE") is None
    assert commodity.match("SOAK") is None
    assert commodity.match("TEAM") is None


def test_an_exact_match_beats_an_approximate_one_anywhere_in_the_lexicon() -> None:
    """`toffee` and `coffee` are both commodities and one edit apart. A single
    pass in term-length order would let one claim a line spelling the other."""
    assert commodity.match("TOFFEE") == "toffee"
    assert commodity.match("COFFEE") == "coffee"


def test_the_consumer_care_caption_survives_a_lost_word_gap() -> None:
    """camlinbrush.jpg. `Consumer Care Cell:` came back as `Consumerare Ce:`,
    and Rule 6(2)'s declaration was invisible on a pack that prints it."""
    assert classify_text("Consumerare Ce:Te Manager Adresso., e:22-6655700").field == (
        "consumer_care"
    )
    assert classify_text("CONSUMER CARE CELL").field == "consumer_care"
    assert classify_text("Customer Care No : 022-28334457").field == "consumer_care"


# ---------------------------------------------------------------------------
# Four guards, because tolerance is precision spent in advance
# ---------------------------------------------------------------------------


def test_a_legal_entity_is_not_a_commodity() -> None:
    """`is_address_like` wants two signals before it calls a line an address,
    which is right for what it gates. `HALDIRAM SNACKS FOOD PRIVATE UMITED`
    scored one, and was declared the pack's generic name on the word `snacks`.
    """
    assert commodity.match("HALDIRAM SNACKS FOOD PRIVATE UMITED") is None
    assert commodity.match("Rishabh Plast India Private Limited") is None
    assert commodity.match("Kokuyo Camlin Ltd.") is None


def test_marketing_copy_about_a_commodity_is_not_a_declaration_of_it() -> None:
    assert commodity.match("Explore our delicious range of cookies!") is None
    assert commodity.match("Enjoy our tea") is None


def test_an_ingredient_fragment_under_its_heading_is_not_the_generic_name() -> None:
    """Nothing in `Milk and Mustard` says what it is: short, uncaptioned, not
    an address, no prose marker. Where it sits says it -- directly under
    `INGREDIENTS:`, which is named correctly and is right above it."""
    lines = [
        _line("INGREDIENTS:", cap=10.0, y=0.0),
        _line("Milk and Mustard", cap=10.0, y=30.0),
        _line("lodized Salt, Spices", cap=10.0, y=60.0),
    ]
    guesses = [FieldGuess("ingredients", 0.85, ""), *_other(2)]

    assert commodity.identify(lines, guesses) is None


def test_a_line_in_display_type_is_not_the_body_of_the_list_above_it() -> None:
    """coconut_oil.jpg: `INGREDIENT:` at 11 px with `Coconut Oil` at 14 px
    under it -- the pack's sole ingredient and its generic name, printed in
    display type. Geometry alone called it list body and the pack lost the only
    declaration it had, which then read as `no_declaration_panel`."""
    lines = [
        _line("INGREDIENT:", cap=11.0, y=0.0),
        _line("Coconut Oil", cap=14.0, y=30.0),
    ]
    guesses = [FieldGuess("ingredients", 0.85, ""), *_other(1)]

    found = commodity.identify(lines, guesses)

    assert found is not None
    assert found[1] == "coconut oil"


def test_a_table_row_is_not_a_heading_and_claims_nothing_beneath_it() -> None:
    """rocksalt.jpg sets its nutrition table one nutrient per line, so
    `Energy`, `Sodium`, `Calcium` and `Carbohydrate` were each named
    `nutrition` -- correctly -- and each anchored a walk of its own. One ran
    down the panel and swallowed the pack's generic name."""
    lines = [
        _line("Calcium", cap=17.0, y=0.0),
        _line("Mt (Sondha Namak)", cap=18.5, y=30.0),
    ]
    guesses = [FieldGuess("nutrition", 0.85, ""), *_other(1)]

    found = commodity.identify(lines, guesses)

    assert found is not None
    assert found[1] == "sendha namak"


def test_a_nutrient_word_is_reclaimed_only_when_it_is_the_whole_line() -> None:
    """`sugar` is a nutrient and a commodity packs are sold as. On sugar.jpg
    the generic name is `CRYSTAL SUGAR` in the largest type on the panel and
    `_NUTRITION` claimed it. `TOTAL SUGARS` is not a term and keeps its name."""
    claimed = [_line("CRYSTAL SUGAR", cap=17.0)]
    assert commodity.identify(claimed, [FieldGuess("nutrition", 0.85, "")]) == (
        0,
        "crystal sugar",
    )

    row = [_line("TOTAL SUGARS", cap=8.0)]
    assert commodity.identify(row, [FieldGuess("nutrition", 0.85, "")]) is None


def test_the_nutrition_panel_keeps_its_column_labels() -> None:
    """Packs set the table in two columns and the detector returns each as its
    own region, so the nutrient names arrive with no figure beside them.
    Requiring one cost 192 correctly named rows across the corpus."""
    for text in ("ENERGY", "PROTEIN", "CARBOHYDRATE", "TOTAL SUGARS", "TRANS FAT"):
        assert classify_text(text).field == "nutrition", text


def test_a_nutrition_row_is_named_before_the_price_guard_sees_it() -> None:
    """`Sugars` ends in the two letters `rs`, and the bare-price pattern reads
    `rs` with no letter boundary in front of it -- deliberately, because
    `MRPRS.750` is a real line off a real pack. Seventeen nutrition rows were
    read as carrying a price and fell through to the declaration patterns."""
    assert classify_text("Total Sugars 13.5g").field == "nutrition"
    assert classify_text("OF WHICH SUGARS 24.8g").field == "nutrition"
