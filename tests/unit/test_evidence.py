"""Weak signals, combined — and the look-alikes they must still refuse.

The case this exists for, straight off `shampoo_400ml`. The MRP block was
detected and cropped correctly and every exact pattern failed on it:

    'MPEE'       'MRP RS.', three edits away
    '559.00'     read at confidence 1.00
    'otal tes)'  '(incl. of all taxes)'

A human is not in doubt. The tests below pin that we are not either — and,
much more carefully, that `Rs. 20 OFF` and a barcode still are.
"""

from __future__ import annotations

import pytest

from vision.classify.evidence import MIN_SCORE, best_candidate, levenshtein, score

SHAMPOO = ["MPEE", "559.00", "otal tes)", "OCT 2024", "B.NO.", "BAM4J062"]


def test_the_line_that_started_this_is_still_not_recovered():
    """The uncomfortable one, and the reason it is written down.

    Assembled, `'MPEE 559.00 otal tes)'` yields exactly one signal: the amount.
    `'tes'` is two edits from `'taxes'` on a five-letter word, and `'MPEE'` is
    three from `'MRP'`. Admitting either would mean allowing a 40% error rate
    inside a token, which is where fuzzy matching stops recovering words and
    starts inventing them -- `mrp` would begin matching `mfg` and `map`.

    So this module does **not** rescue this line, and the threshold was not
    lowered until it did. What is broken here is the reading, and the fix for a
    bad reading is a better recogniser, not a more forgiving matcher. Evidence
    scoring recovers the case where *one* word of a line is garbled; it cannot
    recover a line where almost every word is.
    """
    found = score("MPEE 559.00 otal tes)", "mrp")
    assert found.score == 1.0
    assert found.reasons == ["carries a price-shaped amount with paise"]
    assert not found.is_worth_reading


def test_no_single_fragment_is_enough_on_its_own():
    """Each of the three alone is exactly what a false positive looks like."""
    for fragment in ("MPEE", "559.00", "otal tes)"):
        assert not score(fragment, "mrp").is_worth_reading, fragment


def test_the_amount_alone_never_wins_a_crop():
    assert best_candidate(SHAMPOO, "mrp") is None


def test_a_promotional_price_is_not_an_mrp():
    """`Rs. 20 OFF` is price-shaped and carries a rupee marker. It must fail
    on the amount: a discount is written without paise."""
    assert not score("Rs. 20 OFF", "mrp").is_worth_reading


def test_a_barcode_is_not_a_price():
    assert not score("8904352003912", "mrp").is_worth_reading


def test_a_phone_number_is_not_a_price():
    assert not score("Call: +91 8901555", "mrp").is_worth_reading


def test_a_readable_mrp_scores_strongly():
    found = score("MRP Rs. 45.00 (inclusive of all taxes)", "mrp")
    assert found.score >= MIN_SCORE
    assert len(found.reasons) == 3


def test_a_misread_net_quantity_is_recovered_by_its_unit():
    """`Net Qty.: 50 g` read as `Net Qay: 50g`. The unit symbol survives what
    the word did not — one or two characters have fewer ways to go wrong."""
    found = score("Net Qay: 50g", "net_quantity")
    assert found.is_worth_reading
    assert any("unit symbol" in r for r in found.reasons)


def test_a_bare_unit_is_not_a_declaration():
    assert not score("contains 2 g of salt per serving", "net_quantity").is_worth_reading


@pytest.mark.parametrize(
    ("a", "b", "distance"),
    [("mrp", "mrp", 0), ("taxes", "tes", 2), ("", "abc", 3), ("qty", "qay", 1)],
)
def test_edit_distance(a, b, distance):
    assert levenshtein(a, b) == distance
    assert levenshtein(b, a) == distance


def test_short_tokens_are_held_to_a_tighter_tolerance():
    """A three-letter token allows one edit, not two. Otherwise `mrp` starts
    matching `map`, `mfg` and `top`, and fuzzy matching finds things that are
    not there."""
    assert score("mfg 12.00", "mrp").score < MIN_SCORE


def test_an_unscored_field_returns_nothing_rather_than_an_opinion():
    assert score("Batch No.: 060924", "batch").score == 0.0
