"""Does the system accuse a compliant pack? Measured, not asserted. AKSHAR.md §18.

    .venv/Scripts/python.exe bench/false_accusations.py

`bench/declaration_blocks.py` scores EXTRACTION -- did we read what is printed.
This scores the VERDICT, which is the thing an officer actually sees and the
only thing a manufacturer can be asked to answer for.

---------------------------------------------------------------------------
WHAT CAN AND CANNOT BE REFUTED MECHANICALLY
---------------------------------------------------------------------------
Only PRESENCE rules. A rule saying "X is not declared" is false exactly when
`data/declaration_blocks/ground_truth.json` records X as printed on that frame,
and the ground truth was written by reading the panel before any of this ran.

Everything else is reported as needing an eye rather than scored. An
over-sticker finding, a character width ratio, an exclusion zone: those are
claims about geometry or duplication that a list of fields cannot settle. An
earlier version of this file scored them anyway and called
`LMPC.MRP.OVERSTICKER` a false accusation on `camlin.webp`, whose panel
genuinely carries two prices -- `New MRP Rs 29.00` pasted above `MRP Rs 30.00`.
It was right and the bench was wrong.

---------------------------------------------------------------------------
RULE 6(1)(a) IS SATISFIED THREE WAYS
---------------------------------------------------------------------------
A manufacturer, a packer or an importer. A pack naming only its packer has not
failed to name a manufacturer, so `SATISFIED_BY` accepts any of the three
before calling `LMPC.MFR.PRESENT` true. Without that this bench would report
false accusations that the engine never made.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from contracts import PackageContext  # noqa: E402
from rules.checks._common import reading_supports_an_absence  # noqa: E402
from rules.engine import evaluate  # noqa: E402
from rules.loader import load_rulepack  # noqa: E402
from vision.pipeline import scan  # noqa: E402

DATA = ROOT / "data" / "declaration_blocks"
REPORT = ROOT / "bench" / "false_accusations.json"

PRESENCE_RULE_FIELD = {
    "LMPC.MRP.PRESENT": "mrp",
    "LMPC.NETQTY.PRESENT": "net_quantity",
    "LMPC.DATE.PRESENT": "mfg_date",
    "LMPC.MFR.PRESENT": "manufacturer",
    "LMPC.CARE.PRESENT": "consumer_care",
    "LMPC.NAME.PRESENT": "generic_name",
    "LMPC.GENERIC.PRESENT": "generic_name",
    "LMPC.ORIGIN.PRESENT": "country_of_origin",
    "LMPC.IMPORTER.PRESENT": "importer",
    "LMPC.BATCH.PRESENT": "batch",
}

SATISFIED_BY = {"manufacturer": {"manufacturer", "packer", "importer"}}
"""Rule 6(1)(a): name and address of the manufacturer OR packer OR importer."""


def main() -> int:
    truth = json.loads((DATA / "ground_truth.json").read_text("utf-8"))
    pack = load_rulepack()
    ctx = PackageContext()

    rows: list[dict[str, Any]] = []
    by_rule: dict[str, list[str]] = defaultdict(list)
    guard_fired = 0

    for entry in truth["images"]:
        name = entry["image"]
        printed = set(entry["fields"])
        blank = set(entry.get("blank_labels", []))

        image = cv2.imread(str(DATA / "images" / name))
        if image is None:
            continue
        outcome = scan(image, quality_gate=False)
        ds = outcome.declarations
        if ds is None:
            continue

        withheld = reading_supports_an_absence(ds, pack)
        guard_fired += withheld is not None

        blocking = [v for v in evaluate(ds, ctx, pack) if v.status == "FAIL" and not v.advisory]
        extracted = {d.field for d in ds.declarations}

        false_n = 0
        detail = []
        for v in blocking:
            field = PRESENCE_RULE_FIELD.get(v.rule_id)
            if field is None:
                verdict = "needs-eye"
            else:
                accepts = SATISFIED_BY.get(field, {field})
                if accepts & blank:
                    verdict = "TRUE-blank-on-pack"
                elif accepts & printed:
                    verdict = "FALSE"
                    false_n += 1
                else:
                    verdict = "TRUE"
            detail.append(
                {
                    "rule": v.rule_id,
                    "field": field,
                    "verdict": verdict,
                    # The distinction that says whose fault a false accusation
                    # is: a field we never read is an extraction failure, one we
                    # DID read and still failed is the rule disagreeing with the
                    # extractor about what the declaration looks like.
                    "was_extracted": field in extracted if field else None,
                }
            )
            by_rule[v.rule_id].append(verdict)

        rows.append(
            {
                "image": name,
                "blocking": len(blocking),
                "false": false_n,
                "guard_withheld": withheld is not None,
                "extracted": sorted(extracted),
                "printed": sorted(printed),
                "accusations": detail,
            }
        )
        print(
            f"{name:<22} FAIL {len(blocking):>2}  false {false_n:>2}"
            f"  guard {'ON ' if withheld else 'off'}"
            f"{'  <-- FALSE' if false_n else ''}",
            flush=True,
        )

    checkable = sum(1 for r in rows for a in r["accusations"] if a["verdict"] != "needs-eye")
    needs_eye = sum(1 for r in rows for a in r["accusations"] if a["verdict"] == "needs-eye")
    false_total = sum(r["false"] for r in rows)
    never_read = sum(
        1
        for r in rows
        for a in r["accusations"]
        if a["verdict"] == "FALSE" and a["was_extracted"] is False
    )

    print("=" * 78)
    print(f"packs                                       {len(rows)}")
    print(f"blocking FAILs raised                       {sum(r['blocking'] for r in rows)}")
    print(f"  presence claims (refutable here)          {checkable}")
    print(f"  DEMONSTRABLY FALSE                        {false_total}")
    print(f"    of those, the field was never read      {never_read}   <- extraction, not the rule")
    print(f"    of those, it was read and still failed  {false_total - never_read}   <- the rule")
    print(f"  geometry / duplication (needs an eye)     {needs_eye}")
    print(f"packs with at least one false FAIL          {sum(1 for r in rows if r['false'])}")
    print(
        f"packs with a clean sheet                    {sum(1 for r in rows if not r['blocking'])}"
    )
    print(f"'not read well enough' guard withheld on    {guard_fired} of {len(rows)}")
    print("-" * 78)
    print(f"{'rule':<34}{'fails':>7}{'false':>7}{'true':>7}{'eye':>6}")
    for rule, hits in sorted(by_rule.items(), key=lambda kv: -len(kv[1])):
        print(
            f"{rule:<34}{len(hits):>7}{hits.count('FALSE'):>7}"
            f"{sum(1 for h in hits if h.startswith('TRUE')):>7}{hits.count('needs-eye'):>6}"
        )

    REPORT.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"\nwritten to {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
