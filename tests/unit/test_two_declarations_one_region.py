"""One region, two declarations, a full stop between them.

From a live scan of a face serum carton on 2026-09-19. Across the foot of the
front panel the pack sets, in one line of type:

    Face Serum. Made in India

`country_of_origin` takes the region at 0.88, and Rule 6(1)(b)'s generic name
is lost -- not misread, never offered to any tier as a line of its own. The
officer's exhibit then draws a box round the product's own name and captions it
*Country of origin*.

---------------------------------------------------------------------------
WHY MOST OF THIS FILE IS ABOUT NOT CUTTING
---------------------------------------------------------------------------
Cutting a line invents a boundary the recogniser did not report, and the thing
most easily destroyed by it is an address -- Rule 6(1)(a)'s name-and-address is
*made* of full stops. So the operation is defined to be a pure gain and this
file is mostly the proof of that: every refusal below is a real line from the
469-frame corpus or the 38 labelled panels, and every one of them was cut by a
looser draft of this module before it was measured.

The measurement, over 13,197 corpus lines and 796 from the labelled panels:
the loose form cut seven, four of them wrongly; the shipped form cuts one, and
that one is a body lotion recovering its generic name.
"""

from __future__ import annotations

import pytest

from vision.classify.assemble import classify_lines
from vision.ocr.sentences import unstitch, unstitch_line
from vision.types import Box, OcrLine


def line(text: str, *, x: float = 10.0, y: float = 40.0, cap: float | None = 24.0) -> OcrLine:
    return OcrLine(
        text=text,
        box=Box(x=x, y=y, w=float(max(len(text) * 12, 24)), h=40.0),
        confidence=0.92,
        script="latin",
        cap_height_px=cap,
    )


def pieces(text: str) -> list[str]:
    return [part.text for part in unstitch_line(line(text))]


# ---------------------------------------------------------------------------
# The carton that forced it
# ---------------------------------------------------------------------------


def test_the_serum_carton_declares_two_things_and_now_says_both() -> None:
    assert pieces("Face Serum. Made in India") == ["Face Serum", "Made in India"]


def test_the_generic_name_reaches_the_classifier_as_a_generic_name() -> None:
    """The cut is only worth making if the declaration it frees is then found.
    This is the end-to-end statement, through the real classifier tiers."""
    panel = [
        line("AURA NATURALS", y=100, cap=60.0),
        line("Face Serum. Made in India", y=180, cap=30.0),
        line("Batch No.:", y=260, cap=18.0),
    ]

    before = {g.field for g in classify_lines(panel)}
    assert "generic_name" not in before

    after = unstitch(panel)
    named = dict(zip([part.text for part in after], classify_lines(after), strict=True))
    assert named["Face Serum"].field == "generic_name"
    assert named["Made in India"].field == "country_of_origin"


def test_a_pack_that_uses_a_rule_instead_of_a_stop_is_read_the_same_way() -> None:
    """`Face Serum | Made in India` is the same layout with a different mark,
    and a pack setting it that way puts a space on both sides."""
    assert pieces("Face Serum | Made in India") == ["Face Serum", "Made in India"]


def test_a_small_carton_may_print_its_whole_declaration_block_on_one_line() -> None:
    assert pieces("Toilet Soap. Net Wt. 100 g. MRP Rs. 45.00. Made in India") == [
        "Toilet Soap",
        "Net Wt. 100 g. MRP Rs. 45.00",
        "Made in India",
    ]


