"""Word proposals must become printed lines — and must not become paragraphs.

DBNet proposes words. `MRP Rs.` and `10` are two proposals, each of which
declares nothing on its own, and the classifier was being handed them
separately. Nothing was ever assembling the line.

The failure mode on the other side is worse than the one being fixed, so it is
tested harder: merge too eagerly and two stacked lines of marketing copy become
one region whose box has the height of a paragraph, which then measures nothing
and consumes a crop from a budget of eight. The fixtures below are taken from
real dev-corpus geometry, including the pair that fooled the first attempt.
"""

from __future__ import annotations

from vision.ocr.lines import merge_into_lines
from vision.types import Box, TextRegion


def _r(x: float, y: float, w: float, h: float, score: float = 0.9) -> TextRegion:
    return TextRegion(box=Box(x=x, y=y, w=w, h=h), score=score)


def _texts(merged: list[TextRegion], raw: list[tuple]) -> list[str]:
    """Which fragments ended up inside each merged box, in reading order."""
    out = []
    for region in sorted(merged, key=lambda r: r.box.y):
        inside = [
            t
            for x, y, w, h, t in raw
            if region.box.x - 1 <= x
            and x + w <= region.box.x2 + 1
            and region.box.y - 1 <= y
            and y + h <= region.box.y2 + 1
        ]
        out.append(" ".join(inside))
    return out


# Straight off a dev-corpus pack: a label column and a value column.
PACK = [
    (167, 585, 65, 36, "MRP Rs."),
    (275, 597, 160, 32, "10"),
    (172, 618, 60, 32, "(incl. of"),
    (283, 629, 152, 32, "100004"),
    (170, 648, 78, 30, "all taxes) :"),
    (172, 678, 78, 30, "Batch No.:"),
    (282, 673, 157, 31, "060924"),
    (171, 700, 56, 42, "Md:"),
    (172, 728, 67, 44, "Useby:"),
]


def test_a_label_joins_the_value_printed_beside_it():
    merged = merge_into_lines([_r(*p[:4]) for p in PACK])
    joined = _texts(merged, PACK)
    assert "MRP Rs. 10" in joined
    assert "Batch No.: 060924" in joined


def test_lines_stacked_above_each_other_are_never_joined():
    """The bug the first attempt shipped.

    These two are consecutive lines of body copy. They overlap vertically by
    61% -- past `OVERLAP_FRAC` -- because DBNet's boxes are loose. What tells
    them apart is that they sit on top of each other rather than beside: their
    gap along the reading axis is -168 px for lines 45 px tall.
    """
    stacked = [_r(425, 550, 295, 49), _r(427, 574, 168, 41)]
    assert len(merge_into_lines(stacked)) == 2


def test_every_fragment_survives_somewhere():
    """Merging regroups; it must never drop a proposal."""
    regions = [_r(*p[:4]) for p in PACK]
    merged = merge_into_lines(regions)
    for region in regions:
        assert any(
            m.box.x - 1 <= region.box.x
            and region.box.x2 <= m.box.x2 + 1
            and m.box.y - 1 <= region.box.y
            and region.box.y2 <= m.box.y2 + 1
            for m in merged
        )


def test_a_merged_line_carries_its_weakest_score():
    merged = merge_into_lines([_r(167, 585, 65, 36, 0.9), _r(275, 597, 160, 32, 0.4)])
    assert len(merged) == 1
    assert merged[0].score == 0.4


def test_type_set_at_wildly_different_sizes_does_not_join():
    """A brand name beside small print is not one line."""
    assert len(merge_into_lines([_r(10, 100, 200, 80), _r(220, 130, 60, 20)])) == 2


def test_text_running_down_the_pack_merges_along_its_own_axis():
    """Vertical fragments stack along y, and must not reach sideways.

    A column of print down the side of a pack is a run of tall narrow boxes.
    Merging it along x would join it to whatever is printed beside it.
    """
    column = [_r(500, 100, 40, 120), _r(505, 235, 40, 90)]
    beside = _r(600, 100, 40, 120)
    merged = merge_into_lines([*column, beside])
    assert len(merged) == 2
    tall = max(merged, key=lambda r: r.box.h)
    assert tall.box.h >= 225  # the two vertical fragments, joined
    assert tall.box.w < 100  # and it did not reach across to `beside`


def test_horizontal_and_vertical_regions_never_merge_into_each_other():
    merged = merge_into_lines([_r(100, 100, 200, 30), _r(100, 100, 30, 200)])
    assert len(merged) == 2


def test_a_single_region_is_returned_untouched():
    only = _r(10, 10, 50, 20)
    assert merge_into_lines([only]) == [only]
    assert merge_into_lines([]) == []


def test_a_merged_line_reports_the_type_size_not_the_box():
    """The union box is taller than the type in it, and ranking reads that.

    `MRP Rs.` spans y 585-621 and the `10` beside it spans y 597-629. Unioned,
    the box is 44 px tall for type that is 32 to 36 px tall -- a 29%
    overstatement, which was enough to push the declaration out of the
    statutory size band and cost it the crop it needed.
    """
    merged = merge_into_lines([_r(167, 585, 65, 36), _r(275, 597, 160, 32)])
    assert len(merged) == 1
    assert merged[0].box.h == 44.0
    assert merged[0].line_height_px == 34.0


def test_an_unmerged_region_makes_no_claim_about_its_line_height():
    """Straight from the detector, the box's minor axis is the answer."""
    assert merge_into_lines([_r(10, 10, 50, 20)])[0].line_height_px is None
