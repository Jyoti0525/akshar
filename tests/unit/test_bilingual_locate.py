"""A Latin label abutting Devanagari must still be found. Rule 6 permits Hindi.

Found on a dev-corpus pack. The pipeline detected the MRP, cropped it, read it
as `MRP\u0930 15.00(incl. of all taxes)` -- which is right; the rupee sign came back
as a Devanagari letter -- and then threw it away, because `mrp_locate` ended in
a word boundary and there is no word boundary between `P` and `\u0930`. Both are
word characters. LMPC.MRP.PRESENT then reports "Retail sale price not declared"
against a pack that declares it.

That is the worst failure this tool can have. A missed violation is a missed
case; a **fabricated** violation is an enforcement action against someone who
complied. And it is not only an OCR artefact: `MRP\u0930\u0941. 15.00` is an ordinary
bilingual rendering, so a pack printed exactly as the rules allow was
unfindable.

These tests pin both directions -- what must now match, and every look-alike
that must still not.
"""

from __future__ import annotations

import pytest

from vision.classify.regex_tier import classify_text

FOUND = [
    ("MRP\u0930 15.00(incl. of all taxes)", "mrp", "the read that exposed this"),
    ("MRP\u0930\u0941. 15.00", "mrp", "bilingual: Hindi rupee abbreviation, no space"),
    ("MRP\u20b9 15.00", "mrp", "rupee sign, no space"),
    ("MRP Rs. 45.00", "mrp", "the ordinary case, unchanged"),
    ("M.R.P. 45.00", "mrp", "dotted abbreviation, unchanged"),
    ("Maximum Retail Price Rs 45", "mrp", "spelled out, unchanged"),
    ("Net Qty\u0964 50 g", "net_quantity", "Devanagari danda straight after the label"),
    ("Net Wt. 250 g", "net_quantity", "the ordinary case, unchanged"),
]

NOT_FOUND = [
    ("24MRP07", "a batch code with MRP inside it"),
    ("MRP07", "a code, not a declaration"),
    ("AMRP 45", "MRP inside a longer Latin word"),
]


@pytest.mark.parametrize(("text", "field", "why"), FOUND)
def test_a_declaration_is_located(text, field, why):
    assert classify_text(text).field == field, why


@pytest.mark.parametrize(("text", "why"), NOT_FOUND)
def test_a_look_alike_is_still_rejected(text, why):
    assert classify_text(text).field != "mrp", why


def test_the_boundary_still_blocks_on_latin_and_digits():
    """The lookarounds must be exactly as strict as a word boundary was, for
    Latin. Only a script change is newly allowed through."""
    assert classify_text("XMRP 45").field != "mrp"
    assert classify_text("MRPX 45").field != "mrp"
    assert classify_text("1MRP 45").field != "mrp"
