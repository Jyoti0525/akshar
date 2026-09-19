"""The label reader tier. `vision/vlm/`.

Measured on 2026-09-19 against the hand labels in `data/declaration_blocks/`:
the reader 17/17 across three packs, the OCR path 1/17 with three values
confidently wrong. The honey jar is the case that matters and it has a test of
its own below, because the failure there was not a miss -- it was the net weight
reported as the maximum retail price.

Everything here runs against a fake reader. No test in this repository may open
a network connection, and a tier whose correctness depends on a live model is a
tier nobody can regression-test.
"""

from __future__ import annotations

import json

import pytest

from contracts.declarations import Box
from vision import vlm
from vision.classify import assemble
from vision.types import OcrLine, ScaleEstimate


@pytest.fixture(autouse=True)
def _no_reader_left_installed():
    """`install` is process-global. A test that leaves one behind would change
    the behaviour of every test that runs after it."""
    yield
    vlm.install(None)


class FakeReader:
    def __init__(self, reply: str, *, name: str = "fake-reader-2026-09-19"):
        self.reply = reply
        self.name = name
        self.calls = 0

    def read(self, image: bytes, *, prompt: str, media_type: str = "image/jpeg") -> str:
        self.calls += 1
        return self.reply


def _reply(*rows: dict) -> str:
    return json.dumps({"declarations": list(rows)})


def _line(text: str, x: float, y: float, w: float = 200.0, h: float = 30.0) -> OcrLine:
    return OcrLine(text=text, box=Box(x=x, y=y, w=w, h=h), confidence=0.8, script="latin")


# ---------------------------------------------------------------------------
# The wall
# ---------------------------------------------------------------------------


def test_no_reader_installed_is_the_default_and_is_not_an_error():
    assert vlm.installed() is None
    ready = vlm.availability()
    assert not ready.ready
    assert "no vision reader" in ready.detail


def test_a_reader_that_will_not_name_itself_is_refused():
    """The name goes into `scans.model_versions`. A declaration whose origin
    cannot be named has no business in a legal record, so an anonymous reader
    is treated as absent rather than used and left unrecorded."""
    vlm.install(FakeReader(_reply(), name=""))

    assert not vlm.availability().ready
    assert "does not name itself" in vlm.availability().detail


def test_every_transport_failure_is_the_same_outcome_as_no_reader():
    """A timeout, a rate limit and an expired key must not fail a scan. The
    OCR path answers and the officer never learns there was a second tier."""

    class Broken:
        name = "broken"

        def read(self, image, *, prompt, media_type="image/jpeg"):
            raise TimeoutError("gateway")

    vlm.install(Broken())
    assert vlm.provider.read(b"x", prompt="p") is None


def test_an_empty_reply_is_not_a_reading():
    vlm.install(FakeReader("   "))
    assert vlm.provider.read(b"x", prompt="p") is None


# ---------------------------------------------------------------------------
# The reply is untrusted input
# ---------------------------------------------------------------------------


def test_a_field_name_that_is_not_in_the_vocabulary_is_dropped_not_mapped():
    """`"price"` is not coerced to `mrp`. A mapping table is a place for the
    next wrong guess to hide."""
    readings = vlm.parse(_reply({"field": "price", "text": "335.00", "box": [0, 0, 1, 1]}))
    assert readings == []


def test_a_reading_with_no_box_is_dropped():
    assert vlm.parse(_reply({"field": "mrp", "text": "335.00"})) == []


def test_a_box_outside_the_image_is_dropped():
    out = _reply({"field": "mrp", "text": "335.00", "box": [0.1, 0.1, 1.4, 0.3]})
    assert vlm.parse(out) == []


def test_corners_in_either_order_are_accepted():
    """Normalising a rectangle is a formatting fix, not a guess about content."""
    readings = vlm.parse(_reply({"field": "mrp", "text": "x", "box": [0.8, 0.6, 0.2, 0.1]}))
    assert readings[0].box == (0.2, 0.1, 0.8, 0.6)


def test_a_zero_area_box_is_dropped():
    assert vlm.parse(_reply({"field": "mrp", "text": "x", "box": [0.3, 0.3, 0.3, 0.5]})) == []


def test_prose_and_code_fences_around_the_json_do_not_lose_the_read():
    body = _reply({"field": "mrp", "text": "335.00", "box": [0.1, 0.1, 0.3, 0.2]})
    for wrapped in (f"Here you go:\n```json\n{body}\n```", f"Sure.\n{body}", f"```\n{body}\n```"):
        assert len(vlm.parse(wrapped)) == 1, wrapped


