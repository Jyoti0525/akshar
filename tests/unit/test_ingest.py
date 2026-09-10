"""The page-classification half of `scripts/ingest_gazettes.py`.

Only the decisions are tested here, not the recogniser. What a page *says* comes
from RapidOCR and cannot be asserted; what the corpus *keeps* is ours, and it is
the part that silently loses statute when it is wrong.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from ingest_gazettes import (
    BLOCK_DISTINCT_ENGLISH,
    GAP_MIN_WORDS,
    GAP_SIMILARITY,
    GAP_SIMILARITY_REACH,
    _already_read,
    _fold,
    _pitch_bands,
    english_block,
    ideographs,
    repair_flipped,
)

# Devanagari comes back from PP-OCR as CJK glyphs, never as Devanagari
# codepoints. Tests use the glyphs the recogniser actually emits.
HINDI = "可T. 3. 825(3).AaT (fa8 Hg fAsT)"


@pytest.fixture
def vocabulary() -> frozenset[str]:
    return frozenset(
        {
            "particulars", "laboratory", "field", "use", "equipment",
            "application", "made", "weight", "measure", "which", "for",
            "part", "sec", "the", "gazette", "india", "extraordinary",
            "max", "kpa",
        }
    )


def test_the_english_block_of_a_bilingual_page_is_kept(vocabulary):
    """`model_test_labs_2014` p. 6: an English table header over a Hindi body.

    The header is the only place in the corpus these column names appear, and
    the page as a whole fails the ideograph test on the body below it.
    """
    page = "\n".join(
        [
            "[PART II-SEC. 3(ii)]",
            "PARTICULARS OF LABORATORY",
            "Model of Weight or Measure for which",
            "Field of use",
            "Equipment",
            "application is made",
            HINDI,
            "2011" + HINDI,
        ]
    )
    block = english_block(page, vocabulary)

    assert block is not None
    assert "PARTICULARS OF LABORATORY" in block
    assert "Field of use" in block
    assert "Equipment" in block
    # The Hindi body is left where it was.
    assert ideographs(block) == 0


def test_a_block_scoring_on_one_repeated_word_is_rejected(vocabulary):
    """`general_rules_2011` p. 150 reaches eight English words on four `max`.

    This is why the threshold counts *distinct* words. A formula table repeating
    one unit name is not English prose, and admitting it puts noise under a
    citation.
    """
    page = "\n".join(
        [
            "3(d) 3x(1) f max",
            "[se/mpse(1)] max",
            "[md/mpd(1)] max",
            "3 (x)> [md/mpd(1)] max",
            HINDI,
        ]
    )

    assert english_block(page, vocabulary) is None


def test_unit_symbols_standing_in_hindi_are_rejected(vocabulary):
    """`general_rules_2011` p. 268: `kPa` and `mm Hg` inside Hindi sentences."""
    page = "\n".join(
        [
            "0.3 kPa/8  0.4 kPa/8 (2mm Hg/s",
            "a0.3KPa/A",
            "kPa 2 kPa (260 mm Hlg 15mm Hg)",
            "Ilnle hy",
            HINDI,
        ]
    )

    assert english_block(page, vocabulary) is None


def test_blocks_are_not_stitched_across_the_hindi_between_them(vocabulary):
    """Two English runs separated by Hindi are two runs, not one.

    Joining them would put text next to text it is not next to on the page,
    which is the one thing a corpus read for quotation must not do.
    """
    good = [
        "PARTICULARS OF LABORATORY",
        "Model of Weight or Measure for which",
        "Field of use",
        "Equipment",
        "application is made",
    ]
    page = "\n".join([*good, HINDI, "Equipment", "Field of use"])

    block = english_block(page, vocabulary)

    assert block is not None
    assert block == "\n".join(good)


def test_a_page_with_no_english_block_returns_none(vocabulary):
    page = "\n".join([HINDI, "(3)", "(2)", "1.", HINDI])

    assert english_block(page, vocabulary) is None


def test_the_threshold_is_a_count_of_distinct_words(vocabulary):
    """Guards the constant itself: a block one word short must not qualify."""
    words = ["particulars", "laboratory", "field", "use", "equipment",
             "application", "made", "weight", "measure"]
    short = " ".join(words[: BLOCK_DISTINCT_ENGLISH - 1])
    enough = " ".join(words[:BLOCK_DISTINCT_ENGLISH])

    assert english_block(f"{short}\n{HINDI}", vocabulary) is None
    assert english_block(f"{enough}\n{HINDI}", vocabulary) is not None


# --------------------------------------------------------------------------
# recovering lines the recogniser lost
# --------------------------------------------------------------------------


def _box(top: int, bottom: int, left: int = 0, right: int = 900) -> list[list[int]]:
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


def test_a_skipped_beat_in_the_line_pitch_is_found():
    """One dropped line among evenly spaced ones, on real page-19 geometry.

    Tops 1813, 1873, 1934, 2054, 2114 -- a 60px pitch with one step of 120.
    """
    boxes = [_box(top, top + 138) for top in (1813, 1873, 1934, 2054, 2114)]

    bands = _pitch_bands(boxes)

    assert len(bands) == 1
    top, bottom, pitch = bands[0]
    assert 55 <= pitch <= 65
    # The band has to contain where the lost line sat, about 1994.
    assert top < 1994 < bottom


def test_evenly_spaced_lines_open_no_band():
    """The common case must cost nothing: no gap, no recognition pass."""
    boxes = [_box(top, top + 138) for top in (100, 160, 220, 280, 340, 400)]

    assert _pitch_bands(boxes) == []


def test_a_paragraph_sized_hole_is_left_alone():
    """A detector loses a line, not a page -- see GAP_MAX_LINES."""
    boxes = [_box(top, top + 40) for top in (100, 160, 220, 2000, 2060, 2120)]

    assert all(bottom - top < 600 for top, bottom, _ in _pitch_bands(boxes))


def test_identical_wording_elsewhere_on_the_page_is_not_a_duplicate():
    """Page 319 of the General Rules prints rules 7, 8 and 9 in identical words.

    `(2) The number, types and specifications of such` is the text of three
    different sub-rules. A text-only guard rejected the recovery of rule 8(2) as
    a duplicate of rule 7(2), and nothing could bring it back.
    """
    line = _fold("(2) The number, types and specifications of such")
    seen = [(line, 400.0)]          # rule 7(2), twelve lines higher up

    assert _already_read(line, 1000.0, seen, 47.0) is False


def test_the_same_line_read_twice_is_a_duplicate():
    """The guard still has to do its original job."""
    line = _fold("(2) The number, types and specifications of such")
    seen = [(line, 1000.0)]

    assert _already_read(line, 1010.0, seen, 47.0) is True


def test_two_readings_of_one_line_are_recognised_as_one():
    """`speciffied ... Eourth` and `specified ... Fourth`, same line of print."""
    held = _fold("balances shall be as are specified in Part Ii of Fourth")
    reread = _fold("balances shall be as are speciffied in Part Il of Eourth")

    assert _already_read(reread, 1000.0, [(held, 1000.0)], 47.0) is True


@pytest.mark.parametrize(
    ("garbled", "held"),
    [
        ("fal The slrfare of the weiahts shall be", "(a) The surface of the weights shall be"),
        ("For better stablity and finist, the weiahts", "(b) For better stability and finish, the weights"),
        ("(b) The weiahts shall be suppliec in a suitable", "(b) The weights shall be supplied in a suitable"),
        ("may remain vicible far aat mata", "may remain visible for not more than"),
        ("fecordiro_the data_ahave_and", "recording the data above and"),
        ("Comprisina a bladdar ard s ctooue", "comprising a bladder and a sleeve, which is wrapped"),
    ],
)
def test_a_garbled_second_reading_is_still_a_duplicate(garbled, held):
    """The failure that `GAP_SIMILARITY` exists for.

    These six pairs are measured, not invented: each is a line the pitch
    detector re-read out of a band it should not have opened on pages 350 to
    600 of the General Rules, against the clean reading the page already held.
    A garbled reading shares no long *contiguous* run with its twin -- the
    first pair shares ten characters where `GAP_OVERLAP` demands sixteen -- so
    the longest-run test admitted every one of them and the corpus kept both
    copies.
    """
    assert _already_read(_fold(garbled), 1000.0, [(_fold(held), 1000.0)], 47.0) is True


def test_genuinely_new_text_survives_the_similarity_test():
    """Sub-rule (2) of *Permitted unit of mass*, page 70 of the National
    Standards rules, which no reading before the pitch detector had ever seen.

    It has to clear both neighbours it lands between, and it is the reason
    `GAP_SIMILARITY` is not set any higher: it scores 0.37 against them.
    """
    recovered = _fold('(2)Only the prefixes "kilo","mega yiga and "tera" specified in the')
    neighbours = [
        (_fold("tonne.(Symbol:t). The tonne shall be equal to 10o0 kilograms"), 980.0),
        (_fold("Third Schedulemaybeusedwith the tonne."), 1020.0),
    ]

    assert _already_read(recovered, 1000.0, neighbours, 47.0) is False


def test_the_parallel_provision_survives_the_similarity_test_too():
    """`GAP_SIMILARITY` must not undo the positional guard.

    Rule 8(2) on page 319 is word-for-word rule 7(2), so it scores 1.0 against
    it. Only the distance between them keeps it in the corpus.
    """
    line = _fold("(2) The number, types and specifications of such")

    assert _already_read(line, 1000.0, [(line, 400.0)], 47.0) is False


def test_a_confident_page_is_returned_untouched():
    """`repair_flipped` must not re-read a page with nothing doubtful on it.

    The recogniser is never called: the fixture raises if it is.
    """

    def never(*args, **kwargs):
        raise AssertionError("the page was re-read despite reading confidently")

    result = [(_box(10, 50), "A set of secondary standard balances shall", 0.99)]

    assert repair_flipped(object(), result, never) is result


@pytest.mark.parametrize(
    ("recovered", "neighbour"),
    [
        (
            "10. Re-submission of-disapproved model for approval. - (1) Whereanv modol i.",
            "not approved, the disapproved model may be re-submitted for approval after carrying",
        ),
        (
            "(j) physical constants means those constants which express the value of",
            "physical invariant in a given system of units and these constants include;",
        ),
    ],
)
def test_a_line_a_pitch_away_is_not_a_duplicate_however_alike(recovered, neighbour):
    """The regression `GAP_SIMILARITY_REACH` exists for.

    Both of these are lines the sweep correctly recovered and a bare likeness
    test then deleted: the heading of rule 10 of the Approval of Models Rules,
    and the National Standards definition of *physical constants*. They score
    0.52 and 0.56 against the line below them -- above two of the nine garbled
    duplicates -- because consecutive lines of a statute repeat its words.

    What separates them is where they sit. A second reading of one line of
    print lands on top of the first; these sit a full line pitch below their
    neighbour, so likeness is not allowed to convict them.
    """
    assert (
        _already_read(_fold(recovered), 1000.0, [(_fold(neighbour), 1047.0)], 47.0)
        is False
    )


def test_the_same_print_read_twice_is_still_caught_at_that_distance():
    """And the guard must not have simply switched the test off."""
    garbled = _fold("fal The slrfare of the weiahts shall be")
    held = _fold("(a) The surface of the weights shall be")

    assert _already_read(garbled, 1000.0, [(held, 1004.0)], 47.0) is True


def test_gap_similarity_reach_is_under_a_line():
    """Above one line height it would reach the neighbour it must not judge."""
    assert 0 < GAP_SIMILARITY_REACH < 1.0


def test_gap_similarity_sits_between_the_two_measured_populations():
    """0.37 was the lowest genuine recovery, 0.54 the highest garbled duplicate."""
    assert 0.37 < GAP_SIMILARITY < 0.54


def test_gap_min_words_is_at_least_two():
    """Guards the constant: single-word fragments are what it exists to drop."""
    assert GAP_MIN_WORDS >= 2
