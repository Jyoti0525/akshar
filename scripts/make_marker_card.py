"""Generate the printable AKSHAR inspection card. AKSHAR.md sections 8b and 18b.

    python scripts/make_marker_card.py
    -> data/marker_card/akshar_card_A4.png  (print at 100%, no scaling)

**What this is for.** Section 8b B3 replaced the ₹5 coin with a printed marker
of known physical size, because a coin gives one apparent diameter that
foreshortens into an ellipse the moment the camera tilts — which is most of the
time in a shop — whereas a marker gives four sub-pixel corners and yields the
scale *and* the homography from one detection. This script prints that marker.

**The single number that matters is the square size**, and it is a *measured*
number, not a declared one. `MARKER_EDGE_MM` in `vision/scale/tier_a.py` says
how large the printed square is, and every millimetre this system reports is
that value multiplied by a pixel ratio. A card printed at 96% — which is what
"fit to page" quietly does — puts a 4% error into a legal document with nothing
anywhere to reveal it. So the card carries a **printed 100 mm ruler line**: check
it with a steel rule after printing, and if it is not 100 mm, the card is wrong
and the printer settings are what to fix.

**Two shapes, one file.** The card holds a ChArUco board, and a ChArUco board is
detected by an ArUco pass followed by chessboard-corner refinement — so
`vision.scale.tier_a`, which today reads single ArUco markers, already finds
every marker on it with no change. That is the property that made ChArUco a
card-design decision rather than a code one.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vision.scale.tier_a import DEFAULT_DICTIONARY, MARKER_EDGE_MM  # noqa: E402

OUTPUT_DIR = Path("data/marker_card")

SQUARES_X, SQUARES_Y = 5, 4
"""A 5x4 board. Small enough to lay flat beside a packet without covering the
declarations we came to read, large enough that several interior corners are
visible even when a hand or the packet itself occludes part of it."""

MARKER_MM = MARKER_EDGE_MM
"""The **ArUco marker** — the black square with the bit pattern in it.

This, and not the chessboard cell, is the length `vision.scale.tier_a` measures:
`detectMarkers` returns the corners of the marker's black border, and `tier_a`
divides `MARKER_EDGE_MM` by the pixel edge it observes. Taken from `tier_a`
rather than restated so the card and the code that measures against it cannot
disagree.

**This is the trap that this card was built with, wrongly, first.** The obvious
reading of a ChArUco board is that its *square* is the unit, and setting
`SQUARE_MM = MARKER_EDGE_MM` with OpenCV's usual 0.75 marker ratio prints a
marker 25% smaller than the code believes — so every measurement comes back a
third too large. It was caught by `scripts/make_u1_example.py`, which measures a
digit of known physical height through its own printed card and fails if the
answer is wrong. Detection alone would never have caught it: all ten markers
decoded perfectly and the scale resolved cleanly, to the wrong number."""

SQUARE_MM = 34.0
"""The chessboard cell that carries each marker.

The white margin around the marker is what ArUco's adaptive threshold needs to
find the black border at all — a board whose markers run to the cell edge is
undetectable while looking perfectly correct to a person. OpenCV states the
requirement in terms of the marker's own bit cells: the margin must be at least
70% of one cell. A 25 mm marker from a 4x4 dictionary renders as 6x6 cells
(4 data bits plus a one-cell black border each side), so a cell is 4.17 mm and
the margin must clear 2.92 mm. 34 mm gives 4.5 mm a side.

