"""Where, exactly, does a missed declaration get lost?

---------------------------------------------------------------------------
THE QUESTION THIS ANSWERS
---------------------------------------------------------------------------
Presence recall on the 38 labelled panels is 0.722: 71 of 255 printed
declarations are not reported. `bench/curves.py` shows those 71 are not hiding
under a confidence threshold — sweeping it recovers none of them. So they are
lost somewhere in the pipeline, and *which stage* decides what work is worth
doing.

The pipeline offers four places to lose a declaration, and they call for
completely different fixes:

    A  NEVER READ         the characters are not in `raw_text` at all.
                          Fix: the detector, the crop budget, the recogniser.

    B  READ, NOT NAMED    the text is in `raw_text` and the rulepack's own
                          locate pattern matches it, but no declaration in the
                          set carries that field.
                          Fix: classifier patterns and tiers.

    C1 READ, UNRECOGNISED the declaration's own printed words ARE in `raw_text`
                          -- the ground truth records them, and they are there --
                          but no locate pattern matches. The pack phrases it in
                          a way nothing knows.
                          Fix: vocabulary and fuzzy matching. Cheap.

    C2 NOT EXTRACTED      the declaration's printed words are NOT in `raw_text`,
                          though other text on the frame is. That region was
                          never proposed, never read, or read as noise.
                          Fix: the detector, the crop budget, the recogniser.

    D  NAMED, WITHDRAWN   a declaration for the field exists but a guard pulled
                          it (a duplicate withdrawal, a demotion).
                          Fix: the guard.

A fix aimed at B when the losses are in A is a fix that cannot move the number
however many packs it is tested on. That is the whole reason this file exists:
to stop the choice of work being made from whichever pack was looked at last.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import re  # noqa: E402

from bench.declaration_blocks import (  # noqa: E402
    DATA,
    DEFAULT_PACK_HEIGHT_MM,
    GROUND_TRUTH,
)
from rules import cached_rulepack  # noqa: E402
from vision.pipeline import scan  # noqa: E402

LOCATE = {
    "mrp": "mrp_locate",
    "net_quantity": "net_quantity_locate",
    "mfg_date": "mfg_date_locate",
    "expiry_date": "expiry_date_locate",
    "batch": "batch_locate",
    "manufacturer": "manufacturer_locate",
    "packer": "packer_locate",
    "importer": "importer_locate",
    "consumer_care": "consumer_care_locate",
    "country_of_origin": "country_of_origin_locate",
    "generic_name": "generic_name_locate",
}


def squeeze(text: str) -> str:
    """Letters and digits only, folded. The recogniser loses spaces and case
    constantly, and neither carries meaning for "is this string on the frame"."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def truth_is_on_the_frame(value, raw: str) -> bool | None:
    """Did the words the pack actually prints reach `raw_text`?

    Returns None where the ground truth records no value to look for (a field
    mapped to null is printed but illegible in that frame, so there is nothing
    to search). A value counts as present if a run of eight or more of its
    characters survives -- whole-string equality would be defeated by a single
    mis-read letter, which is the very thing being measured around.
    """
    values = value if isinstance(value, list) else [value]
    haystack = squeeze(raw)
    checked = False
    for item in values:
        needle = squeeze(str(item) if item is not None else "")
        if len(needle) < 4:
            continue
        checked = True
        if needle in haystack:
            return True
        window = min(len(needle), 8)
        for i in range(len(needle) - window + 1):
            if needle[i : i + window] in haystack:
                return True
    return False if checked else None


def imread(path: Path) -> np.ndarray | None:
    buf = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR) if buf.size else None


