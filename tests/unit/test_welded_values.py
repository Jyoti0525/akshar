"""A coded strip printed as columns — `vision/ocr/split.py` and its two fallout.

`udadpapad.jpg` sets three declarations as a two-row table:

    PACKED ON      USE BY       BATCH NO.
    09-08-2023     08-11-2023   M-09

The detector returns the value row as one region and the recogniser, which
emits a space for a word gap and nothing for a column gap, reads it as
`'09-08-202308-11-2023M-09'`. Three declarations, one unmatchable string.

Fixing that surfaced two bugs that had been invisible while such dates arrived
welded, and each has its own section below.
"""

from __future__ import annotations

import pytest

from vision.classify import regex_tier, shapes
from vision.classify.associate import associate
from vision.ocr.split import unweld, unweld_line
from vision.types import Box, OcrLine


def _line(text: str, x=192.0, y=207.0, w=432.0, h=38.0, cap=21.0) -> OcrLine:
    return OcrLine(
        text=text,
        box=Box(x=x, y=y, w=w, h=h),
        confidence=0.9,
        script="latin",
        cap_height_px=cap,
    )


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------


def test_the_udadpapad_value_row_becomes_its_three_cells() -> None:
    parts = unweld_line(_line("09-08-202308-11-2023M-09"))

    assert [p.text for p in parts] == ["09-08-2023", "08-11-2023", "M-09"]


def test_the_goodday_coded_strip_becomes_its_three_cells() -> None:
    parts = unweld_line(_line("19/06/2218/12/22B062207"))

    assert [p.text for p in parts] == ["19/06/22", "18/12/22", "B062207"]


def test_the_fragments_are_laid_out_left_to_right_across_the_parent() -> None:
    """Position is the whole point: it is what decides which label a cell sits
    under. Proportional is an approximation, but it must at least be ordered
    and must stay inside the region the recogniser reported."""
    parent = _line("09-08-202308-11-2023M-09")
    parts = unweld_line(parent)

    assert [round(p.box.x) for p in parts] == sorted(round(p.box.x) for p in parts)
    assert parts[0].box.x >= parent.box.x
    assert parts[-1].box.x + parts[-1].box.w <= parent.box.x + parent.box.w + 1


def test_a_fragment_keeps_the_rows_measured_cap_height() -> None:
    """One baseline was measured for the row and every cell sits on it."""
    parts = unweld_line(_line("09-08-202308-11-2023M-09", cap=21.0))

    assert all(p.cap_height_px == 21.0 for p in parts)


def test_character_geometry_is_dropped_rather_than_misattributed() -> None:
    """`char_boxes` describes the parent's characters at the parent's offsets.
    Carrying it onto a cell would hand `min_width_ratio` boxes belonging to a
    different piece of text; NO_DATA is the honest answer."""
    parent = _line("09-08-202308-11-2023M-09")
    parent = OcrLine(
        text=parent.text,
        box=parent.box,
        confidence=parent.confidence,
        script=parent.script,
        cap_height_px=parent.cap_height_px,
        char_boxes=[Box(x=float(i), y=0.0, w=1.0, h=10.0) for i in range(24)],
    )

    assert all(p.char_boxes == [] for p in unweld_line(parent))


@pytest.mark.parametrize(
    "text",
    [
        "09-08-2023 08-11-2023 M-09",  # spaced: the recogniser saw the gaps
        "MRP 140.00",  # an ordinary label and value
        "Percent daily values are based on a 2000 calorie diet",
        "INGREDIENTS : Udad-dal Flour,",
        "MK08D2451",  # one batch code, not two of anything
        "200 g",
        "Net Weight: 500 g",
        "",
    ],
)
def test_anything_that_is_not_a_row_of_cells_is_left_exactly_as_read(text: str) -> None:
    """Splitting invents a boundary the recogniser never reported, so the bar
    is every character accounted for by a value shape."""
    assert [p.text for p in unweld_line(_line(text))] == [text]


