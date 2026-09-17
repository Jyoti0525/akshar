"""What the pipeline reads off 38 hand-labelled declaration panels. AKSHAR.md §18.

    .venv/Scripts/python.exe bench/declaration_blocks.py
    .venv/Scripts/python.exe bench/declaration_blocks.py --only parleg.jpg --verbose

---------------------------------------------------------------------------
WHY THIS SET AND NOT THE CORPUS
---------------------------------------------------------------------------
The 468-frame corpus is unlabelled. Everything measured against it so far has
been measured against *itself* — how many regions the detector proposes, how
many declarations the classifier names, how those counts move when a parameter
changes. Those are useful numbers and none of them is an accuracy: a frame where
we name four declarations may be a frame that carries six, and nothing in the
corpus can say which.

These 38 can. Each one has been read by a human, panel by panel, and what is
printed on it written down in `data/declaration_blocks/ground_truth.json`. That
turns every count in this file into a comparison against a known answer, which
is the difference between coverage and accuracy, and it is the first time
§18's MRP bar can be reported as a real F1 rather than as an aspiration.

---------------------------------------------------------------------------
WHAT THE NUMBERS HERE DO AND DO NOT MEAN
---------------------------------------------------------------------------
**The framing figure is a recall and nothing else.** All 38 frames show a
declaration panel, by construction — that is what was asked for and what was
delivered. So this set can say how often `assess_framing` correctly reports a
panel that is there, and it cannot say anything at all about how often it
reports one that is not. Precision on that gate needs front-of-pack negatives,
which live in the corpus and are not labelled. The number is printed as
`framing recall` and never as an accuracy, and a false-positive rate must not be
inferred from it.

**Presence is scored against the frame, not against the product.** A pack
declaring a manufacturer on a face this photograph does not show counts as
absent, because absent is what it is from where the extractor is standing. This
makes the set harder than a product-level label set and it is the honest
comparison: the pipeline is given one photograph.

**Two annotations are excluded from scoring, in opposite directions.**
`blank_labels` — an empty `Batch No.`, an empty `Mfg & Consumer Cared By` — are
declarations the *package* is missing. Counting a non-extraction there as a miss
would penalise the pipeline for being right. And a field annotated `null` is
printed but unreadable, or is a cross-reference such as `See on Crimp`; it
counts towards presence, where the label really is on the pack, but is skipped
in the value comparison, where there is no value to compare against.

**Value scoring is containment, not equality.** The annotation records the
numeral as printed (`342-00`, `199`, `10.00`); the extractor returns the line it
read (`Maximum Retail Price (Incl. of all taxes) Rs. 342-00`). Requiring string
equality would measure line segmentation rather than reading. Digits are
compared after stripping everything that is not a digit, so `Rs.342-00`,
`342.00` and `₹ 342-00` are one answer and `348.00` is not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import cv2

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from contracts import NON_STATUTORY_FIELDS, DeclarationSet, FieldName  # noqa: E402
from vision.pipeline import scan  # noqa: E402

DATA = ROOT / "data" / "declaration_blocks"
IMAGES = DATA / "images"
GROUND_TRUTH = DATA / "ground_truth.json"
MANIFEST = DATA / "manifest.json"
REPORT = ROOT / "bench" / "declaration_blocks.json"

MANDATORY: tuple[FieldName, ...] = (
    "generic_name",
    "net_quantity",
    "mrp",
    "mfg_date",
    "manufacturer",
    "consumer_care",
)
"""Rule 6(1)'s six as `vision.quality.framing` counts them.

