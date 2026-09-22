"""One tall declaration must not excuse every short one on the pack.

AKSHAR.md Rule 7(3), Rule 9(4).

`bilingual_group` exists to honour Rule 9(4): a bilingual pack prints the same
declaration twice, in two scripts, often at two sizes, and the requirement is
satisfied if either instance clears the bar. Flagging the smaller one would
convict a pack that complies.

It said it returned "one group per field" and returned one group for
everything. That is the same thing only while a rule names a single field.
`LMPC.LETTER.MIN_HEIGHT` names four, so on a real pack the 1.48 mm
manufacturing date was quietly covering a 0.90 mm consumer-care address, and
Rule 7(3) does not say the tallest declaration has to clear 1 mm — it says the
letters do.

These tests pin both halves, because the fix has to keep the leniency it was
written for while losing the leniency it was not.
"""

from __future__ import annotations

from contracts import Box, Declaration
from rules.checks._common import bilingual_group


def _declaration(field: str, height_mm: float, script: str = "latin") -> Declaration:
    return Declaration(
        field=field,  # type: ignore[arg-type]
        text=f"{field} at {height_mm} mm",
        script=script,  # type: ignore[arg-type]
        box=Box(x=0.0, y=0.0, w=100.0, h=10.0),
        height_px=10.0,
        height_mm=height_mm,
        height_mm_tolerance=0.1,
        ocr_confidence=0.9,
        field_confidence=0.9,
    )


def test_two_scripts_of_one_field_stay_together():
    """Rule 9(4), which is the whole reason this function exists."""
    latin = _declaration("manufacturer", 1.8, "latin")
    devanagari = _declaration("manufacturer", 0.7, "devanagari")

    groups = bilingual_group([latin, devanagari], "max")

    assert len(groups) == 1, "the same declaration in two scripts must be judged together"
    assert [id(d) for d in groups[0]] == [id(latin), id(devanagari)]


def test_different_fields_are_judged_separately():
    """The defect: a tall date excusing a short address.

    These are not one declaration in two scripts. They are two declarations,
    and Rule 7(3) applies to each.
    """
    date = _declaration("mfg_date", 1.48)
    care = _declaration("consumer_care", 0.90)

    groups = bilingual_group([date, care], "max")

    assert len(groups) == 2, (
        "four fields collapsed into one group let the tallest declaration on "
        "the pack satisfy the height rule for all of them"
    )
    assert {d.field for group in groups for d in group} == {"mfg_date", "consumer_care"}
    assert all(len(group) == 1 for group in groups)


def test_a_single_field_rule_is_unaffected():
    """Two of the three height rules name one field; their behaviour must not move."""
    one = _declaration("mrp", 2.0)
    two = _declaration("mrp", 3.0)

    groups = bilingual_group([one, two], "max")

    assert len(groups) == 1
    assert [id(d) for d in groups[0]] == [id(one), id(two)]


def test_the_strict_mode_still_judges_every_declaration_alone():
    """Without `bilingual: max` nothing is grouped, and that is unchanged."""
    declarations = [
        _declaration("manufacturer", 1.2),
        _declaration("manufacturer", 0.8),
        _declaration("consumer_care", 0.9),
    ]

    groups = bilingual_group(declarations, None)

    assert len(groups) == 3
    assert all(len(group) == 1 for group in groups)


def test_grouping_preserves_every_declaration():
    """Nothing may be dropped on the way through — a lost declaration is a
    height nobody judges, which is the failure this whole change is about."""
    declarations = [
        _declaration("manufacturer", 1.2),
        _declaration("manufacturer", 0.8, "devanagari"),
        _declaration("consumer_care", 0.9),
        _declaration("generic_name", 2.4),
        _declaration("mfg_date", 1.1),
    ]

    groups = bilingual_group(declarations, "max")

    flattened = [d for group in groups for d in group]
    assert len(flattened) == len(declarations)
    assert sorted(id(d) for d in flattened) == sorted(id(d) for d in declarations)


def test_no_declarations_is_no_groups():
    assert bilingual_group([], "max") == []
    assert bilingual_group([], None) == []