def main() -> None:
    pack = cached_rulepack()
    truth = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))

    buckets: Counter[str] = Counter()
    by_field: dict[str, Counter[str]] = {}
    examples: dict[str, list[str]] = {k: [] for k in ("A", "B", "C1", "C2", "C?", "D")}
    budget_bound = 0
    proposed_total = read_total = 0

    for entry in truth["images"]:
        image = imread(DATA / "images" / entry["image"])
        if image is None:
            continue
        outcome = scan(image, quality_gate=False, operator_height_mm=DEFAULT_PACK_HEIGHT_MM)
        ds = outcome.declarations
        if ds is None:
            continue

        proposed_total += outcome.ocr.regions_proposed
        read_total += outcome.ocr.regions_read
        budget_bound += outcome.ocr.regions_proposed > outcome.ocr.regions_read

        raw = ds.raw_text or ""
        named = {d.field for d in ds.declarations}
        # `other` lines still reach raw_text, so a field that was read and then
        # demoted is separable from one that was never read at all.
        other_text = " ".join(d.text for d in ds.declarations if d.field == "other")

        for field in entry.get("fields") or {}:
            if field in named:
                continue

            pattern = pack.pattern(LOCATE.get(field, ""))
            matched = bool(pattern and pattern.matches(raw))
            in_other = bool(pattern and pattern.matches(other_text))

            if matched and in_other:
                bucket = "B"  # the line is there, classified `other`
            elif matched:
                bucket = "D"  # matches raw text but not in a kept line
            elif not raw.strip():
                bucket = "A"  # nothing was read at all
            else:
                on_frame = truth_is_on_the_frame((entry["fields"] or {})[field], raw)
                # C? = the ground truth records no value to search for, so this
                # miss cannot be attributed either way and is never counted
                # towards the case for any particular fix.
                bucket = "C?" if on_frame is None else ("C1" if on_frame else "C2")

            buckets[bucket] += 1
            by_field.setdefault(field, Counter())[bucket] += 1
            if len(examples[bucket]) < 6:
                examples[bucket].append(f"{entry['image']:24} {field}")

    total = sum(buckets.values())
    print("=" * 74)
    print(f"WHERE THE {total} MISSED DECLARATIONS GO")
    print("=" * 74)
    labels = {
        "A": "never read       nothing recognised on the frame at all",
        "B": "read, not named  the line is in the set as `other`",
        "C1": "READ, UNMATCHED  the printed words ARE in raw_text; no pattern knows them",
        "C2": "NOT EXTRACTED    the printed words never reached raw_text",
        "C?": "no truth value   ground truth records none; cannot attribute",
        "D": "named, withdrawn matched raw text but no line kept it",
    }
    for key in ("A", "B", "C1", "C2", "C?", "D"):
        n = buckets[key]
        bar = "#" * round(n / max(total, 1) * 46)
        print(f"  {key}  {n:3}  {n / total:6.1%}  {bar}")
        print(f"        {labels[key]}")

    print()
    print("-" * 74)
    print(f"{'field':20} {'missed':>7} {'A':>4} {'B':>4} {'C1':>4} {'C2':>4} {'C?':>4} {'D':>4}")
    for field, counts in sorted(by_field.items(), key=lambda kv: -sum(kv[1].values())):
        print(
            f"{field:20} {sum(counts.values()):7} "
            f"{counts['A']:4} {counts['B']:4} {counts['C1']:4} "
            f"{counts['C2']:4} {counts['C?']:4} {counts['D']:4}"
        )

    print()
    print("-" * 74)
    print(f"regions proposed {proposed_total}, read {read_total} "
          f"({read_total / max(proposed_total, 1):.1%})")
    print(f"frames where the crop budget bound: {budget_bound} of {len(truth['images'])}")

    for key in ("A", "B", "C1", "C2", "C?", "D"):
        if examples[key]:
            print(f"\n  {key} examples:")
            for line in examples[key]:
                print(f"     {line}")

    out = {
        "total_missed": total,
        "buckets": dict(buckets),
        "by_field": {f: dict(c) for f, c in by_field.items()},
        "regions_proposed": proposed_total,
        "regions_read": read_total,
        "frames_budget_bound": budget_bound,
    }
    (ROOT / "bench" / "funnel.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("\nwritten to bench/funnel.json")


if __name__ == "__main__":
    main()
