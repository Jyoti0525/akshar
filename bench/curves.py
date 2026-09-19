"""The three named plots, computed from one pass over the 38 labelled panels.

    confusion matrix        per field, over 38 images: TP / FP / FN / TN
    precision-recall curve  by sweeping the classifier's own confidence
    Bland-Altman            agreement between our millimetres and the steel rule

---------------------------------------------------------------------------
WHY THESE THREE AND NOT A SINGLE ACCURACY
---------------------------------------------------------------------------
Section 19: *"Measure per class, never in aggregate. A single accuracy number
hides the failure that matters."* Each plot here answers a question the others
cannot.

**The confusion matrix** is the only one that shows the true negatives — the
38x11 grid of field-and-image pairs where a declaration is absent from the pack
and we correctly said nothing. Precision and recall both ignore that cell
entirely, and it is two thirds of the grid.

**The precision-recall curve** exists because `field_confidence` travels on
every declaration and nothing downstream has ever used it as a dial. The curve
says what the dial is worth: whether precision could be traded for recall, or
whether the misses are simply not there to be recovered at any threshold.

**Bland-Altman** is the plot for agreement between two ways of measuring the
same physical thing, which is exactly what `mm we report` versus `mm the ruler
says` is. A correlation or an R-squared would flatter it; Bland-Altman shows
the bias and the limits of agreement in millimetres, the unit the rule is
written in.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench.declaration_blocks import (  # noqa: E402
    DATA,
    DEFAULT_PACK_HEIGHT_MM,
    GROUND_TRUTH,
)
from vision.pipeline import scan  # noqa: E402

SEALED = ROOT / "data" / "test_split"

FIELDS = [
    "mrp", "net_quantity", "mfg_date", "expiry_date", "batch",
    "manufacturer", "packer", "importer", "generic_name",
    "consumer_care", "country_of_origin",
]

THRESHOLDS = [round(x / 20, 2) for x in range(0, 21)]


def imread(path: Path) -> np.ndarray | None:
    buf = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR) if buf.size else None


# ---------------------------------------------------------------------------
# One pass over the panels
# ---------------------------------------------------------------------------


def read_panels() -> list[dict[str, Any]]:
    truth = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []

    for entry in truth["images"]:
        image = imread(DATA / "images" / entry["image"])
        if image is None:
            continue
        outcome = scan(image, quality_gate=False, operator_height_mm=DEFAULT_PACK_HEIGHT_MM)
        ds = outcome.declarations
        found: list[tuple[str, float]] = []
        if ds is not None:
            found = [(d.field, float(d.field_confidence)) for d in ds.declarations]
        out.append(
            {
                "image": entry["image"],
                "expected": sorted(entry.get("fields") or {}),
                "blank": sorted(entry.get("blank_labels") or []),
                "found": found,
            }
        )
        print(f"  read {entry['image']:28} {len(found):3} declarations", flush=True)
    return out


# ---------------------------------------------------------------------------
# 1. Confusion matrix, per field
# ---------------------------------------------------------------------------


def confusion(panels: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """For each field, across all 38 images: TP, FP, FN, TN.

    One image contributes one cell per field, so every field sees all 38 —
    including the images where the pack does not carry it, which is where the
    true negatives come from. `blank_labels` are excluded from the field they
    name on that image: the label IS on the pack with nothing after it, so
    neither claiming it nor staying silent is wrong.
    """
    grid = {f: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for f in FIELDS}
    for panel in panels:
        expected = set(panel["expected"])
        blank = set(panel["blank"])
        found = {f for f, _ in panel["found"]}
        for field in FIELDS:
            if field in blank:
                continue
            if field in expected and field in found:
                grid[field]["tp"] += 1
            elif field in expected:
                grid[field]["fn"] += 1
            elif field in found:
                grid[field]["fp"] += 1
            else:
                grid[field]["tn"] += 1
    return grid


# ---------------------------------------------------------------------------
# 2. Precision-recall curve
# ---------------------------------------------------------------------------


def pr_curve(panels: list[dict[str, Any]]) -> list[dict[str, float]]:
    """Sweep the confidence a declaration must carry before it is believed."""
    curve: list[dict[str, float]] = []
    for cut in THRESHOLDS:
        tp = fp = fn = 0
        for panel in panels:
            expected = set(panel["expected"])
            blank = set(panel["blank"])
            found = {f for f, c in panel["found"] if c >= cut and f in FIELDS}
            tp += len(expected & found)
            fn += len(expected - found)
            fp += len(found - expected - blank)
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        curve.append(
            {
                "threshold": cut,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                "tp": tp, "fp": fp, "fn": fn,
            }
        )
    return curve


# ---------------------------------------------------------------------------
# 3. Bland-Altman, against the steel rule
# ---------------------------------------------------------------------------


def bland_altman() -> dict[str, Any]:
    """Our millimetres against the ruler's, on the sealed set.

    Read-only. The seal forbids training on, tuning against, or picking a
    threshold from this directory; plotting a result is what it is for.
    """
    rows = list(csv.DictReader((SEALED / "ground_truth.csv").open(encoding="utf-8")))
    points: list[dict[str, Any]] = []

    for row in rows:
        path = SEALED / row["filename"]
        image = imread(path)
        if image is None:
            continue
        outcome = scan(image, quality_gate=False)
        ds = outcome.declarations
        if ds is None:
            continue
        ours = next(
            (
                d.height_mm
                for d in ds.declarations
                if d.field == "mrp" and d.height_mm is not None
            ),
            None,
        )
        if ours is None:
            continue
        truth = float(row["measured_mm"])
        points.append(
            {
                "image": row["filename"],
                "product": row["product"],
                "ruler_mm": truth,
                "ours_mm": round(float(ours), 3),
                "mean_mm": round((truth + float(ours)) / 2, 3),
                "diff_mm": round(float(ours) - truth, 3),
            }
        )
        print(f"  measured {row['filename']:44} ruler {truth:.2f}  ours {ours:.2f}", flush=True)

    diffs = [p["diff_mm"] for p in points]
    if len(diffs) < 2:
        return {"points": points, "n": len(points)}
    bias = statistics.fmean(diffs)
    sd = statistics.stdev(diffs)
    return {
        "points": points,
        "n": len(points),
        "bias_mm": round(bias, 4),
        "sd_mm": round(sd, 4),
        "upper_loa_mm": round(bias + 1.96 * sd, 4),
        "lower_loa_mm": round(bias - 1.96 * sd, 4),
    }


def main() -> None:
    print("reading the 38 labelled panels...")
    panels = read_panels()

    print("\nreading the sealed ruler set...")
    agreement = bland_altman()

    out = {
        "confusion": confusion(panels),
        "pr_curve": pr_curve(panels),
        "bland_altman": agreement,
        "panels": len(panels),
    }
    (ROOT / "bench" / "curves.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

    print("\n" + "=" * 70)
    print("CONFUSION MATRIX — each field over 38 images")
    print("=" * 70)
    print(f"{'field':20} {'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4}   {'precision':>9} {'recall':>7}")
    for field, c in out["confusion"].items():
        p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 0.0
        r = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else 0.0
        print(f"{field:20} {c['tp']:4} {c['fp']:4} {c['fn']:4} {c['tn']:4}   {p:9.3f} {r:7.3f}")

    print("\n" + "=" * 70)
    print("PRECISION-RECALL, sweeping field confidence")
    print("=" * 70)
    print(f"{'cut':>5} {'precision':>10} {'recall':>8} {'F1':>7}   {'TP':>4} {'FP':>4} {'FN':>4}")
    for row in out["pr_curve"]:
        print(
            f"{row['threshold']:5.2f} {row['precision']:10.4f} {row['recall']:8.4f} "
            f"{row['f1']:7.4f}   {row['tp']:4} {row['fp']:4} {row['fn']:4}"
        )

    print("\n" + "=" * 70)
    print("BLAND-ALTMAN — our millimetres against the steel rule")
    print("=" * 70)
    if agreement.get("n", 0) >= 2:
        print(f"  pairs                {agreement['n']}")
        print(f"  bias                 {agreement['bias_mm']:+.3f} mm")
        print(f"  limits of agreement  {agreement['lower_loa_mm']:+.3f} to "
              f"{agreement['upper_loa_mm']:+.3f} mm")
    else:
        print(f"  only {agreement.get('n', 0)} pairs; not enough to plot")

    print("\nwritten to bench/curves.json")


if __name__ == "__main__":
    main()
