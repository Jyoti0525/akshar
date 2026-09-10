"""A label and its figure, read as two regions, must become one declaration.

The geometry in these fixtures is taken from `bodywash_bottle_300ml/tilt.jpg`,
where the pipeline read `449.00` at confidence 0.97 and reported the pack as
declaring no retail sale price, because the word beside it was a separate
region. Every number below — the 98 px gap, the 24 px label against the 42 px
figure — is off that photograph.

The failure mode on the other side is a fabricated declaration, so it is tested
harder than the one being fixed: a bare number is a batch code far more often
than it is a price, and joining one to a distant label would invent a price the
pack never declared.
"""

from __future__ import annotations

from vision.classify.assemble import from_lines
from vision.classify.associate import associate
from vision.classify.regex_tier import classify_line
from vision.types import Box, OcrLine, ScaleEstimate


def _line(
    text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    confidence: float = 0.95,
    k: int = 0,
    cap: float | None = None,
    numeral_height: float | None = None,
) -> OcrLine:
    return OcrLine(
        text=text,
        box=Box(x=x, y=y, w=w, h=h, panel_id="pdp"),
        confidence=confidence,
        script="latin",
        panel_id="pdp",
        cap_height_px=cap,
        numeral_height_px=numeral_height,
        rotation_k=k,
    )


def _guesses(lines: list[OcrLine]):
    return [classify_line(line) for line in lines]


def _pairs(lines: list[OcrLine]):
    return associate(lines, _guesses(lines))


# -- the case this exists for ----------------------------------------------


def test_a_price_beside_its_label_becomes_one_declaration():
    lines = [
        _line("MRP Rs.", 2171, 1591, 100, 24),
        _line("449.00", 2297, 1597, 145, 42),
    ]
    found = _pairs(lines)
    assert len(found) == 1
    assert (found[0].label, found[0].value, found[0].field) == (0, 1, "mrp")


def test_a_quantity_beside_its_label_is_the_same_problem():
    """Not an MRP fix. Every numeric declaration splits the same way."""
    lines = [
        _line("Net Wt.", 100, 100, 90, 22),
        _line("500 g", 210, 102, 70, 22),
    ]
    found = _pairs(lines)
    assert len(found) == 1
    assert found[0].field == "net_quantity"


def test_a_figure_set_under_its_label_is_caught_too():
    lines = [
        _line("MRP", 100, 100, 60, 24),
        _line("449.00", 100, 130, 90, 26),
    ]
    assert len(_pairs(lines)) == 1


# -- and the things it must not do -----------------------------------------


def test_a_label_that_already_carries_its_figure_is_left_alone():
    lines = [
        _line("MRP Rs. 449.00", 2171, 1591, 250, 30),
        _line("100004", 2600, 1591, 120, 30),
    ]
    assert _pairs(lines) == []


def test_a_number_across_the_pack_is_not_a_price():
    """The gap is the whole claim. Without it this joins anything to anything."""
    lines = [
        _line("MRP Rs.", 100, 100, 90, 24),
        _line("449.00", 900, 100, 145, 42),
    ]
    assert _pairs(lines) == []


def test_a_number_on_another_line_is_not_a_price():
    lines = [
        _line("MRP Rs.", 100, 100, 90, 24),
        _line("449.00", 100, 400, 145, 42),
    ]
    assert _pairs(lines) == []


def test_a_figure_that_declared_its_own_field_is_never_taken():
    """`Net Wt. 500 g` beside an MRP label stays the net quantity."""
    lines = [
        _line("MRP Rs.", 100, 100, 90, 24),
        _line("Net Wt. 500 g", 210, 100, 160, 24),
    ]
    assert _pairs(lines) == []


def test_text_running_the_other_way_is_not_beside_anything():
    """A figure printed down the side of a pack does not belong to a label
    printed across it, however close the two boxes happen to fall."""
    lines = [
        _line("MRP Rs.", 100, 100, 90, 24),
        _line("449.00", 210, 100, 42, 145, k=1),
    ]
    assert _pairs(lines) == []


def test_one_figure_serves_one_label():
    lines = [
        _line("MRP Rs.", 100, 100, 90, 24),
        _line("MRP Rs.", 100, 160, 90, 24),
        _line("449.00", 210, 100, 90, 24),
    ]
    found = _pairs(lines)
    assert len(found) == 1
    assert found[0].label == 0


