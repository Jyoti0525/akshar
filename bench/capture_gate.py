"""Does the capture gate reject the photographs a person cannot read?

---------------------------------------------------------------------------
WHAT THIS ANSWERS AND WHAT IT CANNOT
---------------------------------------------------------------------------
`bench/declaration_blocks.py` reports the gate's pass rate on 38 usable
photographs, which is its **false-reject** rate and nothing else. Its docstring
says so, and adds that the other half of section 18's bar — *"rejects >=90% of
the deliberately-bad subset"* — cannot be measured because no deliberately-bad
frames have been delivered.

That was half right. No frames were delivered *as* bad ones, but the 469-frame
corpus has always contained a handful that nobody could read: an empty frame,
and eight destroyed by motion blur. They were never labelled, so they were
never scored against anything.

`data/corpus/negatives/labels.json` is that label, read by eye at full size.
This script scores the gate against it.

---------------------------------------------------------------------------
WHY THE LABEL IS NOT CIRCULAR
---------------------------------------------------------------------------
The obvious objection: the candidates came from `audit.json`, which ranks
frames by variance-of-Laplacian, and the gate is also a sharpness test — so is
this just the audit grading the gate against itself?

No, and the labelling was done the way it was in order to answer that. The
audit only nominated 62 frames to *look at*. Every one was then judged on what
the picture shows, and **53 of the 62 were rejected as negatives** because a
person can read them perfectly well. Six frames whose blur scores fall between
those of accepted negatives (12.1 to 19.0, against negatives at 13.3, 30.8,
45.2 and 48.1) were looked at at full size and kept as positives, because their
branding is legible. The label and the statistic disagree on those six by
construction, which is what makes the label evidence.

---------------------------------------------------------------------------
NINE IS NOT ENOUGH AND THE NUMBER SAYS SO
---------------------------------------------------------------------------
A recall measured on nine frames is quoted here with the count beside it, never
alone. Section 18 wants a deliberately-bad subset; nine accidental frames out
of 469 are not one, and the honest use of this script today is as a floor — the
gate at least does not sail past an empty frame — rather than as the bar being
met.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus"
PANELS = ROOT / "data" / "declaration_blocks"

sys.path.insert(0, str(ROOT))

from vision.quality import assess  # noqa: E402

SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def imread(path: Path) -> np.ndarray | None:
    """Windows-safe: the corpus filenames carry spaces and brackets."""
    if not path.is_file() or path.suffix.lower() not in SUFFIXES:
        return None
    buf = np.fromfile(str(path), dtype=np.uint8)
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def main() -> None:
    labels = json.loads((CORPUS / "negatives" / "labels.json").read_text(encoding="utf-8"))
    negatives = labels["negatives"]

    print("=" * 78)
    print("NEGATIVES — frames a person cannot read. The gate should reject every one.")
    print("=" * 78)
    print(f"{'frame':46} {'blur':>6} {'glare':>6} {'expo':>6}  verdict")

    rejected = 0
    for row in negatives:
        image = imread(CORPUS / "images" / row["image"])
        if image is None:
            print(f"  MISSING {row['image']}")
            continue
        quality = assess(image)
        rejected += not quality.usable
        name = row["image"]
        name = name if len(name) <= 44 else name[:41] + "..."
        print(
            f"{name:46} {quality.blur_score:6.3f} {quality.glare_ratio:6.3f} "
            f"{quality.exposure_score:6.3f}  "
            f"{'REJECTED (right)' if not quality.usable else 'passed  (MISS)'}"
            f"   {row['kind']}"
        )

    print()
    print("=" * 78)
    print("POSITIVES — 38 usable declaration panels. The gate should pass every one.")
    print("=" * 78)

    panels = sorted(
        p for p in (PANELS / "images").iterdir()
        if p.is_file() and p.suffix.lower() in SUFFIXES
    )
    passed = 0
    rejected_positives: list[str] = []
    for path in panels:
        image = imread(path)
        if image is None:
            continue
        quality = assess(image)
        if quality.usable:
            passed += 1
        else:
            rejected_positives.append(path.name)

    for name in rejected_positives:
        print(f"  wrongly rejected: {name}")

    n_neg = len(negatives)
    n_pos = len(panels)
    print()
    print("-" * 78)
    print(f"true-reject rate  (on negatives) {rejected}/{n_neg}"
          f"  {rejected / n_neg:.1%}   target >= 90%")
    print(f"pass rate         (on positives) {passed}/{n_pos}"
          f"  {passed / n_pos:.1%}   target >= 98%")
    print("-" * 78)
    print(
        f"The negative set is {n_neg} frames out of {len(list((CORPUS / 'images').iterdir()))} "
        f"in the corpus. Section 18 asks for a deliberately-bad subset and this is not\n"
        f"one; read the true-reject rate as a floor, not as the bar being met."
    )

    out = {
        "negatives": n_neg,
        "negatives_rejected": rejected,
        "true_reject_rate": round(rejected / n_neg, 4),
        "positives": n_pos,
        "positives_passed": passed,
        "pass_rate": round(passed / n_pos, 4),
        "positives_wrongly_rejected": rejected_positives,
    }
    (ROOT / "bench" / "capture_gate.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8"
    )
    print("\nwritten to bench/capture_gate.json")


if __name__ == "__main__":
    main()
