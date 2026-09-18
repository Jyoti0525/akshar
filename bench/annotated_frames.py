"""The pipeline against hand-drawn declaration boxes. AKSHAR.md §16, §18.

    .venv/Scripts/python.exe bench/annotated_frames.py <label-studio-export.json>
    .venv/Scripts/python.exe bench/annotated_frames.py export.json --verbose

---------------------------------------------------------------------------
WHY THIS EXISTS BESIDE `declaration_blocks.py`
---------------------------------------------------------------------------
`bench/declaration_blocks.py` scores 38 hand-labelled panels on **presence**:
did the pipeline find a manufacturer on this pack at all. That is the question
the rules ask, and it is the right headline.

It cannot answer a different question that matters just as much to the people
maintaining this: *is the box in the right place, and is it the right box?* A
pipeline that reports a manufacturer because it read the marketing strapline
scores a presence hit and is wrong about everything else.

This scores a Label Studio export — a person's own boxes, on corpus frames —
and answers that second question.

---------------------------------------------------------------------------
WHY IT DOES NOT USE IoU, WHICH IS WHAT EVERYONE EXPECTS
---------------------------------------------------------------------------
Measured 2026-09-18 on the first 37-frame export: scored at IoU >= 0.5 the
pipeline gets **33.2% recall and 8.1% precision**, which reads like a broken
detector. It is not. The two sides are drawing different things:

    the annotator's boxes are 6.4x the area of the pipeline's
    median pipeline boxes sitting inside one annotator box: 1 (mean 2.3, max 51)

`docs/annotation-guide.md` says *"one box per declaration"*, and a consumer-care
declaration is an address of four printed lines. The pipeline emits **lines**,
because that is what `vision/ocr/lines.py` assembles and what the classifier
reads. One generous box around a four-line address and one tight box around its
first line describe the same declaration and overlap at an IoU of roughly 0.15.
Reporting that as a miss would be measuring a drawing convention.

So the test is **containment**: does the pipeline put a text box *inside* the
region the annotator marked, and does it give it the same name? That is the
question whose answer changes what we would fix.

`--iou` reports the IoU view as well, for anyone who wants to see the
convention gap rather than take this docstring's word for it.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

Box = tuple[float, float, float, float, str]

CONTAINMENT = 0.6
"""Fraction of a pipeline box that must fall inside the annotator's box.