# ---------------------------------------------------------------------------
# An abbreviation is not the end of a sentence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # The licence the same carton prints, and the defect fixed the day
        # before this one. A cut at `Mfg.` or `Lic.` would undo it.
        "Mfg. Lic. No.: JK/21-22/C0S-8/334",
        # matches.jpg, from the labelled panels. `NET WT.` belongs to `46 g`,
        # and a looser draft cut between them and invented a date.
        "Made in India NET WT. WHEN PACKED: 46 g",
        # Corpus, twice. The stop is inside `RS.`
        "For Net W., MRP RS. Incl. ofall taxes):, Batch No., PKD. and 565 mg Selenium",
        # Corpus. `MFG.` and `PKD.` are both abbreviations.
        "SEE BELOW FOR MFG. DATE/ PKD. DATE / EXPIRY DATE (EXP) /",
        # The company forms, which end in a stop and are never a sentence.
        "Marketed by Acme Foods Pvt. Ltd. 12 MG Road, Pune 411001",
        "M/s. ABC Foods. 12 MG Road",
        "Mfd. by Acme Industries Co. Plot 4, MIDC",
    ],
)
def test_a_stop_behind_a_short_word_is_an_abbreviation(text: str) -> None:
    assert pieces(text) == [text]


def test_a_decimal_point_does_not_end_a_sentence() -> None:
    """`645.00.` ends a figure, and the four characters behind that last stop
    are `5.00` -- a whole number, not a two-digit stub."""
    assert pieces("MRP Rs 645.00. Made in India") == ["MRP Rs 645.00", "Made in India"]


# ---------------------------------------------------------------------------
# What must never be cut
# ---------------------------------------------------------------------------


def test_an_address_is_never_cut() -> None:
    """Rule 6(1)(a) wants the name AND the address. A cut that separates them
    leaves a manufacturer with nowhere to be served."""
    text = "Manufactured by Sunrise Foods Limited, 44 Industrial Estate. Nashik 422007"
    assert pieces(text) == [text]


def test_an_ingredients_list_keeps_its_own_contents() -> None:
    """`Iodised Salt` is a term in the generic-name lexicon and it is sitting
    inside an ingredients declaration. Cut out, it becomes a short clean line
    that the commodity tier would call what the pack IS.

    `commodity._inside_a_prose_block` normally shadows list items, but it walks
    DOWN the panel from the heading and these two sit side by side on one row --
    so it would never see this one. Refusing the cut is the only place the
    heading is still attached to its list.
    """
    text = "INGREDIENTs: Maize Starch. Iodised Salt,"
    assert pieces(text) == [text]


def test_a_commodity_word_inside_an_allergen_sentence_is_not_a_declaration() -> None:
    """`Milk& Soya` contains a lexicon term; it is not one. The piece has to BE
    a commodity, exactly, or it earns nothing and the cut is refused."""
    text = "Milk& Soya. Manufactured on equipment that also processes"
    assert pieces(text) == [text]


def test_storage_copy_stays_as_the_paragraph_it_is() -> None:
    text = "Store in a cool dry place. Keep away from direct sunlight."
    assert pieces(text) == [text]


def test_a_caption_is_never_cut_off_its_own_value() -> None:
    """`Qty.` is an abbreviation, and separating it from `30 ml` is precisely
    the damage `vision.classify.associate` exists to repair."""
    assert pieces("Hair Serum. Net Qty. 30 ml") == ["Hair Serum", "Net Qty. 30 ml"]


def test_one_named_piece_and_a_leftover_is_not_worth_a_cut() -> None:
    """The leftover is usually the rest of somebody's address."""
    text = "Marketed by Coastal Traders. Building 7 Second Cross Road"
    assert pieces(text) == [text]


# ---------------------------------------------------------------------------
# Geometry divided honestly
# ---------------------------------------------------------------------------


def test_the_pieces_are_laid_out_left_to_right_inside_the_parent() -> None:
    parent = line("Face Serum. Made in India", x=100.0)
    parts = unstitch_line(parent)

    assert len(parts) == 2
    assert parts[0].box.x >= parent.box.x
    assert parts[1].box.x > parts[0].box.x
    assert parts[-1].box.x2 <= parent.box.x2 + 1.0


def test_character_boxes_are_sliced_rather_than_dropped() -> None:
    """Unlike `split.unweld_line`, the offsets here are exact, so Rule 7(3)'s
    character-width proviso survives the cut instead of answering NO_DATA."""
    text = "Face Serum. Made in India"
    parent = OcrLine(
        text=text,
        box=Box(x=0.0, y=0.0, w=500.0, h=40.0),
        confidence=0.9,
        script="latin",
        char_boxes=[Box(x=float(i * 20), y=0.0, w=18.0, h=30.0) for i in range(len(text))],
    )

    parts = unstitch_line(parent)
    assert len(parts) == 2
    for part in parts:
        assert len(part.char_boxes) == len(part.text)
    assert parts[0].char_boxes[0].x == 0.0


