"""How often do the six advisory rules fire, and on what? AKSHAR.md §13c, §18.

    python scripts/advisory_false_positives.py --limit 40
    python scripts/advisory_false_positives.py --limit 40 --json out.json

Six rules in the pack carry `advisory: true` — the unit-symbol printing rules
from the National Standards Third Schedule, plus the Numeration Rules digit
form. `rules/packs/lmpc_2011.yaml` says why they are separated:

    "All severity LOW: these are formatting defects, not consumer deception. A
     tool that reports `250 ML` at the same severity as a missing MRP is a tool
     an officer stops trusting."

---------------------------------------------------------------------------
WHY THIS NEEDS MEASURING RATHER THAN REASONING ABOUT
---------------------------------------------------------------------------
Every one of the six fires on the *text of the net quantity declaration*, and
that text comes out of an OCR head. So each has a failure mode that has nothing
to do with the packet:

* `SYMBOL_SPACE` fires when there is no space between value and unit. A
  recogniser that drops a thin space turns a compliant `500 g` into a finding.
* `SYMBOL_CASE` fires on `ML`. A recogniser reading a small lower-case `ml` off
  a curved bottle at 60% confidence may well return `ML`.
* `SYMBOL_STOP` fires on a trailing full stop, which is also what a speck of
  print noise looks like.
* `DIGIT_FORM` fires on non-international numerals, and Devanagari digits are
  exactly what the Devanagari recognition head is least sure about.

So the number that matters is not *"how many advisories did we raise"* but
*"how many of those were the packet's fault"*. Nothing here can answer the
second on its own — that needs a person looking at the pack. What it does is
raise the first, print the exact string that triggered each one, and put them in
front of somebody who can judge, which is the same shape as
`scripts/audit_corpus.py`: **it measures and shortlists; it does not decide.**

The output belongs in `RESULTS.md` with the date, per §18.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import cv2

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from contracts import PackageContext  # noqa: E402
from rules.engine import evaluate  # noqa: E402
from rules.loader import load_rulepack  # noqa: E402
from vision.pipeline import scan  # noqa: E402

MANIFEST = ROOT / "data" / "manifest.json"


def frames(limit: int, *, millimetre_grade_only: bool = True) -> list[Path]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    paths = [
        ROOT / frame["path"]
        for frame in manifest["frames"]
        if frame["set"] == "corpus"
        and frame.get("superseded_by") is None
        and (frame["millimetre_grade"] or not millimetre_grade_only)
    ]
    return paths[:limit] if limit else paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--json", type=Path, help="write the full per-hit detail here")
    parser.add_argument("--all-frames", action="store_true", help="include transcodes")
    args = parser.parse_args(argv)

    # This script prints the text that triggered each finding, and one of the
    # six rules exists precisely to catch Devanagari numerals. On a Windows
    # console that is cp1252, and printing U+0969 raised `UnicodeEncodeError`
    # *after* the whole 40-frame run had completed and before the JSON was
    # written -- losing forty minutes of work to a print statement.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    pack = load_rulepack()
    advisory_ids = {rule.id for rule in pack.rules if rule.advisory}
    enabled = {rule.id for rule in pack.rules if rule.advisory and rule.enabled}
    print(f"{len(advisory_ids)} advisory rules in {pack.version_string}, {len(enabled)} enabled")
    for rule_id in sorted(advisory_ids):
        state = "" if rule_id in enabled else "   (disabled)"
        print(f"  {rule_id}{state}")

    paths = frames(args.limit, millimetre_grade_only=not args.all_frames)
    print(f"\nrunning the pipeline over {len(paths)} frames ...", flush=True)

    hits: dict[str, list[dict[str, Any]]] = defaultdict(list)
    statuses: Counter = Counter()
    scanned = 0
    no_quantity = 0

    for index, path in enumerate(paths, 1):
        image = cv2.imread(str(path))
        if image is None:
            continue
        outcome = scan(image, cache_lookup=lambda _identity: None, quality_gate=False)
        if outcome.declarations is None:
            continue
        scanned += 1

        quantity = outcome.declarations.first("net_quantity")
        if quantity is None:
            no_quantity += 1

        # The context is deliberately minimal. These six rules are about how a
        # symbol is printed, not about what is in the packet, so nothing here
        # should depend on the category -- and if a future one does, this run
        # will over-report rather than silently under-report.
        verdicts = evaluate(outcome.declarations, PackageContext(category="unclassified"), pack)
        for verdict in verdicts:
            if verdict.rule_id not in advisory_ids:
                continue
            statuses[(verdict.rule_id, verdict.status)] += 1
            if verdict.status == "FAIL":
                hits[verdict.rule_id].append(
                    {
                        "image": path.relative_to(ROOT).as_posix(),
                        "found": verdict.found,
                        "net_quantity_text": quantity.text if quantity else None,
                        "ocr_confidence": (
                            round(quantity.ocr_confidence, 3) if quantity else None
                        ),
                    }
                )
        if index % 10 == 0 or index == len(paths):
            print(f"  {index}/{len(paths)}", flush=True)

    print(f"\n{scanned} frames produced a DeclarationSet")
    print(f"{no_quantity} of them read no net_quantity at all\n")

    print(f"  {'rule':32} {'FAIL':>5} {'PASS':>5} {'NO_DATA':>8} {'N/A':>5}  rate")
    print("  " + "-" * 68)
    for rule_id in sorted(advisory_ids):
        fail = statuses[(rule_id, "FAIL")]
        passed = statuses[(rule_id, "PASS")]
        no_data = statuses[(rule_id, "NO_DATA")]
        na = statuses[(rule_id, "NOT_APPLICABLE")]
        judged = fail + passed
        rate = f"{fail / judged:.0%}" if judged else "   -"
        print(f"  {rule_id:32} {fail:5} {passed:5} {no_data:8} {na:5}  {rate:>5}")

    total_fails = sum(len(v) for v in hits.values())
    print(f"\n{total_fails} advisory findings raised over {scanned} frames")
    if scanned:
        print(f"  {total_fails / scanned:.2f} per frame")

    print("\nThe exact string behind each finding. A person decides which are the")
    print("packet's fault and which are the recogniser's:\n")
    for rule_id in sorted(hits):
        print(f"  {rule_id}  ({len(hits[rule_id])})")
        for hit in hits[rule_id][:8]:
            confidence = hit["ocr_confidence"]
            suffix = f"  conf {confidence}" if confidence is not None else ""
            print(f"    {hit['found']!r:40} <- {hit['net_quantity_text']!r}{suffix}")
        if len(hits[rule_id]) > 8:
            print(f"    ... and {len(hits[rule_id]) - 8} more")
        print()

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "rulepack": pack.version_string,
                    "frames_scanned": scanned,
                    "frames_with_no_net_quantity": no_quantity,
                    "counts": {f"{r}|{s}": n for (r, s), n in statuses.items()},
                    "hits": hits,
                },
                indent=1,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
