"""A coded sticker is several declarations, and it arrived as one crop.

From a live scan of a face serum carton on 2026-09-19. The values were printed
by a coding printer onto a white label beside their captions:

    Batch No.:              B77A6571
    Use before:             01/2028
    MRP: Rs                 645.00
    USP per ml: Rs          21.50/ML

Every caption was read and named correctly. The block of values came back from
the detector as regions **385 px and 195 px tall on a panel whose lines run 62
to 107 px**, and the recogniser -- which decodes one line along one sequence --
returned `'['` and `'S2T'` for them.

So the officer's exhibit showed a batch caption with no batch, a price caption
with no price, and an expiry caption with no date. Nothing downstream can
recover that: `vision.ocr.split` un-welds a row that *was* read, and
`vision.classify.associate` cannot pair a value that was never text.

Measured over 70 corpus photographs after the fix: six blocks split, and the
alphanumeric characters recovered from them went from 21 to 48.
"""

from __future__ import annotations

import numpy as np
import pytest

from vision.ocr import rows
from vision.types import Box, TextRegion

PIL = pytest.importorskip("PIL", reason="Pillow draws the reference block")
from PIL import Image as PILImage  # noqa: E402
from PIL import ImageDraw, ImageFont  # noqa: E402

FACES = [r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\arial.ttf"]


def _font(size: int):
    from pathlib import Path

    for path in FACES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    pytest.skip("no TrueType face available to draw a reference block")


def _block(lines: list[str], *, line_h: int = 60, leading: int = 14) -> np.ndarray:
    font = _font(line_h)
    width, height = 520, (line_h + leading) * len(lines) + 30
    image = PILImage.new("L", (width, height), 245)
    draw = ImageDraw.Draw(image)
    y = 15
    for text in lines:
        draw.text((18, y), text, font=font, fill=25)
        y += line_h + leading
    return np.stack([np.array(image)] * 3, axis=-1)


def _page(block: np.ndarray) -> list[TextRegion]:
    """The block, plus the caption regions that tell the page what a line is."""
    captions = [
        TextRegion(box=Box(x=0.0, y=0.0, w=671.0, h=98.0), score=0.9),
        TextRegion(box=Box(x=0.0, y=0.0, w=242.0, h=64.0), score=0.9),
        TextRegion(box=Box(x=0.0, y=0.0, w=344.0, h=79.0), score=0.9),
        TextRegion(box=Box(x=0.0, y=0.0, w=173.0, h=62.0), score=0.9),
    ]
    whole = TextRegion(
        box=Box(x=0.0, y=0.0, w=float(block.shape[1]), h=float(block.shape[0])),
        score=0.9,
    )
    return [*captions, whole]


# ---------------------------------------------------------------------------
# Finding the lines
# ---------------------------------------------------------------------------


def test_the_serum_sticker_comes_apart_into_its_five_lines() -> None:
    printed = ["B77A6571", "01/2026", "01/2028", "645.00", "21.50/ML"]
    block = _block(printed)

    out = rows.unstack(block, _page(block))

    produced = [r for r in out if r.box.w == block.shape[1] and r.box.h < block.shape[0]]
    assert len(produced) == len(printed)
    assert [round(r.box.y) for r in produced] == sorted(round(r.box.y) for r in produced)


def test_every_row_stays_inside_the_block_it_came_from() -> None:
    block = _block(["645.00", "21.50/ML", "01/2028"])
    out = rows.unstack(block, _page(block))
    produced = [r for r in out if r.box.w == block.shape[1] and r.box.h < block.shape[0]]

    for region in produced:
        assert region.box.y >= 0
        assert region.box.y2 <= block.shape[0] + 1


def test_a_row_carries_its_own_type_size_and_not_the_blocks() -> None:
    """`line_height_px` decides which crops the budget buys. A row that
    inherited the block's height would be ranked as 400 px of display type and
    sent to the back of the queue behind the brand name."""
    block = _block(["645.00", "21.50/ML"])
    produced = [
        r
        for r in rows.unstack(block, _page(block))
        if r.box.w == block.shape[1] and r.box.h < block.shape[0]
    ]

    assert produced
    for region in produced:
        assert region.line_height_px is not None
        assert region.line_height_px < block.shape[0] / 2


def test_the_block_polygon_is_dropped_rather_than_inherited() -> None:
    """A polygon describes the whole block. Carried onto a row it would draw a
    rectangle on the exhibit around text the row does not contain."""
    block = _block(["645.00", "21.50/ML"])
    page = _page(block)
    page[-1] = TextRegion(
        box=page[-1].box,
        score=page[-1].score,
        polygon=[(0.0, 0.0), (520.0, 0.0), (520.0, 400.0), (0.0, 400.0)],
    )

    produced = [
        r
        for r in rows.unstack(block, page)
        if r.box.w == block.shape[1] and r.box.h < block.shape[0]
    ]

    assert produced
    assert all(r.polygon is None for r in produced)


# ---------------------------------------------------------------------------
# Leaving alone what is already one line
# ---------------------------------------------------------------------------


def test_an_ordinary_line_is_returned_untouched() -> None:
    block = _block(["MRP Rs. 645.00"])
    page = _page(block)

    out = rows.unstack(block, page)

    assert len(out) == len(page)
    assert out[-1] is page[-1]


def test_text_running_down_the_side_of_a_pack_is_never_split() -> None:
    """A vertical line is tall by nature, and a projection across it would cut
    it into its own characters."""
    block = _block(["645.00", "21.50/ML"])
    tall = TextRegion(box=Box(x=0.0, y=0.0, w=60.0, h=400.0), score=0.9)
    page = [TextRegion(box=Box(x=0.0, y=0.0, w=300.0, h=70.0), score=0.9), tall]

    out = rows.unstack(block, page)

    assert out == page


def test_a_page_with_no_line_shaped_region_declines_to_guess() -> None:
    """The yardstick is the page's own lines. With nothing line-shaped on it
    there is no yardstick, and inventing one would split by a constant."""
    block = _block(["645.00", "21.50/ML"])
    page = [TextRegion(box=Box(x=0.0, y=0.0, w=100.0, h=400.0), score=0.9)]

    assert rows.unstack(block, page) == page


def test_a_paragraph_is_left_whole_rather_than_spending_the_whole_budget() -> None:
    block = _block([f"line {n}" for n in range(rows.MAX_ROWS + 3)], line_h=30, leading=8)
    page = _page(block)

    assert rows.unstack(block, page) == page


# ---------------------------------------------------------------------------
# The projection itself
# ---------------------------------------------------------------------------


def test_ink_bands_finds_one_band_per_printed_line() -> None:
    assert len(rows.ink_bands(_block(["AAA", "BBB", "CCC"]))) == 3


def test_ink_bands_reports_a_single_line_as_one_band() -> None:
    assert len(rows.ink_bands(_block(["AAA"]))) == 1


def test_a_blank_crop_has_no_bands() -> None:
    assert rows.ink_bands(np.full((120, 300, 3), 240, dtype=np.uint8)) == []


def test_light_text_on_a_dark_pack_is_found_too() -> None:
    """About a third of Indian packaging prints light on dark, and the serum
    carton is one of them. `binarise` orients the polarity; this pins that the
    projection inherits it."""
    inverted = 255 - _block(["645.00", "21.50/ML", "01/2028"])

    assert len(rows.ink_bands(inverted)) == 3