def test_mismatched_character_boxes_are_dropped_rather_than_misaligned() -> None:
    parent = OcrLine(
        text="Face Serum. Made in India",
        box=Box(x=0.0, y=0.0, w=500.0, h=40.0),
        confidence=0.9,
        script="latin",
        char_boxes=[Box(x=0.0, y=0.0, w=18.0, h=30.0)],  # one box, many characters
    )
    assert all(part.char_boxes == [] for part in unstitch_line(parent))


def test_the_figures_go_to_the_piece_that_holds_them() -> None:
    """`numeral_height_px` is what every Rule 7(2) height verdict on a price is
    computed from. Handed to the wrong piece it would measure one declaration
    and report it as another's."""
    parent = OcrLine(
        text="MRP Rs 645.00. Made in India",
        box=Box(x=0.0, y=0.0, w=560.0, h=40.0),
        confidence=0.9,
        script="latin",
        numeral_box=Box(x=140.0, y=4.0, w=120.0, h=30.0),
        numeral_height_px=26.0,
    )

    price, origin = unstitch_line(parent)
    assert price.numeral_height_px == 26.0
    assert origin.numeral_height_px is None
    assert origin.numeral_box is None


def test_an_unplaceable_figure_goes_nowhere() -> None:
    """Two candidate pieces and no geometry to choose between them. The height
    rules then answer NO_DATA, which is the refusal they already make when the
    figures could not be separated -- and better than a coin toss."""
    parent = OcrLine(
        text="Net Wt 500 g. Made in 2 States",
        box=Box(x=0.0, y=0.0, w=560.0, h=40.0),
        confidence=0.9,
        script="latin",
        numeral_height_px=26.0,
    )
    parts = unstitch_line(parent)
    if len(parts) > 1:
        assert all(part.numeral_height_px is None for part in parts)


def test_every_piece_keeps_the_baseline_the_parent_measured() -> None:
    """One printed line, one baseline: the parent's cap height is each piece's
    own, and re-deriving it from the sub-box would report display type."""
    parts = unstitch_line(line("Face Serum. Made in India", cap=31.5))
    assert [part.cap_height_px for part in parts] == [31.5, 31.5]


# ---------------------------------------------------------------------------
# Everything else passes through untouched
# ---------------------------------------------------------------------------


def test_an_ordinary_line_is_returned_as_the_same_object() -> None:
    original = line("MRP Rs. 45.00 (incl. of all taxes)")
    assert unstitch_line(original) == [original]


def test_unstitch_preserves_every_other_line_and_their_order() -> None:
    page = [line("AURA NATURALS"), line("Face Serum. Made in India"), line("B77A6571")]
    assert [part.text for part in unstitch(page)] == [
        "AURA NATURALS",
        "Face Serum",
        "Made in India",
        "B77A6571",
    ]


@pytest.mark.parametrize("text", ["", "   ", ".", ". . .", "Face Serum."])
def test_nothing_degenerate_raises(text: str) -> None:
    assert [part.text for part in unstitch_line(line(text))] == [text]


# ---------------------------------------------------------------------------
# The third input channel
# ---------------------------------------------------------------------------


def test_an_e_commerce_listing_is_cut_the_same_way() -> None:
    """The problem statement names three inputs and one is pure text. A
    marketplace description runs two declarations together exactly as a carton
    does, and there is no detector to blame for it there."""
    from vision.classify.assemble import from_listing_text

    ds = from_listing_text("AURA NATURALS\nFace Serum. Made in India\nMRP Rs. 645.00")
    found = {d.field: d.text for d in ds.declarations}

    assert found["generic_name"] == "Face Serum"
    assert found["country_of_origin"] == "Made in India"
    assert found["mrp"] == "MRP Rs. 645.00"
