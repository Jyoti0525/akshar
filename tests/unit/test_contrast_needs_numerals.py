"""The price was called illegible on a measurement taken off its caption.

---------------------------------------------------------------------------
THE FALSE ACCUSATION
---------------------------------------------------------------------------
A face serum carton, scanned live on 2026-09-19, came back with:

    LMPC.CONTRAST.NUMERALS   FAIL   found 1.888:1   expected >= 3.000:1

Rule 9(1)(b) is about the *numerals* of the retail sale price and the net
quantity -- the gazette says so -- and the crop that 1.888 was computed on read
`MRP: ₹`. The figures were inkjet-coded onto a label to the right of it, came
back from the detector as one 385 px block, and were never recognised at all.

So the manufacturer was told the price on their pack could not be read, on the
evidence of a contrast measurement taken somewhere the price is not printed.

---------------------------------------------------------------------------
WHAT CHANGED, AND WHAT DELIBERATELY DID NOT
---------------------------------------------------------------------------
`requires_numerals: true` on both rules that use this check. Where the
declaration we hold carries no digit, there is nothing here to measure and the
answer is NO_DATA.

This does NOT excuse the pack. The declaration's absence is a separate finding
under the presence rules and it still fires; only the legibility verdict is
withdrawn, and only while the silence is ours. And a declaration that *was*
read is judged exactly as before -- `gulabjal.jpg` reads `Rs.259.00 16022` at
2.21:1 and still fails, which is the whole point of keeping the rule.
"""

from __future__ import annotations

import pytest

from rules.checks import REGISTRY
from tests.unit.test_check_sweep import CONTEXT, PACK, declaration, declaration_set, rule


def contrast(*declarations, **options):
    options.setdefault("min_ratio", 3.0)
    options.setdefault("fields", ["mrp"])
    return REGISTRY["min_contrast"](
        rule("min_contrast", **options), declaration_set(*declarations), CONTEXT, PACK
    )


# ---------------------------------------------------------------------------
# The caption alone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "caption",
    [
        "MRP: ₹",  # the serum carton, exactly
        "MRP:र",  # and as the ruler set's recogniser returned it
        "MRP Rs",
        "M.R.P. (Incl. of all taxes)",
        "Net Wt.",
        "NET QUANTITY:",
    ],
)
def test_a_caption_with_no_figure_is_not_measured(caption: str) -> None:
    outcome = contrast(
        declaration(field="mrp", text=caption, contrast_ratio=1.888),
        requires_numerals=True,
    )
    assert outcome.status == "NO_DATA"
    assert outcome.measured is None


def test_the_reason_tells_the_officer_what_to_do_about_it() -> None:
    outcome = contrast(
        declaration(field="mrp", text="MRP: ₹", contrast_ratio=1.0),
        requires_numerals=True,
    )
    assert outcome.detail is not None
    assert "caption" in outcome.detail.lower()


# ---------------------------------------------------------------------------
# The figures, where they were read
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "ratio", "expected"),
    [
        ("Rs.259.00 16022", 2.21, "FAIL"),  # gulabjal.jpg, measured
        ("MRP Rs. 645.00", 1.50, "FAIL"),
        ("MRP Rs. 645.00", 2.85, "REVIEW"),  # inside the +/-0.2 band
        ("MRP Rs. 645.00", 8.00, "PASS"),
        ("NET QUANTITY: 15 NUMBER", 8.649, "PASS"),  # agarbati.webp, measured
    ],
)
def test_a_declaration_carrying_its_figures_is_judged_exactly_as_before(
    text: str, ratio: float, expected: str
) -> None:
    outcome = contrast(
        declaration(field="mrp", text=text, contrast_ratio=ratio),
        requires_numerals=True,
    )
    assert outcome.status == expected


def test_devanagari_figures_are_figures() -> None:
    """A pack that prints its price in Devanagari digits has printed its price:
    `\\d` is Unicode-aware on a Python `str`. Refusing to measure it would be a
    script-shaped hole in Rule 9(1)(b)."""
    outcome = contrast(
        declaration(field="mrp", text="मूल्य २५९", contrast_ratio=1.0),
        requires_numerals=True,
    )
    assert outcome.status == "FAIL"


# ---------------------------------------------------------------------------
# The caption and the figure both present
# ---------------------------------------------------------------------------


def test_the_caption_does_not_drag_the_figure_down() -> None:
    """The check keeps the WORST of what it measures, and a caption set in a
    tint over artwork routinely measures worse than the price beside it. Before
    this, one panel carrying both meant the pack was judged on the caption."""
    outcome = contrast(
        declaration(field="mrp", text="MRP: ₹", contrast_ratio=1.10),
        declaration(field="mrp", text="645.00", contrast_ratio=9.20),
        requires_numerals=True,
    )
    assert outcome.status == "PASS"
    assert outcome.measured == pytest.approx(9.20)


# ---------------------------------------------------------------------------
# The rule that does not ask for numerals
# ---------------------------------------------------------------------------


def test_without_the_flag_nothing_changes() -> None:
    """`requires_numerals` is read off the rulepack rather than wired into the
    check, so a future contrast rule about a phrase still measures the phrase."""
    outcome = contrast(declaration(field="mrp", text="MRP: ₹", contrast_ratio=1.888))
    assert outcome.status == "FAIL"


# ---------------------------------------------------------------------------
# Both rules in the shipped pack ask for it
# ---------------------------------------------------------------------------


def test_every_contrast_rule_in_the_pack_measures_figures() -> None:
    """Rule 9(1)(b) says "numerals" and Rule 18(5) is about a price obliterated
    or altered. Neither is a statement about a caption, and a new contrast rule
    added without this flag would quietly reopen the defect."""
    from rules import cached_rulepack

    pack = cached_rulepack()
    contrast_rules = [r for r in pack.rules if r.check == "min_contrast"]
    assert contrast_rules, "the pack should still carry the contrast rules"
    for r in contrast_rules:
        assert r.opt("requires_numerals") is True, r.id