Repeated from there rather than imported, for the reason that module gives:
`vision/` may not import `rules/`, and a bench that reached across the wall to
borrow a definition would be the first thing to break it."""


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def as_list(value: Any) -> list[str | None]:
    if isinstance(value, list):
        return list(value)
    return [value]


# ---------------------------------------------------------------------------
# Scoring one image
# ---------------------------------------------------------------------------


def score_presence(
    truth: dict[str, Any], found: set[str], blank: set[str]
) -> tuple[set[str], set[str], set[str]]:
    """Returns (hit, missed, spurious) as sets of field names.

    `blank` is subtracted from `spurious` rather than from `found`. A pack whose
    `Batch No.` line is printed empty genuinely has a batch label on it, and an
    extractor that proposes `batch` from that line has read the pack correctly;
    what it must not do is invent a *value*. Counting it as a false positive
    would push the pipeline towards suppressing a label it can see, which is the
    opposite of what an enforcement tool should do.
    """
    expected = set(truth)
    hit = expected & found
    return hit, expected - found, found - expected - blank


def score_values(truth: dict[str, Any], declarations: list[Any]) -> dict[str, dict[str, Any]]:
    """Numeral containment, per field, for the fields whose values are numerals.

    Only `mrp`, `net_quantity`, `mfg_date`, `expiry_date` and `batch` are
    compared. An address is not scored: `manufacturer` is forty words that the
    detector splits across six regions in an order that depends on the layout,
    and any string comparison over that measures line segmentation. Whether the
    address was *found* is the presence score above, which is the question the
    rules actually ask of it.
    """
    scored: dict[str, dict[str, Any]] = {}
    for field in ("mrp", "net_quantity", "mfg_date", "expiry_date", "batch"):
        if field not in truth:
            continue
        wanted = [v for v in as_list(truth[field]) if v is not None]
        if not wanted:
            continue  # printed but unreadable, or a cross-reference: no value to match
        read = [d.text for d in declarations if d.field == field]
        blob = digits("".join(read))
        matched = [w for w in wanted if digits(w) and digits(w) in blob]
        scored[field] = {
            "wanted": wanted,
            "matched": matched,
            "all": len(matched) == len(wanted),
            "any": bool(matched),
            "read": read,
        }
    return scored


def run_one(path: Path, entry: dict[str, Any]) -> dict[str, Any]:
    image = cv2.imread(str(path))
    if image is None:
        return {"image": entry["image"], "error": "cannot decode"}

    started = time.perf_counter()
    outcome = scan(image, quality_gate=False)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    truth: dict[str, Any] = entry["fields"]
    blank = set(entry.get("blank_labels", []))

    declarations: DeclarationSet | None = outcome.declarations
    found_all = list(declarations.declarations) if declarations else []
    # Subtract every name no rule asks for. The ground truth records statutory
    # declarations and nothing else, so counting `nutrition` or `barcode` as an
    # emitted field would score naming the nutrition table as inventing a
    # declaration -- precision fell 0.98 -> 0.75 on identical extraction the day
    # those names were added.
    found = {d.field for d in found_all} - NON_STATUTORY_FIELDS

    hit, missed, spurious = score_presence(truth, found, blank)
    quality = outcome.quality
    framing = outcome.framing

    return {
        "image": entry["image"],
        "product": entry["product"],
        "exit_path": outcome.exit_path,
        "tier": outcome.degradation.tier,
        "ms": round(elapsed_ms, 1),
        "usable": None if quality is None else quality.usable,
        "quality_faults": [] if quality is None else list(quality.faults),
        "shows_declarations": None if framing is None else framing.shows_declarations,
        "framing_fault": None if framing is None else framing.fault,
        "text_regions": None if framing is None else framing.text_regions,
        "coverage": None if declarations is None else round(declarations.coverage, 4),
        "expected": sorted(truth),
        "found": sorted(found),
        "hit": sorted(hit),
        "missed": sorted(missed),
        "spurious": sorted(spurious),
        "mandatory_expected": sorted(set(truth) & set(MANDATORY)),
        "mandatory_hit": sorted(hit & set(MANDATORY)),
        "values": score_values(truth, found_all),
        "blank_labels": sorted(blank),
    }


# ---------------------------------------------------------------------------
# Aggregating
# ---------------------------------------------------------------------------


def prf(hit: int, missed: int, spurious: int) -> dict[str, float]:
    recall = hit / (hit + missed) if hit + missed else 0.0
    precision = hit / (hit + spurious) if hit + spurious else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "support": hit + missed,
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    read = [r for r in rows if "error" not in r]

    per_field_hit: Counter[str] = Counter()
    per_field_missed: Counter[str] = Counter()
    per_field_spurious: Counter[str] = Counter()
    for row in read:
        per_field_hit.update(row["hit"])
        per_field_missed.update(row["missed"])
        per_field_spurious.update(row["spurious"])

    fields = sorted(set(per_field_hit) | set(per_field_missed) | set(per_field_spurious))
    per_field = {
        field: prf(per_field_hit[field], per_field_missed[field], per_field_spurious[field])
        for field in fields
    }

    micro = prf(
        sum(per_field_hit.values()),
        sum(per_field_missed.values()),
        sum(per_field_spurious.values()),
    )
    mandatory = prf(
        sum(len(r["mandatory_hit"]) for r in read),
        sum(len(r["mandatory_expected"]) - len(r["mandatory_hit"]) for r in read),
        0,
    )

    value_rows = {
        field: [r["values"][field] for r in read if field in r["values"]]
        for field in ("mrp", "net_quantity", "mfg_date", "expiry_date", "batch")
    }
    values = {
        field: {
            "scored": len(entries),
            "any": sum(1 for e in entries if e["any"]),
            "all": sum(1 for e in entries if e["all"]),
            "accuracy": round(sum(1 for e in entries if e["any"]) / len(entries), 4)
            if entries
            else None,
        }
        for field, entries in value_rows.items()
    }

    framed = [r for r in read if r["shows_declarations"] is not None]
    usable = [r for r in read if r["usable"] is not None]

    return {
        "images": len(rows),
        "read": len(read),
        "capture_quality": {
            "measured": len(usable),
            "usable": sum(1 for r in usable if r["usable"]),
            "pass_rate": round(sum(1 for r in usable if r["usable"]) / len(usable), 4)
            if usable
            else None,
            "note": (
                "All 38 are usable photographs by construction, so this is the "
                "false-reject rate of the M0 gate and nothing else. §18's 'passes "
                ">=98% of usable photos' is the bar it answers to. The complementary "
                "'rejects >=90% of the deliberately-bad subset' cannot be measured "
                "here: no deliberately-bad frames have been delivered."
            ),
        },
        "framing_recall": {
            "measured": len(framed),
            "correct": sum(1 for r in framed if r["shows_declarations"]),
            "recall": round(sum(1 for r in framed if r["shows_declarations"]) / len(framed), 4)
            if framed
            else None,
            "note": (
                "RECALL ONLY. Every frame in this set shows a declaration panel, so "
                "there are no negatives and precision is unmeasurable here. Do not "
                "read a false-positive rate off this number."
            ),
        },
        "presence_micro": micro,
        "presence_per_field": per_field,
        "mandatory_recall": mandatory,
        "values": values,
        "median_ms": round(sorted(r["ms"] for r in read)[len(read) // 2], 1) if read else None,
        "coverage_mean": round(sum(r["coverage"] or 0.0 for r in read) / len(read), 4)
        if read
        else None,
    }


# ---------------------------------------------------------------------------


def verify_bytes(entries: list[dict[str, Any]]) -> list[str]:
    """The manifest is the claim; this checks it. Returns the names that differ."""
    if not MANIFEST.exists():
        return []
    expected = {
        item["image"]: item["sha256"] for item in json.loads(MANIFEST.read_text("utf-8"))["images"]
    }
    drifted = []
    for entry in entries:
        path = IMAGES / entry["image"]
        if not path.exists():
            drifted.append(f"{entry['image']} (missing)")
            continue
        if entry["image"] in expected:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected[entry["image"]]:
                drifted.append(f"{entry['image']} (bytes changed since annotation)")
    return drifted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", help="run just these image names")
    parser.add_argument("--verbose", action="store_true", help="print per-image detail")
    args = parser.parse_args()

    truth = json.loads(GROUND_TRUTH.read_text("utf-8"))
    entries = truth["images"]
    if args.only:
        wanted = set(args.only)
        entries = [e for e in entries if e["image"] in wanted]
        if not entries:
            print(f"no such image: {sorted(wanted)}", file=sys.stderr)
            return 1

    drifted = verify_bytes(entries)
    if drifted:
        print("PROVENANCE FAILURE — these labels no longer describe these bytes:", file=sys.stderr)
        for name in drifted:
            print(f"  {name}", file=sys.stderr)
        return 1

    rows = []
    for index, entry in enumerate(entries, start=1):
        row = run_one(IMAGES / entry["image"], entry)
        rows.append(row)
        flag = "" if not row.get("missed") else "  missed: " + ",".join(row["missed"])
        print(
            f"[{index:2d}/{len(entries)}] {row['image']:<22}"
            f" {len(row['hit'])}/{len(row['expected'])} fields"
            f"  {row.get('ms', 0):>6.0f} ms{flag}",
            flush=True,
        )
        if args.verbose:
            print("      " + json.dumps(row, indent=6)[6:-1].strip())

    summary = summarise(rows)

    print("=" * 78)
    print(f"images                                  {summary['read']}/{summary['images']} read")
    cq = summary["capture_quality"]
    print(
        f"M0 capture gate, pass rate on usable    {cq['usable']}/{cq['measured']}  {cq['pass_rate']}"
    )
    fr = summary["framing_recall"]
    print(
        f"framing recall (no negatives in set)    {fr['correct']}/{fr['measured']}  {fr['recall']}"
    )
    print(
        f"declaration presence, micro F1          {summary['presence_micro']['f1']}"
        f"  (P {summary['presence_micro']['precision']} / R {summary['presence_micro']['recall']}"
        f" over {summary['presence_micro']['support']} labels)"
    )
    print(
        f"Rule 6(1) mandatory recall              {summary['mandatory_recall']['recall']}"
        f"  over {summary['mandatory_recall']['support']} labels"
    )
    print("-" * 78)
    print(f"{'field':<20}{'P':>8}{'R':>8}{'F1':>8}{'support':>9}")
    for field, scores in summary["presence_per_field"].items():
        print(
            f"{field:<20}{scores['precision']:>8.2f}{scores['recall']:>8.2f}"
            f"{scores['f1']:>8.2f}{scores['support']:>9}"
        )
    print("-" * 78)
    print(f"{'value read':<20}{'correct':>10}{'scored':>9}{'accuracy':>10}")
    for field, scores in summary["values"].items():
        if scores["scored"]:
            print(f"{field:<20}{scores['any']:>10}{scores['scored']:>9}{scores['accuracy']:>10.2f}")
    print("-" * 78)
    print(f"median scan                             {summary['median_ms']} ms")
    print(f"mean coverage                           {summary['coverage_mean']}")

    REPORT.write_text(
        json.dumps({"summary": summary, "images": rows}, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nwritten to {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