Not 1.0: a tight line box can overhang a hand-drawn edge by a few pixels and
still plainly be the same text. Not 0.5 either, which would let a box half
outside the region count as inside it."""


def _overlap(outer: Box, inner: Box) -> float:
    ox, oy, ow, oh = outer[:4]
    ix, iy, iw, ih = inner[:4]
    x0, y0 = max(ox, ix), max(oy, iy)
    x1, y1 = min(ox + ow, ix + iw), min(oy + oh, iy + ih)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0)


def contains(outer: Box, inner: Box, frac: float = CONTAINMENT) -> bool:
    return _overlap(outer, inner) >= frac * inner[2] * inner[3]


def iou(a: Box, b: Box) -> float:
    inter = _overlap(a, b)
    if inter <= 0:
        return 0.0
    return inter / (a[2] * a[3] + b[2] * b[3] - inter)


def truth_boxes(task: dict) -> list[Box]:
    """The annotator's declaration boxes, in pixels.

    Label Studio stores percentages of the original frame; `original_width` and
    `original_height` travel on every result so the conversion needs no second
    look at the image.
    """
    out: list[Box] = []
    for result in task["annotations"][0]["result"]:
        value = (result or {}).get("value") or {}
        if result.get("from_name") != "declarations" or "rectanglelabels" not in value:
            continue
        width, height = result["original_width"], result["original_height"]
        out.append(
            (
                value["x"] * width / 100,
                value["y"] * height / 100,
                value["width"] * width / 100,
                value["height"] * height / 100,
                value["rectanglelabels"][0],
            )
        )
    return out


def image_path(task: dict) -> Path:
    """`/data/local-files/?d=corpus/originals/IMG_0639.JPG` -> a real path."""
    raw = task["data"]["image"]
    if "?d=" in raw:
        raw = raw.split("?d=", 1)[1]
    return ROOT / "data" / unquote(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score the pipeline against hand-drawn boxes.")
    parser.add_argument("export", type=Path, help="Label Studio JSON export (with annotations)")
    parser.add_argument("--iou", action="store_true", help="also report the IoU view")
    parser.add_argument("--verbose", action="store_true", help="name every missed box")
    args = parser.parse_args(argv)

    import cv2

    from vision.pipeline import scan

    tasks = json.loads(args.export.read_text(encoding="utf-8"))
    tasks = [t for t in tasks if t.get("annotations") and t["annotations"][0].get("result")]
    if not tasks:
        print("No completed annotations in that export.")
        return 1

    found = missed = agreed = 0
    per_field: collections.Counter[str] = collections.Counter()
    per_field_found: collections.Counter[str] = collections.Counter()
    per_field_named: collections.Counter[str] = collections.Counter()
    confusions: collections.Counter[tuple[str, str]] = collections.Counter()
    misses: list[str] = []
    iou_hits = iou_truth = iou_pred = 0
    frames = 0

    for task in tasks:
        path = image_path(task)
        image = cv2.imread(str(path))
        if image is None:
            print(f"  ! unreadable: {path}")
            continue
        truth = truth_boxes(task)
        if not truth:
            continue
        frames += 1

        outcome = scan(image, quality_gate=False, online=False)
        declarations = outcome.declarations
        predicted: list[Box] = (
            [(d.box.x, d.box.y, d.box.w, d.box.h, d.field) for d in declarations.declarations]
            if declarations
            else []
        )

        for box in truth:
            per_field[box[4]] += 1
            hits = [p for p in predicted if contains(box, p)]
            if not hits:
                missed += 1
                misses.append(f"{path.name}: {box[4]}")
                continue
            found += 1
            per_field_found[box[4]] += 1
            names = {p[4] for p in hits}
            if box[4] in names:
                agreed += 1
                per_field_named[box[4]] += 1
            else:
                confusions[(box[4], sorted(names)[0])] += 1

        if args.iou:
            iou_truth += len(truth)
            iou_pred += len(predicted)
            used: set[int] = set()
            for box in truth:
                best, index = 0.0, -1
                for i, p in enumerate(predicted):
                    if i in used:
                        continue
                    score = iou(box, p)
                    if score > best:
                        best, index = score, i
                if best >= 0.5:
                    iou_hits += 1
                    used.add(index)

    if not found and not missed:
        print("No declaration boxes in that export.")
        return 1

    total = found + missed
    print(f"\n{frames} annotated frames, {total} hand-drawn declaration boxes\n")
    print(f"  pipeline put text inside the box : {found}/{total} = {found / total:.1%}")
    print(f"  ...and gave it the same name     : {agreed}/{found} = {agreed / found:.1%}")
    print(f"  end to end                       : {agreed}/{total} = {agreed / total:.1%}")

    # The number above flatters us and must not be quoted on its own. Most boxes
    # on a label are `other` -- printed matter that is not a declaration -- and
    # both sides agreeing on `other` is agreement about nothing anyone is going
    # to be prosecuted over. What the rules act on is the named declarations, so
    # they get their own line.
    named_total = sum(n for f, n in per_field.items() if f != "other")
    named_right = sum(n for f, n in per_field_named.items() if f != "other")
    if named_total:
        print(
            f"\n  EXCLUDING `other`, which is most of the label and most of the\n"
            f"  agreement: {named_right}/{named_total} = {named_right / named_total:.1%} "
            f"of your named declarations were named the same way."
        )

    print("\n  field                found    named")
    print("  " + "-" * 38)
    for field, n in per_field.most_common():
        print(
            f"  {field:<20}{per_field_found[field]:>3}/{n:<4}{per_field_named[field]:>4}/{n:<4}"
        )

    if confusions:
        print("\n  where the names disagree (annotator -> pipeline):")
        for (mine, theirs), n in confusions.most_common(8):
            print(f"    {mine:<18} -> {theirs:<18} x{n}")

    if args.iou:
        print(
            f"\n  IoU>=0.5 view, for the convention gap: "
            f"recall {iou_hits}/{iou_truth} = {iou_hits / iou_truth:.1%}, "
            f"precision {iou_hits}/{iou_pred} = {iou_hits / iou_pred if iou_pred else 0:.1%}"
        )
        print("  See this module's docstring before quoting those two anywhere.")

    if args.verbose and misses:
        print(f"\n  missed ({len(misses)}):")
        for line in misses:
            print(f"    {line}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