def test_unweld_preserves_every_other_line() -> None:
    lines = [_line("BATCH NO."), _line("09-08-202308-11-2023M-09"), _line("Net Weight")]

    assert [p.text for p in unweld(lines)] == [
        "BATCH NO.",
        "09-08-2023",
        "08-11-2023",
        "M-09",
        "Net Weight",
    ]


# ---------------------------------------------------------------------------
# A date is not a barcode
# ---------------------------------------------------------------------------


def test_a_printed_date_is_never_classified_as_a_barcode() -> None:
    """`_BARCODE_NOISE` strips hyphens, so `09-08-2023` becomes `09082023` --
    eight digits, the length of an EAN-8. Every `DD-MM-YYYY` on every pack was
    named `barcode` here, and `associate` only offers `other` lines as values,
    so such a date could never reach the declaration it belonged to."""
    assert regex_tier.classify_line(_line("09-08-2023")).field != "barcode"
    assert regex_tier.classify_line(_line("08-11-2023")).field != "barcode"


def test_a_real_barcode_is_still_a_barcode() -> None:
    assert regex_tier.classify_line(_line("8901537024014")).field == "barcode"
    assert regex_tier.classify_line(_line("09082023")).field == "barcode"


def test_a_date_inside_a_longer_string_does_not_excuse_it() -> None:
    """`is_date` is whole-string on purpose: a date appearing inside other text
    says nothing about what that text is."""
    assert not shapes.is_date("MFD 09-08-2023 LOT 4471")
    assert shapes.is_date("09-08-2023")


# ---------------------------------------------------------------------------
# An expiry is after a manufacture date
# ---------------------------------------------------------------------------


def _column(labels: list[tuple[str, float]], values: list[tuple[str, float]]):
    lines, guesses = [], []
    for text, x in labels:
        lines.append(_line(text, x=x, y=165.0, w=100.0, h=20.0, cap=14.0))
    for text, x in values:
        lines.append(_line(text, x=x, y=207.0, w=100.0, h=20.0, cap=14.0))
    for line in lines:
        guesses.append(regex_tier.classify_line(line))
    return lines, guesses


def test_two_dates_that_come_back_in_the_wrong_order_are_exchanged() -> None:
    """goodday.jpg. `PKD.` took `18/12/22` and `USE BY` took `19/06/22`, so the
    officer was shown a pack that expired six months before it was made.
    Chronology is the one fact distance does not have."""
    lines, guesses = _column(
        [("PKD.", 200.0), ("USE BY", 400.0)],
        [("18/12/22", 400.0), ("19/06/22", 200.0)],
    )
    found = {a.field: lines[a.value].text for a in associate(lines, guesses)}

    assert found.keys() >= {"mfg_date", "expiry_date"}, "nothing was paired; test is vacuous"
    assert found["mfg_date"] == "19/06/22"
    assert found["expiry_date"] == "18/12/22"


def test_dates_already_in_order_are_left_alone() -> None:
    lines, guesses = _column(
        [("PKD.", 200.0), ("USE BY", 400.0)],
        [("19/06/22", 200.0), ("18/12/22", 400.0)],
    )
    found = {a.field: lines[a.value].text for a in associate(lines, guesses)}

    assert found.keys() >= {"mfg_date", "expiry_date"}, "nothing was paired; test is vacuous"
    assert found["mfg_date"] == "19/06/22"
    assert found["expiry_date"] == "18/12/22"


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("19/06/22", (2022, 6, 19)),
        ("18/12/22", (2022, 12, 18)),
        ("07/20", (2020, 7, 0)),
        ("JAN.2025", (2025, 1, 0)),
        ("23/SEP/2025", (2025, 9, 23)),
    ],
)
def test_the_date_key_orders_the_forms_packs_actually_print(text, key) -> None:
    from vision.classify.associate import _date_key

    assert _date_key(text) == key


def test_a_fragment_that_cannot_be_ordered_returns_nothing_rather_than_a_guess() -> None:
    from vision.classify.associate import _date_key

    assert _date_key("B062207") is None
    assert _date_key("") is None
