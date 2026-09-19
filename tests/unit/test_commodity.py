"""The commodity lexicon — `vision/classify/commodity.py`.

Rule 6(1)(b)'s generic name is the one declaration packs habitually print with
no caption, which is why the caption patterns found 1 of 27 on the labelled
panels. This tier recognises the commodity noun itself.

Most of these tests are named after the photograph that produced them. That is
deliberate: a word list is the easiest thing in this repository to widen
carelessly, and the failures worth pinning are the ones real packs caused.
"""

from __future__ import annotations

import pytest

from vision.classify import assemble, commodity
from vision.classify.regex_tier import FieldGuess
from vision.types import Box, OcrLine


def _is_devanagari(term: str) -> bool:
    return any("ऀ" <= ch <= "ॿ" for ch in term)


def _line(text: str, *, cap: float | None = 20.0, y: float = 0.0) -> OcrLine:
    return OcrLine(
        text=text,
        box=Box(x=0.0, y=y, w=200.0, h=30.0),
        confidence=0.9,
        script="latin",
        cap_height_px=cap,
    )


# ---------------------------------------------------------------------------
# What it is for: the uncaptioned generic name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "term"),
    [
        ("Coconut Oil", "coconut oil"),
        ("BALL POINT PEN", "ball point pen"),
        ("Incense Stick", "incense stick"),
        ("LED LAMPS", "led lamps"),
        ("DETERGENT CAKE", "detergent cake"),
        ("SCENTED SANITARY PADS", "sanitary pads"),
        # Two names for one commodity on one line, and the longer wins. It read
        # `rock salt` until `sendha namak` was added to the lexicon on
        # 2026-09-19; both are the right answer and the reason string now
        # carries the one the pack prints second.
        ("HIMALAYAN ROCK SALT / SENDHA NAMAK", "sendha namak"),
        ("Brush Pen (Assorted Shades)", "brush pen"),
    ],
)
def test_a_commodity_printed_without_a_caption_is_found(text: str, term: str) -> None:
    assert commodity.match(text) == term


def test_the_longest_term_wins_so_the_reason_is_the_specific_one() -> None:
    """`Toilet Soap` is a narrower declaration than `soap`, and the reason
    string is shown to an officer, so it must carry the narrower one."""
    assert commodity.match("Toilet Soap") == "toilet soap"
    assert commodity.match("Bathing Bar") == "bathing bar"


def test_devanagari_is_matched_on_the_same_terms_as_latin() -> None:
    """Section 15b asks for explicit Hindi support. A pack that prints its
    commodity only in Devanagari has declared it."""
    assert commodity.match("फेस क्रीम") == "फेस क्रीम"
    assert commodity.match("अगरबत्ती") == "अगरबत्ती"


def test_a_term_matches_only_on_whole_words() -> None:
    """`pen` is a commodity; `OPEN` and `PENCIL` are not it."""
    assert commodity.match("BALL POINT PEN") == "ball point pen"
    assert commodity.match("OPEN HERE") is None
    assert commodity.match("PENCIL") == "pencil"


# ---------------------------------------------------------------------------
# Precision. The set scores P 0.98 and this tier may not spend it.
# ---------------------------------------------------------------------------


def test_a_commodity_word_inside_an_ingredient_list_is_not_a_declaration() -> None:
    assert commodity.match("Contains wheat flour, sugar, edible vegetable oil") is None
    assert commodity.match("INGREDIENTS: SUGAR, MILK SOLIDS, COCOA BUTTER") is None


def test_a_commodity_word_inside_a_storage_instruction_is_not_a_declaration() -> None:
    """`associate.py` records this line welding itself to a net-quantity label
    on cheese.jpg; storage copy is where commodity nouns hide."""
    assert commodity.match("ALWAYS KEEP UNDER REFRIGERATION BELOW 4C") is None
    assert commodity.match("Store in a cool dry place away from sunlight") is None


def test_a_long_line_is_refused_before_the_lexicon_is_consulted() -> None:
    long_line = " ".join(["soap"] * (commodity.MAX_WORDS + 1))
    assert commodity.match(long_line) is None


def test_the_ghee_jar_manufacturer_is_not_read_as_a_commodity() -> None:
    """ghee.jpg, 2026-09-19, and the reason `_PRODUCT_CAPTION` exists.

    The recogniser made `'Met:-dby: GujaratCo-operatve Milk'` of the
    manufacturer's line. Too mangled for `manufacturer_locate`, so it arrived
    here as `other` carrying the word `milk`, and the pack was credited with
    declaring a commodity it had not declared. The caption is the
    discriminator: `Met`/`-dby` names no product, so the line is not ours.
    """
    assert commodity.match("Met:-dby: GujaratCo-operatve Milk") is None
    assert commodity.match("MFD BY: HIMALAYA MILK DAIRY LTD") is None


def test_an_address_is_never_read_as_a_commodity() -> None:
    """A dairy, an oil mill and a match works all carry a commodity in the
    trading name."""
    assert commodity.match("Gujarat Co-operative Milk Marketing Federation Ltd") is None


def test_a_product_caption_is_believed_but_only_for_an_actual_commodity() -> None:
    """pencilbox.webp prints `PRODUCT: METAL PENCIL BOX`, which is a real
    declaration, so the caption may not simply be a rejection.

    The rulepack refuses `Product Name` as a *locate* pattern because what
    follows it is as often the brand. That concern does not reach here: this
    tier never accepts the caption's word for it, only a term from the lexicon.
    """
    assert commodity.match("PRODUCT: METAL PENCIL BOX") == "pencil box"
    assert commodity.match("Commodity: Tea") == "tea"
    # The rulepack's own worked example of the trap, and it is refused.
    assert commodity.match("Product Name: Dark Fantasy Yumfills") is None


