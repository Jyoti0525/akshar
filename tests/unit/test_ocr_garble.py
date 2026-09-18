"""What the recogniser mangles, and what must survive being mangled.

Every case below is a string the OCR actually produced on a real pack in the
2026-09-18 annotated set (`data/annotations/export-2026-09-18.json`), where a
person had drawn a box and named the field. They are the measured gap between
"the pipeline found the text" (78.9%) and "the pipeline named it as a person
did" — naming is what fails, and it fails because captions arrive damaged.

---------------------------------------------------------------------------
AND THE HALF OF THIS FILE THAT MATTERS MORE
---------------------------------------------------------------------------
The `guards` below are not padding. Widening a caption pattern is the cheapest
way in this codebase to destroy a declaration, because the tiers resolve by
leftmost match and one over-eager pattern silently takes a line from another
field.

That happened while these very fixes were being written. Adding an OCR-noise
strip for barcodes reused a variable the batch-code guard reads, `MRP Rs 45`
became `MRPRs45`, and the retail sale price was classified `batch` — gone from
the pack entirely, on a pack that declares it plainly. It was caught by a guard
case typed by hand into a scratch script, which is not a place bugs should be
caught. So the guards live here now.
"""

from __future__ import annotations

import pytest

from vision.classify.regex_tier import classify_text

# -- what OCR produced, and what it is ---------------------------------------
garbled = [
    pytest.param('"9048"6722', "barcode", id="ean-with-a-quote-mark-in-it"),
    pytest.param('8901537"024014', "barcode", id="13-digit-ean-split-by-a-quote"),
    pytest.param("NET W. 160 gms", "net_quantity", id="net-W-not-net-WT"),
    pytest.param("NET W 30 g", "net_quantity", id="net-W-unpunctuated"),
    pytest.param("MANUFACURED BY: RAUCH TRADING AG", "manufacturer", id="manufactured-minus-its-T"),
]


@pytest.mark.parametrize(
    ("text", "expected"), [(p.values[0], p.values[1]) for p in garbled], ids=[p.id for p in garbled]
)
def test_a_damaged_caption_is_still_read(text, expected):
    assert classify_text(text).field == expected


# -- and what must not move, whatever is widened -----------------------------
guards = [
    # The one that broke. `MRP Rs 45` with its spaces squeezed out is an
    # alphanumeric run carrying the letters MRP, which is the exact shape of the
    # batch code the hard-negative guard hunts for.
    ("MRP Rs 45", "mrp"),
    ("MRP Rs. 45.00", "mrp"),
    ("M.R.P. Rs. 45.00", "mrp"),
    ("MRP (incl. of all taxes): Rs 240.00", "mrp"),
    # A batch code that contains the letters MRP is still a batch code.
    ("24MRP07", "batch"),
    ("Batch 24MRP07", "batch"),
    ("B.No.: PA070726E", "batch"),
    # Ten digits is an Indian mobile number at least as often as it is a
    # barcode, and a consumer-care helpline is a Rule 6(2) declaration. The
    # barcode rule must not reach it.
    ("9876543210", "other"),
    ("Consumer care: 1800 22 4020", "consumer_care"),
    # A promotional graphic is never the retail sale price.
    ("Rs. 20 OFF", "marketing_text"),
    ("SPECIAL PRICE 99", "marketing_text"),
    # The four address fields stay four fields.
    ("Packed by: ABC Foods", "packer"),
    ("Imported by: XYZ Traders", "importer"),
    ("Manufactured by: Parle Products", "manufacturer"),
    # Undamaged captions keep working.
    ("Net Wt. 500 g", "net_quantity"),
    ("MFD: 11/2025", "mfg_date"),
    ("BEST BEFORE 12 MONTHS FROM MFG", "expiry_date"),
]


@pytest.mark.parametrize(("text", "expected"), guards)
def test_widening_a_pattern_did_not_take_a_line_from_another_field(text, expected):
    assert classify_text(text).field == expected, (
        f"{text!r} is a {expected}. If a caption pattern was just widened, it reached too far."
    )


def test_the_barcode_length_gap_is_left_open_on_purpose():
    """Two real barcodes are still missed and that is the right trade.

    `3507170632` and `19606030616` are 10 and 11 digits — inside the gap the
    pattern leaves between EAN-8 and UPC-A. Closing it would catch them and
    would also rename every ten-digit helpline printed without a caption, which
    takes a Rule 6(2) declaration off the pack. A missed barcode costs nothing;
    no rule targets `barcode`.
    """
    assert classify_text("3507170632").field == "other"
    assert classify_text("19606030616").field == "other"