def test_junk_is_an_empty_list_and_never_an_exception():
    for reply in ("", "not json", "[]", '{"declarations": "mrp"}', '{"other": []}'):
        assert vlm.parse(reply) == []


# ---------------------------------------------------------------------------
# Fluency cannot manufacture ink
# ---------------------------------------------------------------------------


def test_a_reading_with_no_detected_text_under_it_is_dropped_and_counted():
    """The safety property the whole package rests on.

    `contracts.Declaration` requires a box. A model that invents a price for a
    pack that has none produces a reading with nowhere to land, and it cannot
    enter the record -- not by policy, but because there is no rectangle to
    give it. The count is kept, because a silent drop is the failure this is
    guarding against.
    """
    lines = [_line("SOMETHING ELSE", 10, 10)]
    invented = vlm.Reading(field="mrp", text="MRP Rs. 999.00", box=(0.7, 0.8, 0.9, 0.9))

    applied = vlm.apply(lines, [invented], width=400, height=400)

    assert applied.matched == 0
    assert applied.unplaced == 1
    assert applied.fields == {}
    assert applied.lines[0].text == "SOMETHING ELSE", "the line must not be rewritten"
    assert "no text region under them" in applied.note


def test_one_detected_region_cannot_become_two_declarations():
    lines = [_line("335.00", 100, 100)]
    both = [
        vlm.Reading(field="mrp", text="335.00", box=(0.2, 0.2, 0.8, 0.4)),
        vlm.Reading(field="net_quantity", text="335.00", box=(0.2, 0.2, 0.8, 0.4)),
    ]

    applied = vlm.apply(lines, both, width=500, height=500)

    assert applied.matched == 1
    assert applied.unplaced == 1


def test_geometry_is_never_taken_from_the_model():
    """Only the words change. Every millimetre in the record still comes from
    the detector's box and the scale."""
    line = _line("gibberish", 100, 200, w=180, h=24)
    reading = vlm.Reading(field="mrp", text="MRP Rs. 335.00", box=(0.0, 0.0, 1.0, 1.0))

    applied = vlm.apply([line], [reading], width=1000, height=1000)
    rewritten = applied.lines[0]

    assert rewritten.text == "MRP Rs. 335.00"
    assert rewritten.box == line.box, "the model's rectangle reached the record"


def test_agreement_with_the_recogniser_is_reported_rather_than_assumed():
    """Where OCR read something, the two are compared and the number is kept.
    Where OCR read nothing legible there is nothing to corroborate against, and
    that is a real limitation rather than one to average away."""
    corroborated = vlm.apply(
        [_line("MRP Rs 335.00", 10, 10)],
        [vlm.Reading(field="mrp", text="MRP Rs. 335.00", box=(0.0, 0.0, 1.0, 1.0))],
        width=300,
        height=300,
    )
    alone = vlm.apply(
        [_line("PONDIA", 10, 10)],
        [vlm.Reading(field="mrp", text="MRP Rs. 335.00", box=(0.0, 0.0, 1.0, 1.0))],
        width=300,
        height=300,
    )

    assert corroborated.corroborated == 1
    assert alone.corroborated == 0
    assert alone.matched == 1, "an uncorroborated reading is still placed, and said to be"


# ---------------------------------------------------------------------------
# The honey jar
# ---------------------------------------------------------------------------

HONEY_LINES = [
    # What the recogniser actually produced on 2026-09-19. The net weight and
    # the price label were merged into one region; the price itself was read
    # correctly and classified as unremarkable text.
    _line("MRP NRS. 500", 60, 1090, w=600, h=90),
    _line("335.00", 740, 1060, w=350, h=80),
    _line("Lot No. NB00246", 60, 1170, w=520, h=60),
]


def test_the_regex_tier_calls_the_net_weight_a_price():
    """The bug, pinned. If this ever starts passing on its own, the reader tier
    has stopped being the thing that fixes it and this file should say so."""
    guesses = assemble.classify_lines(HONEY_LINES)
    assert guesses[0].field == "mrp"
    assert "500" in HONEY_LINES[0].text


def test_the_reader_corrects_a_confidently_wrong_price():
    """`model_tier_predictions` could not do this: it only fills lines regex
    left as `other`, and regex was not undecided here. It was wrong."""
    readings = [
        vlm.Reading(field="net_quantity", text="Net Weight: 500 g", box=(0.05, 0.85, 0.55, 0.93)),
        vlm.Reading(field="mrp", text="MRP NRs. 335.00", box=(0.60, 0.83, 0.92, 0.90)),
    ]
    applied = vlm.apply(HONEY_LINES, readings, width=1200, height=1280)
    guesses = assemble.classify_lines(applied.lines, reader_fields=applied.fields)

    by_field = {guess.field: line.text for guess, line in zip(guesses, applied.lines, strict=True)}

    assert "335.00" in by_field["mrp"], f"the price is still wrong: {by_field}"
    assert "500 g" in by_field["net_quantity"]


