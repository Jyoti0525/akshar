"""Which recognition head actually reads the print? Section 15b's benchmark.

---------------------------------------------------------------------------
THE QUESTION, AND WHY IT NEEDS ITS OWN FILE
---------------------------------------------------------------------------
Section 15b left one decision explicitly open:

    "v5's Devanagari recogniser covers Hindi and Marathi and handles English
     too. Benchmark whether a second English-only head earns its bundle size;
     do not assume it."

`read_accuracy.py --head` can answer it end to end, and that is the number that
matters for shipping. But it is **not** a measurement of the head, because
swapping the head changes three other things at once:

  * `vision/ocr/roi.py` deduplicates its two candidate heads by name. With one
    head serving both scripts the pair collapses and each crop is read once;
    with two distinct heads an unsure crop is read twice and the *more
    confident* reading wins.
  * Confidence is the mean of per-timestep maxima over a head's own character
    table. Those numbers are not comparable across tables. A head with no
    Devanagari in its table does not report low confidence on Devanagari print
    -- it reports high confidence on whichever Latin classes it does have.
  * `second_pass.py` re-reads crops below a confidence threshold, so a change
    in the confidence *distribution* changes which crops are read twice.

So an end-to-end regression can mean the head is worse, or it can mean the head
is fine and the routing around it now picks wrong. This file holds the routing
still: every crop from every frame goes through **one** head, and the text is
scored against the same ground truth. Nothing here chooses a head, classifies a
field or gates on confidence.

---------------------------------------------------------------------------
HOW IT IS SCORED
---------------------------------------------------------------------------
The same infix edit distance `read_accuracy.py` uses -- the minimum distance
between the printed string and any substring of everything the head read. See
that module for why a free start and a free end are the right measure when the
target is one declaration inside a whole panel of text.

Two figures per head, and the second is the one to read:

  * **weighted CER** over every printed string, which answers "how much of the
    panel did this head read correctly".
  * **CER split by the script of the printed string.** A Latin-only head can
    only help Latin print, and it can only hurt Devanagari print. Reporting one
    combined number hides exactly the trade the decision turns on.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench.declaration_blocks import DATA, GROUND_TRUTH  # noqa: E402
from bench.read_accuracy import (  # noqa: E402
    HEADS,
    MIN_CHARS,
    band,
    infix_distance,
    normalise,
    script_of,
    use_head,
)
from vision.ocr import recognise  # noqa: E402
from vision.ocr.detect_text import propose_regions  # noqa: E402

MIN_CROP_SIDE = 3
"""Below this a crop has no glyph in it; `propose_regions` can return slivers at
the edge of a pack and passing them to the recogniser only costs a run."""


def imread(path: Path) -> np.ndarray | None:
    buf = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR) if buf.size else None


def crops_for(image: np.ndarray) -> list[np.ndarray]:
    """Every detected region as a crop, in detection order.

    Deliberately *every* region, with no ranking and no budget. The point is to
    give each head exactly the same pixels; a selection step would let the two
    runs diverge before either head had read anything.
    """
    regions, _scale, _model = propose_regions(image)
    out: list[np.ndarray] = []
    for region in regions:
        box = region.box
        x0, y0 = max(0, int(box.x)), max(0, int(box.y))
        crop = image[y0 : y0 + int(box.h), x0 : x0 + int(box.w)]
        if crop.size and min(crop.shape[:2]) >= MIN_CROP_SIDE:
            out.append(crop)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--heads",
        nargs="+",
        default=sorted(HEADS),
        choices=sorted(HEADS),
        help="which heads to compare (default: all of them)",
    )
    args = parser.parse_args()

    truth = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))

    # Detect once. Detection is the same model in every configuration, so
    # re-running it per head would only add a way for the comparison to drift.
    print("detecting regions ...", flush=True)
    pixels: dict[str, list[np.ndarray]] = {}
    for entry in truth["images"]:
        image = imread(DATA / "images" / entry["image"])
        if image is None:
            continue
        pixels[entry["image"]] = crops_for(image)
    print(f"  {len(pixels)} frames, {sum(len(c) for c in pixels.values())} crops\n", flush=True)

    wanted: list[tuple[str, str, str, str]] = []  # image, field, printed, script
    for entry in truth["images"]:
        if entry["image"] not in pixels:
            continue
        for field, value in (entry.get("fields") or {}).items():
            for item in value if isinstance(value, list) else [value]:
                if item is None:
                    continue
                printed = normalise(str(item))
                if len(printed) >= MIN_CHARS:
                    wanted.append((entry["image"], field, printed, script_of(str(item))))

    report: dict[str, dict] = {}

    for head in args.heads:
        use_head(head)
        started = time.perf_counter()

        read: dict[str, str] = {}
        for name, crops in pixels.items():
            if not crops:
                read[name] = ""
                continue
            # `script` is the *routing key*, and `use_head` has pointed it at
            # the head under test. Every crop goes through that one head --
            # this is the whole point of the file.
            results, _ms = recognise.read_batch(crops, "latin")
            read[name] = normalise(" ".join(found.text for found, _crop, _k in results))

        elapsed = time.perf_counter() - started

        rows = []
        for name, field, printed, script in wanted:
            edits = infix_distance(printed, read[name])
            rows.append(
                {
                    "image": name,
                    "field": field,
                    "script": script,
                    "chars": len(printed),
                    "cer": round(edits / len(printed), 4),
                }
            )

        def weighted(subset: list[dict]) -> float:
            chars = sum(r["chars"] for r in subset)
            return sum(r["cer"] * r["chars"] for r in subset) / chars if chars else float("nan")

        report[head] = {
            "model": HEADS[head][0],
            "weighted_cer": round(weighted(rows), 4),
            "by_script": {
                s: {
                    "n": len([r for r in rows if r["script"] == s]),
                    "chars": sum(r["chars"] for r in rows if r["script"] == s),
                    "weighted_cer": round(weighted([r for r in rows if r["script"] == s]), 4),
                }
                for s in ("latin", "devanagari")
                if any(r["script"] == s for r in rows)
            },
            "bands": {
                b: sum(1 for r in rows if band(r["cer"]) == b)
                for b in ("clean", "usable", "corrupt", "absent")
            },
            "seconds": round(elapsed, 1),
            "rows": rows,
        }
        print(f"  {head:12} done in {elapsed:5.1f} s", flush=True)

    print("\n" + "=" * 78)
    print("RECOGNITION HEAD COMPARISON — one head, every crop, no routing")
    print("=" * 78)
    print(
        f"{'head':12} {'overall':>9} {'latin':>9} {'devanagari':>11} "
        f"{'clean':>6} {'corrupt':>8} {'absent':>7} {'secs':>6}"
    )
    for head, data in report.items():
        by = data["by_script"]
        bands = data["bands"]
        print(
            f"{head:12} {data['weighted_cer']:9.4f} "
            f"{by.get('latin', {}).get('weighted_cer', float('nan')):9.4f} "
            f"{by.get('devanagari', {}).get('weighted_cer', float('nan')):11.4f} "
            f"{bands['clean']:6} {bands['corrupt']:8} {bands['absent']:7} {data['seconds']:6.1f}"
        )

    if len(report) > 1:
        baseline = "devanagari" if "devanagari" in report else args.heads[0]
        base = {(r["image"], r["field"]): r["cer"] for r in report[baseline]["rows"]}
        print(f"\nAgainst `{baseline}`, string by string:")
        for head, data in report.items():
            if head == baseline:
                continue
            deltas = [
                (r["cer"] - base[(r["image"], r["field"])], r)
                for r in data["rows"]
                if (r["image"], r["field"]) in base
            ]
            better = sum(1 for d, _ in deltas if d < -0.01)
            worse = sum(1 for d, _ in deltas if d > 0.01)
            print(f"  {head:12} {better:3} better, {worse:3} worse, "
                  f"{len(deltas) - better - worse:3} unchanged")
            deltas.sort()
            for label, sample in (("worst regressions", deltas[-4:]),):
                print(f"    {label}:")
                for delta, row in reversed(sample):
                    print(f"      {delta:+.3f}  {row['script']:11} {row['field']:16} {row['image'][:26]}")

    out = ROOT / "bench" / "head_compare.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\nwritten to {out.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
