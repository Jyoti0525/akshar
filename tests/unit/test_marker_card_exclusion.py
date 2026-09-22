"""The whole reference card is excluded from the read, not one marker of it.

AKSHAR.md sections 8b and 14.

`roi.drop_regions_on` exists because a ChArUco card is, to a text detector,
extremely convincing text — a grid of high-contrast blocks at printed-type
scale. It took a single quad, which was the right shape for a card carrying one
marker, and quietly the wrong shape for the card
`scripts/make_marker_card.py` actually renders: a 5x4 board carrying **ten**.

Nine of the ten were being read as declarations. It cost nothing visible on the
golden scenes, which draw one marker apiece, and it was invisible in every
bench, because until the card was printed on 2026-09-22 no photograph in the
repository contained a real one. On the first forty that did, the card supplied
5 to 82 junk regions a frame against a budget of 96 — on the 6 g Moov tube, 82
of 108 proposals were the card, so the region budget was spent on the reference
object before the packet was reached.

The two tests that matter here are the two halves of that: everything on the
card goes, and nothing on the packet does. A filter that took the second half
for granted would pass by dropping the frame.
"""

from __future__ import annotations

import numpy as np
import pytest

from contracts.declarations import Box
from vision.ocr import roi
from vision.scale import tier_a
from vision.types import TextRegion

from .synthetic import draw_marker


def _region(x: float, y: float, w: float, h: float) -> TextRegion:
    return TextRegion(box=Box(x=x, y=y, w=w, h=h), score=0.9)


def _square(x: float, y: float, side: float) -> list[tuple[float, float]]:
    return [(x, y), (x + side, y), (x + side, y + side), (x, y + side)]


def test_a_region_on_any_marker_is_dropped_not_only_the_first():
    """The defect exactly: ten markers in, one excluded, nine read as text."""
    quads = [_square(100 + 200 * i, 100, 80) for i in range(10)]
    on_card = [_region(110 + 200 * i, 110, 60, 40) for i in range(10)]

    kept = roi.drop_regions_on(list(on_card), quads)
    assert kept == [], "a region lying on a marker survived the filter"

    # And the shape of the bug it replaces: only the first quad supplied.
    survived = roi.drop_regions_on(list(on_card), [quads[0]])
    assert len(survived) == 9, (
        "this is the old single-quad behaviour and the test is only meaningful "
        "while it still differs from the new one"
    )


def test_declarations_on_the_packet_are_never_dropped():
    """The half that must not be taken for granted.

    Dropping the whole frame would satisfy the test above perfectly. The card
    sits beside the packet, so a filter that reached past the card's own
    outline would delete the declarations this pipeline exists to read.
    """
    quads = [_square(100 + 200 * i, 100, 80) for i in range(10)]
    pack = [
        _region(2000, 400, 300, 40),   # a line of address
        _region(2000, 460, 120, 30),   # MRP
        _region(1950, 90, 200, 25),    # level with the card, clear of it
    ]
    assert roi.drop_regions_on(list(pack), quads) == pack


def test_a_region_straddling_a_marker_edge_is_still_dropped():
    """Half on the card is not half a declaration.

    `MARKER_OVERLAP` is measured against the smaller of the two areas, so this
    also covers the opposite case the comment in `roi` describes: one loose box
    drawn around the whole marker, larger than the marker itself.
    """
    quad = _square(100, 100, 80)
    mostly_on = _region(110, 110, 70, 70)       # covers most of the marker
    around_it = _region(80, 80, 130, 130)       # bigger than the marker
    beside_it = _region(300, 100, 80, 40)       # clear of it

    kept = roi.drop_regions_on([mostly_on, around_it, beside_it], [quad])
    assert kept == [beside_it]


def test_no_card_drops_nothing():
    regions = [_region(10, 10, 50, 20), _region(80, 10, 50, 20)]
    assert roi.drop_regions_on(list(regions), None) == regions
    assert roi.drop_regions_on(list(regions), []) == regions
    # A degenerate quad is not a card either, and must not delete the frame.
    assert roi.drop_regions_on(list(regions), [[(0.0, 0.0), (1.0, 1.0)]]) == regions


def test_marker_quads_finds_every_marker_and_agrees_with_marker_quad():
    """`marker_quads()[0]` must be the square rectification warps against.

    They are separate calls on the same detection, and if their ordering ever
    diverged the pipeline would rectify against one marker while measuring
    another — an error that produces a plausible number rather than a failure.
    """
    canvas = np.full((900, 1400, 3), 245, np.uint8)
    centres = [(200, 200), (500, 200), (800, 200), (200, 500)]
    for index, centre in enumerate(centres):
        # Deliberately different sizes: `detect_markers` sorts largest first.
        draw_marker(canvas, centre=centre, edge_px=90 + 12 * index, marker_id=index)

    quads = tier_a.marker_quads(canvas)
    assert len(quads) == len(centres), f"found {len(quads)} of {len(centres)} markers"
    assert quads[0] == tier_a.marker_quad(canvas)


def test_the_printed_card_supplies_ten_markers_to_exclude():
    """A guard on the card design, not on the detector.

    If `make_marker_card` is ever re-rendered with a different board, the number
    of markers the read has to step over changes with it, and the single-quad
    assumption this module removed would creep back unnoticed.
    """
    make_marker_card = pytest.importorskip("scripts.make_marker_card")

    page = make_marker_card.render()
    quads = tier_a.marker_quads(page)
    assert len(quads) == 10, (
        f"the rendered card carries {len(quads)} detectable markers; "
        "roi.drop_regions_on must be given all of them"
    )
