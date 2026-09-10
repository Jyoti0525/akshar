"""A worked example of one U1 frame. AKSHAR.md sections 8b and 18b.

    python scripts/make_u1_example.py
    -> data/marker_card/u1_example_shot.png       what the photo should look like
    -> data/marker_card/u1_example_annotated.png  the same, with what to measure
    -> data/marker_card/u1_ground_truth.csv       the sheet to fill in

**This exists because the instruction "measure the letter height using the card"
is wrong, and I wrote it.** There are *two* measurements in a U1 frame and they
never touch each other:

    the CARD    ->  the computer converts pixels to millimetres      (automatic)
    your RULER  ->  the truth we score that conversion against       (by hand)

Nobody measures the MRP *through* the card. The ruler goes on the packet, on one
printed digit, exactly as it would if no card existed. The card sits beside the
packet so that the *software* can work out how many millimetres a pixel is worth
— which it otherwise cannot know, because a packet held close and a packet held
far look identical in a photograph.

Then the two numbers are compared. That comparison is U1, the day-7 go/no-go:
mean absolute error ≤ 0.15 mm and p95 ≤ 0.25 mm across 40 frames.

**The scene below is built in millimetres, not pixels**, so the example is not a
drawing of a measurement — it is one. `MRP_CAP_MM` is the true printed height of
the digits, the frame is rendered at a known scale, and the script finishes by
running `vision.scale.tier_a` on its own output and printing what AKSHAR
recovered. If those two numbers ever drift apart, this script fails loudly
rather than producing a reassuring picture.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.make_marker_card import SQUARE_MM, SQUARES_X, SQUARES_Y, build_board  # noqa: E402
from vision.scale import tier_a  # noqa: E402

OUT_DIR = Path("data/marker_card")

PX_PER_MM = 12.0
"""Render scale. A 260 mm scene at 12 px/mm is a ~3120 px frame — about what a
phone actually produces, and deliberately *not* generous: at this scale a 1.8 mm
digit is 22 pixels tall, which is the real difficulty of this task rather than a
comfortable illustration of it."""

SCENE_W_MM, SCENE_H_MM = 305.0, 200.0
"""The framed area of the table, in millimetres. Sized so the card and the
packet sit fully side by side with neither overlapping the other: an earlier
version let the packet cover two of the ten markers, which ChArUco tolerates
perfectly well and which is exactly the wrong thing to show in a guide."""

PACKET_W_MM, PACKET_H_MM = 95.0, 135.0
PACKET_ORIGIN_MM = (196.0, 32.0)

CARD_ORIGIN_MM = (14.0, 32.0)

MRP_CAP_MM = 1.8
"""The true cap height of the MRP digits in this example, in millimetres.