30 mm was tried first and OpenCV refused it out loud, which is the good case —
it is the same 2.5 mm margin a person would happily eyeball as "plenty"."""

DPI = 600
"""Printed at 600 dpi. A cheap office laser resolves it, and the black/white edge
lands on a pixel boundary rather than being anti-aliased into a grey ramp that
sub-pixel corner refinement then has to guess through."""

RULER_MM = 100.0
A4_W_MM, A4_H_MM = 210.0, 297.0


def mm_to_px(mm: float) -> int:
    return round(mm * DPI / 25.4)


def build_board(dictionary: str = DEFAULT_DICTIONARY):
    aruco_dict = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary))
    return cv2.aruco.CharucoBoard(
        (SQUARES_X, SQUARES_Y),
        squareLength=SQUARE_MM / 1000.0,
        markerLength=MARKER_MM / 1000.0,
        dictionary=aruco_dict,
    )


def render(dictionary: str = DEFAULT_DICTIONARY) -> np.ndarray:
    """The A4 sheet, at `DPI`, white with the board and its check marks on it."""
    page = np.full((mm_to_px(A4_H_MM), mm_to_px(A4_W_MM)), 255, dtype=np.uint8)

    board = build_board(dictionary)
    board_w, board_h = mm_to_px(SQUARES_X * SQUARE_MM), mm_to_px(SQUARES_Y * SQUARE_MM)
    image = board.generateImage((board_w, board_h))

    x0 = (page.shape[1] - board_w) // 2
    y0 = mm_to_px(40.0)
    page[y0 : y0 + board_h, x0 : x0 + board_w] = image

    _draw_ruler(page, y=y0 + board_h + mm_to_px(25.0))
    _draw_text(page, dictionary)
    return page


def _draw_ruler(page: np.ndarray, *, y: int) -> None:
    """A 100 mm line with end ticks. The card's own proof it printed at 1:1."""
    length = mm_to_px(RULER_MM)
    x0 = (page.shape[1] - length) // 2
    thickness = mm_to_px(0.5)
    cv2.line(page, (x0, y), (x0 + length, y), 0, thickness)
    for x in (x0, x0 + length):
        cv2.line(page, (x, y - mm_to_px(3)), (x, y + mm_to_px(3)), 0, thickness)
    # Millimetre ticks, so a mis-scaled print is visible without a rule at all.
    for step in range(0, int(RULER_MM) + 1, 10):
        x = x0 + mm_to_px(step)
        cv2.line(page, (x, y), (x, y + mm_to_px(2)), 0, max(1, thickness // 2))


def _draw_text(page: np.ndarray, dictionary: str) -> None:
    lines = [
        "AKSHAR inspection card",
        f"ChArUco {SQUARES_X}x{SQUARES_Y}  -  square {SQUARE_MM:.0f} mm, marker {MARKER_MM:.0f} mm  -  {dictionary}",
        "",
        "PRINT AT 100%. Do not use 'fit to page' or 'shrink to fit'.",
        f"The line below must measure exactly {RULER_MM:.0f} mm. If it does not,",
        "the print is scaled and every measurement made against it is wrong.",
    ]
    scale = page.shape[1] / 2800.0
    for index, line in enumerate(lines):
        cv2.putText(
            page,
            line,
            (mm_to_px(20.0), mm_to_px(15.0) + int(index * 26 * scale)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.85 * scale,
            0,
            max(1, int(2 * scale)),
            cv2.LINE_AA,
        )

    footer = [
        "Lay this sheet FLAT, in the SAME plane as the packet, both fully in frame.",
        "Shoot at full camera resolution. Transfer by cable, Drive or USB -",
        "a messaging app re-compresses the photo and the measurement is lost.",
    ]
    base = page.shape[0] - mm_to_px(45.0)
    for index, line in enumerate(footer):
        cv2.putText(
            page,
            line,
            (mm_to_px(20.0), base + int(index * 26 * scale)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8 * scale,
            0,
            max(1, int(2 * scale)),
            cv2.LINE_AA,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dictionary", default=DEFAULT_DICTIONARY)
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR / "akshar_card_A4.png")
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    page = render(args.dictionary)
    cv2.imwrite(str(args.out), page)

    print(f"wrote {args.out}  ({page.shape[1]}x{page.shape[0]} px at {DPI} dpi)")
    print(f"square {SQUARE_MM:.0f} mm, marker {MARKER_MM:.0f} mm "
          f"(= vision.scale.tier_a.MARKER_EDGE_MM, the length the code measures)")
    print(f"check the printed ruler line measures {RULER_MM:.0f} mm before shooting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