# -- what the rules engine is handed ---------------------------------------


def _set(lines: list[OcrLine]):
    return from_lines(lines, ScaleEstimate(mm_per_px=0.1, tolerance=0.002, tier="A", method="aruco"))


def test_the_declaration_reads_as_the_whole_thing():
    """The rulepack's format patterns must see the label and the figure.

    `LMPC.MRP.FORMAT` looks for a currency marker. Emitting `449.00` alone
    would locate the declaration and then fail its format — a violation caused
    entirely by our own detector splitting the line.
    """
    lines = [
        _line("MRP Rs.", 2171, 1591, 100, 24),
        _line("449.00", 2297, 1597, 145, 42),
    ]
    mrp = [d for d in _set(lines).declarations if d.field == "mrp"]
    assert len(mrp) == 1
    assert mrp[0].text == "MRP Rs. 449.00"


def test_the_label_stops_claiming_the_field():
    """Otherwise the pack now declares its MRP twice and duplicate detection
    fires against a compliant label for a split we introduced."""
    lines = [
        _line("MRP Rs.", 2171, 1591, 100, 24),
        _line("449.00", 2297, 1597, 145, 42),
    ]
    assert [d.field for d in _set(lines).declarations].count("mrp") == 1


def test_the_measurement_comes_from_the_figure_and_not_from_the_union():
    """The union box spans the label, the gap and the figure — 243 px wide for
    a 42 px line. Rule 9 measures the numerals."""
    lines = [
        _line("MRP Rs.", 2199, 1591, 100, 24, cap=18.0, numeral_height=None),
        _line("449.00", 2297, 1597, 145, 42, cap=24.8, numeral_height=19.0),
    ]
    mrp = next(d for d in _set(lines).declarations if d.field == "mrp")
    assert mrp.height_for_rules_px == 19.0
    assert mrp.height_mm is not None
    assert mrp.height_mm == 19.0 * 0.1


def test_an_associated_declaration_is_less_confident_than_a_plain_one():
    joined = _set([
        _line("MRP Rs.", 2171, 1591, 100, 24),
        _line("449.00", 2297, 1597, 145, 42),
    ])
    plain = _set([_line("MRP Rs. 449.00", 2171, 1591, 250, 30)])
    a = next(d for d in joined.declarations if d.field == "mrp")
    b = next(d for d in plain.declarations if d.field == "mrp")
    assert a.field_confidence < b.field_confidence


def test_character_boxes_are_dropped_rather_than_misaligned():
    """`min_width_ratio` zips `text` against `char_boxes` positionally. Boxes
    for half the string would compare every character against the wrong glyph,
    so the whole list goes and Rule 7(3) returns NO_DATA."""
    lines = [
        _line("MRP Rs.", 2171, 1591, 100, 24),
        _line("449.00", 2297, 1597, 145, 42),
    ]
    lines[1] = OcrLine(
        text=lines[1].text,
        box=lines[1].box,
        confidence=lines[1].confidence,
        script="latin",
        char_boxes=[Box(x=2297 + 20 * i, y=1597, w=18, h=19) for i in range(6)],
        panel_id="pdp",
    )
    mrp = next(d for d in _set(lines).declarations if d.field == "mrp")
    assert mrp.char_boxes == []


def test_character_boxes_survive_when_both_halves_were_segmented():
    label = OcrLine(
        text="MRP",
        box=Box(x=100, y=100, w=60, h=24, panel_id="pdp"),
        confidence=0.9,
        script="latin",
        char_boxes=[Box(x=100 + 20 * i, y=100, w=18, h=22) for i in range(3)],
        panel_id="pdp",
    )
    value = OcrLine(
        text="449.00",
        box=Box(x=200, y=100, w=120, h=24, panel_id="pdp"),
        confidence=0.9,
        script="latin",
        char_boxes=[Box(x=200 + 20 * i, y=100, w=18, h=22) for i in range(6)],
        panel_id="pdp",
    )
    mrp = next(d for d in _set([label, value]).declarations if d.field == "mrp")
    assert mrp.text == "MRP 449.00"
    assert len(mrp.char_boxes) == len(mrp.text)