Chosen just above Rule 7(2) Table I's 1 mm floor for a ≤200 g pack, because that
is where the interesting cases live: a 1.8 mm declaration passes, a 0.9 mm one
does not, and the whole reason U1 needs a ruler is that our error has to be small
enough to tell those apart honestly."""

NET_CAP_MM = 2.6
BRAND_CAP_MM = 9.0

INK = (28, 26, 24)
TABLE = (108, 104, 100)


def mm(value: float) -> int:
    return round(value * PX_PER_MM)


# ---------------------------------------------------------------------------
# The scene
# ---------------------------------------------------------------------------


def _put(image, text, *, origin_mm, cap_mm, colour=INK, thickness=2):
    """Draw text whose cap height is `cap_mm` millimetres in this scene.

    Returns the digit box in pixels, so the annotation pass can bracket exactly
    the height the ruler is being asked to measure — rather than a box drawn by
    eye near it, which would teach the wrong thing.
    """
    font = cv2.FONT_HERSHEY_SIMPLEX
    (_, unit), _ = cv2.getTextSize("0", font, 1.0, thickness)
    scale = mm(cap_mm) / unit
    (w, h), _ = cv2.getTextSize(text, font, scale, thickness)
    x, y = mm(origin_mm[0]), mm(origin_mm[1])
    cv2.putText(image, text, (x, y), font, scale, colour, thickness, cv2.LINE_AA)
    return (x, y - h, w, h)


def build_scene() -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """The table, the card and the packet. Returns the scene and the MRP box."""
    scene = np.full((mm(SCENE_H_MM), mm(SCENE_W_MM), 3), TABLE, dtype=np.uint8)

    # -- the card, at its true printed size ---------------------------------
    board = build_board()
    card_w, card_h = mm(SQUARES_X * SQUARE_MM), mm(SQUARES_Y * SQUARE_MM)
    card = cv2.cvtColor(board.generateImage((card_w, card_h)), cv2.COLOR_GRAY2BGR)
    cx, cy = mm(CARD_ORIGIN_MM[0]), mm(CARD_ORIGIN_MM[1])
    # The white quiet zone around the board is not decoration: ArUco's adaptive
    # threshold needs it, and a board trimmed to its own edge is undetectable
    # while looking perfectly fine to a person.
    quiet = mm(6.0)
    scene[cy - quiet : cy + card_h + quiet, cx - quiet : cx + card_w + quiet] = 255
    scene[cy : cy + card_h, cx : cx + card_w] = card

    # -- the packet ---------------------------------------------------------
    px, py = mm(PACKET_ORIGIN_MM[0]), mm(PACKET_ORIGIN_MM[1])
    pw, ph = mm(PACKET_W_MM), mm(PACKET_H_MM)
    cv2.rectangle(scene, (px, py), (px + pw, py + ph), (242, 240, 236), -1)
    cv2.rectangle(scene, (px, py), (px + pw, py + ph), (196, 192, 186), 3)

    left = PACKET_ORIGIN_MM[0] + 8.0
    _put(scene, "SAMPLE", origin_mm=(left, PACKET_ORIGIN_MM[1] + 26.0), cap_mm=BRAND_CAP_MM)
    _put(scene, "BISCUITS", origin_mm=(left, PACKET_ORIGIN_MM[1] + 40.0), cap_mm=BRAND_CAP_MM * 0.5)
    _put(scene, "NET WT 100 g", origin_mm=(left, PACKET_ORIGIN_MM[1] + 96.0), cap_mm=NET_CAP_MM)
    mrp_box = _put(
        scene,
        "MRP Rs. 45.00",
        origin_mm=(left, PACKET_ORIGIN_MM[1] + 108.0),
        cap_mm=MRP_CAP_MM,
        thickness=1,
    )
    _put(
        scene,
        "(incl. of all taxes)",
        origin_mm=(left, PACKET_ORIGIN_MM[1] + 114.0),
        cap_mm=MRP_CAP_MM * 0.8,
        thickness=1,
    )
    return scene, mrp_box


# ---------------------------------------------------------------------------
# The annotation
# ---------------------------------------------------------------------------


def _label(image, text, origin, *, colour, scale=0.9, thickness=2, bg=(255, 255, 255)):
    (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    x, y = origin
    cv2.rectangle(image, (x - 8, y - h - 10), (x + w + 8, y + 10), bg, -1)
    cv2.rectangle(image, (x - 8, y - h - 10), (x + w + 8, y + 10), colour, 2)
    cv2.putText(
        image, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, colour, thickness, cv2.LINE_AA
    )
    return (x - 8, y - h - 10, w + 16, h + 20)


def annotate(scene: np.ndarray, mrp_box: tuple[int, int, int, int]) -> np.ndarray:
    """Mark the two measurements and show what a cap height is."""
    blue = (170, 90, 20)
    red = (40, 40, 205)
    out = scene.copy()

    # -- the card: automatic -----------------------------------------------
    card_w, card_h = mm(SQUARES_X * SQUARE_MM), mm(SQUARES_Y * SQUARE_MM)
    cx, cy = mm(CARD_ORIGIN_MM[0]), mm(CARD_ORIGIN_MM[1])
    cv2.rectangle(out, (cx - mm(7), cy - mm(7)), (cx + card_w + mm(7), cy + card_h + mm(7)), blue, 4)
    _label(out, "1. THE CARD - for the computer", (cx - mm(6), cy - mm(11)), colour=blue)
    _label(
        out,
        f"squares are {SQUARE_MM:.0f} mm; software reads them and works out mm-per-pixel",
        (cx - mm(6), cy + card_h + mm(16)),
        colour=blue,
        scale=0.68,
        thickness=1,
    )
    _label(
        out,
        "you never measure anything with this",
        (cx - mm(6), cy + card_h + mm(24)),
        colour=blue,
        scale=0.68,
        thickness=1,
    )

    # -- the packet: by hand ------------------------------------------------
    bx, by, bw, bh = mrp_box
    cv2.rectangle(out, (bx - 6, by - 6), (bx + bw + 6, by + bh + 6), red, 3)

    # The label goes in the empty table BELOW the packet with a leader line up
    # to the box, not floating above it: placed above, it lands squarely on the
    # net-quantity declaration, and a guide whose annotation hides a mandatory
    # declaration is teaching the wrong lesson twice over.
    tip = (bx + bw // 2, by + bh + 8)
    anchor = (bx - mm(6), mm(SCENE_H_MM - 16.0))
    cv2.line(out, tip, (tip[0], anchor[1] - mm(6)), red, 3)
    cv2.line(out, (tip[0], anchor[1] - mm(6)), (anchor[0] + mm(30), anchor[1] - mm(6)), red, 3)
    _label(out, "2. YOUR STEEL RULE - measure a digit here", anchor, colour=red)

    # -- the zoom: what a cap height is ------------------------------------
    pad = mm(2.0)
    crop = scene[max(0, by - pad) : by + bh + pad, max(0, bx - pad) : bx + bw + pad]
    zoom = 7
    big = cv2.resize(crop, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
    cv2.rectangle(big, (0, 0), (big.shape[1] - 1, big.shape[0] - 1), red, 3)

    # The bracket goes in a strip added BESIDE the crop rather than drawn over
    # it. Laid on top it crossed the final digit, which is the one thing in this
    # picture that has to stay legible.
    strip = 340
    framed = np.full((big.shape[0], big.shape[1] + strip, 3), 255, dtype=np.uint8)
    framed[:, : big.shape[1]] = big

    top = pad * zoom
    bottom = (pad + bh) * zoom
    gx = big.shape[1] + 70
    cv2.line(framed, (gx, top), (gx, bottom), red, 3)
    for y in (top, bottom):
        cv2.line(framed, (gx - 24, y), (gx + 24, y), red, 3)
    cv2.putText(
        framed,
        f"{MRP_CAP_MM} mm",
        (gx + 44, (top + bottom) // 2 + 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.95,
        red,
        2,
        cv2.LINE_AA,
    )
    big = framed

    panel_h = big.shape[0] + mm(26)
    panel = np.full((panel_h, out.shape[1], 3), (250, 249, 247), dtype=np.uint8)
    panel[mm(20) : mm(20) + big.shape[0], mm(12) : mm(12) + big.shape[1]] = big
    _label(
        panel,
        f"CAP HEIGHT: baseline to the top of a digit. Not the whole line. Here: {MRP_CAP_MM} mm",
        (mm(12), mm(14)),
        colour=red,
        scale=0.85,
        bg=(250, 249, 247),
    )
    text_x = mm(12) + big.shape[1] + mm(8)
    for index, line in enumerate(
        [
            "Measure ONE character, not the word.",
            "Ignore the tail of a 'g' or 'y'.",
            "Read to 0.1 mm. A magnifier helps.",
            "",
            "Write it down against the filename.",
            "That number is the truth we score",
            "AKSHAR's answer against.",
        ]
    ):
        cv2.putText(
            panel,
            line,
            (text_x, mm(28) + index * 42),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.78,
            INK,
            2,
            cv2.LINE_AA,
        )

    return np.vstack([out, panel])


# ---------------------------------------------------------------------------
# Ground truth sheet
# ---------------------------------------------------------------------------

CSV_HEADER = "filename,product,pack_size,field,character,measured_mm,notes\n"

# TWO rows for ONE packet. Section 16 asks for 40 photographs of 20 SKUs, not 40
# SKUs, and the pairing is the point: the printed digit is the same height in
# both frames, so any disagreement between the two AKSHAR readings is our own
# repeatability — measurable with no ruler involved at all. One photo per packet
# cannot separate our error from the hand holding the rule.
#
# `measured_mm` is therefore the SAME in both rows. You measure the packet once;
# it is the photographs that differ, not the digit.
CSV_EXAMPLE = (
    'u1_example_shot.png,SAMPLE BISCUITS,100 g,mrp,"4",1.8,'
    "shot 1 - straight on; replace these two rows with your own\n"
    'u1_example_shot.png,SAMPLE BISCUITS,100 g,mrp,"4",1.8,'
    "shot 2 - same packet and same digit, camera moved\n"
)



def write_template(path: Path) -> None:
    """The sheet the 40 readings go on.

    One row per photograph, and `filename` is the join key — a ruler reading
    that cannot be tied to a specific frame is not ground truth, it is a number.
    `character` is recorded because two digits in one line can differ by a tenth
    of a millimetre, and at a 0.15 mm error budget that is most of it.
    """
    path.write_text(CSV_HEADER + CSV_EXAMPLE, encoding="utf-8")


# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    scene, mrp_box = build_scene()
    shot_path = args.out_dir / "u1_example_shot.png"
    cv2.imwrite(str(shot_path), scene)
    cv2.imwrite(str(args.out_dir / "u1_example_annotated.png"), annotate(scene, mrp_box))
    write_template(args.out_dir / "u1_ground_truth.csv")

    print(f"wrote {shot_path}  ({scene.shape[1]}x{scene.shape[0]} px)")
    print(f"wrote {args.out_dir / 'u1_example_annotated.png'}")
    print(f"wrote {args.out_dir / 'u1_ground_truth.csv'}")
    print()

    # -- the point of the whole exercise, on its own output ------------------
    estimate = tier_a.estimate(scene)
    print(f"ruler reading (the truth)      : {MRP_CAP_MM:.2f} mm")
    if estimate is None:
        print("AKSHAR                        : card not found - this frame is unusable")
        return 1

    # `mrp_box` is in raw scene pixels; tier A reports mm-per-pixel in the space
    # it rectified to, so the comparison is only honest if we ask it for the
    # same space. This scene is drawn flat, so the two coincide.
    recovered = mrp_box[3] * estimate.mm_per_px
    error = abs(recovered - MRP_CAP_MM)
    print(f"AKSHAR, via the card          : {recovered:.2f} mm")
    print(f"error                         : {error:.3f} mm   (U1 wants <= 0.15 mm mean)")
    print()
    print(f"scale detail: {estimate.detail}")

    if error > 0.15:
        print()
        print("FAILED: the example does not meet its own target; do not ship this as a guide")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