# ---------------------------------------------------------------------------
# `identify` — one per pack, and only over lines nothing else claimed
# ---------------------------------------------------------------------------


def test_a_line_another_tier_already_named_is_never_taken() -> None:
    lines = [_line("Toilet Soap")]
    claimed = [FieldGuess("marketing_text", 0.9, "already decided")]
    assert commodity.identify(lines, claimed) is None


def test_where_several_lines_match_the_one_in_display_type_wins() -> None:
    """The generic name is set on the principal panel in display type; a
    commodity noun in body copy is not the declaration."""
    lines = [_line("soap", cap=8.0, y=100.0), _line("Toilet Soap", cap=40.0, y=10.0)]
    other = [FieldGuess("other", 0.1, ""), FieldGuess("other", 0.1, "")]

    found = commodity.identify(lines, other)

    assert found is not None
    assert found[0] == 1
    assert found[1] == "toilet soap"


def test_a_line_with_no_measured_cap_height_can_still_win_if_it_is_the_only_one() -> None:
    """`cap_height_px` is None where the crop gave no clean baseline. Such a
    line loses on display type; it is not thrown away."""
    lines = [_line("Coconut Oil", cap=None)]
    found = commodity.identify(lines, [FieldGuess("other", 0.1, "")])

    assert found is not None
    assert found[1] == "coconut oil"


def test_nothing_recognised_is_an_answer() -> None:
    lines = [_line("Dark Fantasy Yumfills"), _line("Santoor")]
    other = [FieldGuess("other", 0.1, ""), FieldGuess("other", 0.1, "")]
    assert commodity.identify(lines, other) is None


def test_the_reason_names_the_term_an_officer_can_look_up() -> None:
    guess = commodity.guess("toilet soap")

    assert guess.field == "generic_name"
    assert "toilet soap" in guess.reason
    assert guess.confidence == commodity.CONFIDENCE
    assert guess.confidence >= assemble.MIN_EMIT_CONFIDENCE


def test_this_tier_scores_below_a_captioned_match() -> None:
    """A caption is the pack telling us what a line is; this is us recognising
    a word. The number reaches the report, so the ordering has to be real."""
    assert commodity.CONFIDENCE < 0.80


# ---------------------------------------------------------------------------
# Wiring: last tier, and it stands down where a generic name already exists
# ---------------------------------------------------------------------------


def test_the_classifier_names_the_commodity_when_no_caption_did() -> None:
    lines = [_line("Toilet Soap"), _line("Net Wt. 100 g")]
    guesses = assemble.classify_lines(lines)

    assert guesses[0].field == "generic_name"


def test_a_captioned_generic_name_is_never_overridden() -> None:
    """A pack declares its commodity once. A second claim is the duplicate-MRP
    failure of 2026-09-19 reappearing in another field."""
    lines = [_line("Name of Commodity: Tea"), _line("Toilet Soap")]
    guesses = assemble.classify_lines(lines)

    named = [index for index, guess in enumerate(guesses) if guess.field == "generic_name"]
    assert len(named) == 1


def test_a_pack_with_no_recognised_commodity_is_unchanged() -> None:
    """The safe direction. `uncaptioned_form_is_lawful` already routes a
    missing generic name to REVIEW, so failing to recognise one costs an
    officer a look and never produces a contravention."""
    lines = [_line("Dark Fantasy Yumfills"), _line("Net Wt. 100 g")]
    guesses = assemble.classify_lines(lines)

    assert all(guess.field != "generic_name" for guess in guesses)


# ---------------------------------------------------------------------------
# The list itself
# ---------------------------------------------------------------------------


def test_no_term_is_short_enough_to_collide_with_a_unit() -> None:
    """Two Latin letters would put `ml`, `gm` and `kg` into play.

    Devanagari carries a whole syllable per character and gets its own floor:
    applying the Latin minimum to both scripts left `घी` -- ghee -- in the
    lexicon but unreachable, which is worse than omitting it, because the list
    then claims a coverage it does not have.
    """
    for term in commodity.TERMS:
        floor = commodity.MIN_DEVANAGARI_CHARS if _is_devanagari(term) else commodity.MIN_TERM_CHARS
        assert len(term) >= floor, f"{term!r} is below its script's minimum"


def test_every_term_in_the_lexicon_can_actually_be_matched() -> None:
    """A term the matcher skips is a silent claim of coverage. Found by the
    test above when `घी` sat in the list and could never fire."""
    for term in commodity.TERMS:
        assert commodity.match(term) is not None, f"{term!r} is in the lexicon but unreachable"


def test_terms_are_ordered_longest_first_so_the_specific_match_is_found() -> None:
    lengths = [len(term) for term in commodity.TERMS]
    assert lengths == sorted(lengths, reverse=True)


def test_no_brand_has_crept_into_the_lexicon() -> None:
    """6(1)(b) wants the commodity, never the marque. A brand here would make
    this tier assert a generic name from a trademark, which is the error the
    rulepack refuses `Product Name` to avoid."""
    brands = {"parle", "britannia", "santoor", "surf excel", "amul", "doms", "camlin",
              "whisper", "lifebuoy", "colgate", "maggi", "nescafe", "tata", "dettol"}
    assert not (brands & set(commodity.TERMS))