def test_the_reader_reaches_the_declaration_set_with_the_geometry_intact():
    readings = [vlm.Reading(field="mrp", text="MRP NRs. 335.00", box=(0.60, 0.80, 0.95, 0.90))]
    applied = vlm.apply(HONEY_LINES, readings, width=1200, height=1280)

    result = assemble.from_lines(
        applied.lines,
        ScaleEstimate(tier="A", mm_per_px=0.1, tolerance=0.01, method="operator_height"),
        reader_fields=applied.fields,
    )
    mrp = result.first("mrp")

    assert mrp is not None
    assert "335.00" in mrp.text
    assert mrp.box.x == pytest.approx(740.0), "geometry came from the detector, not the model"


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------


def test_the_prompt_lists_exactly_the_contract_vocabulary():
    """A prompt offering a name `contracts` does not define produces readings
    that are silently dropped, which looks like a model that cannot read."""
    import typing

    from contracts import FieldName

    assert set(vlm.prompt.FIELDS) == set(typing.get_args(FieldName))
    built = vlm.build()
    for name in vlm.prompt.FIELDS:
        assert name in built, name


def test_the_prompt_forbids_guessing_a_value_from_the_brand():
    built = vlm.build()
    assert "Never guess" in built
    assert "not estimated" in built


def test_the_prompt_asks_for_columns_to_be_paired_by_meaning():
    """The honey jar, written into the instruction."""
    assert "do not line up" in vlm.build()


def test_a_corrected_price_leaves_no_second_price_behind():
    """The bug this nearly shipped with.

    The reader correctly read 335.00 as the price. Regex went on calling the
    merged `MRP NRS. 500` region the price as well, so the set came back with
    two maximum retail prices -- and `first("mrp")` returns the earlier one,
    which is the wrong one. The pack would have been assessed on its net weight
    as a price and then reported for declaring its price twice.
    """
    readings = [vlm.Reading(field="mrp", text="MRP NRs. 335.00", box=(0.60, 0.80, 0.95, 0.90))]
    applied = vlm.apply(HONEY_LINES, readings, width=1200, height=1280)

    result = assemble.from_lines(
        applied.lines,
        ScaleEstimate(tier="A", mm_per_px=0.1, tolerance=0.01, method="operator_height"),
        reader_fields=applied.fields,
    )

    prices = result.by_field("mrp")
    assert len(prices) == 1, [d.text for d in prices]
    assert "335.00" in prices[0].text


def test_the_withdrawn_line_is_kept_on_the_record_not_deleted():
    """It becomes `other`, so it still appears on the exhibit and still reaches
    `raw_text` -- where the engine's locate-then-validate path can see it. An
    exhibit that quietly dropped what it read would be the worse document."""
    readings = [vlm.Reading(field="mrp", text="MRP NRs. 335.00", box=(0.60, 0.80, 0.95, 0.90))]
    applied = vlm.apply(HONEY_LINES, readings, width=1200, height=1280)

    result = assemble.from_lines(
        applied.lines,
        ScaleEstimate(tier="A", mm_per_px=0.1, tolerance=0.01, method="operator_height"),
        reader_fields=applied.fields,
    )

    assert "MRP NRS. 500" in result.raw_text
    assert any("MRP NRS. 500" in d.text for d in result.declarations)


def test_an_address_is_never_withdrawn_by_a_single_reading():
    """`manufacturer` wraps over five or six detected regions. Withdrawing the
    rest because the reader named one of them would delete the address."""
    lines = [
        _line("Bilal Match Works, Sivakasi - 626 123.", 40, 100),
        _line("Mktd. by ITC Limited, 37, J.L. Nehru Road,", 40, 140),
        _line("Kolkata - 700 071.", 40, 180),
    ]
    readings = [
        vlm.Reading(field="manufacturer", text="Bilal Match Works, Sivakasi - 626 123.", box=(0.0, 0.1, 0.9, 0.2))
    ]
    applied = vlm.apply(lines, readings, width=500, height=600)
    guesses = assemble.classify_lines(applied.lines, reader_fields=applied.fields)

    assert guesses[0].field == "manufacturer"
    assert "manufacturer" not in assemble.SINGLE_VALUED
