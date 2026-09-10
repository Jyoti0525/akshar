"""Three-way diff across the gazette OCR caches.

`ingest_gazettes` caches one JSON per page, so a change to the recovery
detectors can be judged by holding the old cache beside the new one instead of
trusting that the run "looked fine". Three snapshots exist:

    .ocr_cache.pre405   before the pitch detector and repair_flipped were
                        corrected -- the baseline
    .ocr_cache.pass1    the first full 405-page sweep, run with a
                        GAP_SIMILARITY that had no positional guard and so
                        deleted genuine provisions as lookalikes
    .ocr_cache          the corrected sweep

What this checks, in the order it matters:

1. **The provisions pass1 deleted are back.** Two were found by hand and are
   named below. They are the reason GAP_SIMILARITY_REACH exists: consecutive
   lines of a statute repeat each other's words, so likeness alone convicts an
   innocent line. If either is still missing, the fix did not take.

2. **No garbled twin came back with them.** Relaxing a duplicate guard can pay
   for a recovered line with a second, mangled reading of a line already held.
   The cache keeps no geometry, so this can only be flagged for eyeballing,
   never decided -- which is exactly how it is reported.

3. **Nothing was lost.** Every page is compared line for line against both
   earlier snapshots. A page that shrank is the loudest possible signal and is
   listed first.

Run after any change to the recovery detectors. It reads only; it writes
nothing and needs no models.
"""

from __future__ import annotations

import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ingest_gazettes import _fold  # noqa: E402

RULEBOOK = ROOT / "data" / "rulebook"

CACHES = (
    ("pre405", ".ocr_cache.pre405"),
    ("pass1", ".ocr_cache.pass1"),
    ("final", ".ocr_cache"),
)

DUPLICATE_SIMILARITY = 0.55
"""Above this, an added line resembles one the page already held closely enough
to be worth a human look. Deliberately below GAP_SIMILARITY: this report is
meant to over-report, because a false alarm costs a glance and a missed
duplicate costs a corrupted quotation."""

PROBES = (
    (
        "approval_of_models_2011",
        "rule 10 heading, Re-submission of disapproved model",
        ("re-submission", "disapproved model"),
    ),
    (
        "ns_rules_2011",
        "definition of physical constants",
        ("physical constants", "physical invariant"),
    ),
    (
        "general_rules_2011",
        "clinical thermometers heading, both halves",
        ("clinical thermometers", "enclosed scale"),
    ),
)


def load(directory: str) -> dict[tuple[str, int], list[str]]:
    """Every cached page as a list of lines, keyed by document and page."""
    pages: dict[tuple[str, int], list[str]] = {}
    root = RULEBOOK / directory
    for path in sorted(root.rglob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        key = (record["doc_id"], int(record["page"]))
        pages[key] = [line for line in record["text"].splitlines() if line.strip()]
    return pages


def probe(pages: dict[tuple[str, int], list[str]], doc: str, needles: tuple[str, ...]) -> list[str]:
    """Pages of `doc` holding every needle, folded so OCR noise does not hide a hit."""
    hits = []
    for (doc_id, page), lines in pages.items():
        if doc_id != doc:
            continue
        folded = _fold(" ".join(lines))
        if all(_fold(needle) in folded for needle in needles):
            hits.append(f"p{page}")
    return sorted(hits)


def similar(line: str, others: list[str]) -> float:
    best = 0.0
    for other in others:
        ratio = SequenceMatcher(None, line, other).ratio()
        best = max(best, ratio)
    return best


def main() -> int:
    snapshots = {}
    for name, directory in CACHES:
        if not (RULEBOOK / directory).exists():
            print(f"missing snapshot: {directory}")
            return 1
        snapshots[name] = load(directory)

    print("cache        pages   lines    chars")
    print("-" * 38)
    for name, _ in CACHES:
        pages = snapshots[name]
        lines = sum(len(v) for v in pages.values())
        chars = sum(len(line) for v in pages.values() for line in v)
        print(f"{name:<10} {len(pages):>6} {lines:>7} {chars:>8}")
    print()

    # 1. the provisions pass1 deleted
    print("provisions this run exists to restore")
    print("-" * 60)
    restored = True
    for doc, label, needles in PROBES:
        found = {name: probe(snapshots[name], doc, needles) for name, _ in CACHES}
        held = ", ".join(f"{n}={found[n] or 'ABSENT'}" for n, _ in CACHES)
        ok = bool(found["final"])
        restored = restored and ok
        print(f"  [{'ok' if ok else 'MISSING'}] {label}")
        print(f"         {doc}: {held}")
    print()

    # 2 and 3. what each page gained and lost
    final, pass1, pre = snapshots["final"], snapshots["pass1"], snapshots["pre405"]
    shrunk: list[tuple[str, int, int, int]] = []
    suspects: list[tuple[str, int, float, str]] = []
    gained = 0

    for key in sorted(final):
        new = final[key]
        old = pre.get(key, [])
        folded_old = [_fold(line) for line in old]
        added = [line for line in new if _fold(line) not in folded_old]
        gained += len(added)
        if len(new) < len(old):
            shrunk.append((key[0], key[1], len(old), len(new)))
        held = [_fold(line) for line in new]
        for line in added:
            folded = _fold(line)
            rest = [other for other in held if other != folded]
            score = similar(folded, rest)
            if score >= DUPLICATE_SIMILARITY:
                suspects.append((key[0], key[1], score, line[:64]))

    print(f"lines present in final and not in pre405: {gained}")
    print()

    print(f"pages that lost lines against pre405: {len(shrunk)}")
    for doc, page, was, now in sorted(shrunk, key=lambda r: r[2] - r[3], reverse=True)[:15]:
        print(f"  {doc:<28} p{page:<5} {was} -> {now}")
    print()

    print(f"added lines resembling one the page already held: {len(suspects)}")
    print("(eyeball only -- consecutive lines of a statute legitimately score high)")
    for doc, page, score, text in sorted(suspects, key=lambda r: r[2], reverse=True)[:15]:
        print(f"  {score:.2f}  {doc:<26} p{page:<5} {text}")
    print()

    # The fix, measured directly. pass1 ran the same recovery sweep with the
    # positional guard missing, so every line final holds and pass1 does not is
    # a line likeness alone had convicted.
    kept, dropped = 0, 0
    examples: list[tuple[str, int, str]] = []
    for key in sorted(final):
        one = [_fold(line) for line in pass1.get(key, [])]
        two = [_fold(line) for line in final[key]]
        for line in final[key]:
            if _fold(line) not in one:
                kept += 1
                examples.append((key[0], key[1], line[:64]))
        dropped += sum(1 for line in one if line not in two)

    print(f"lines final holds that pass1 had deleted: {kept}")
    print(f"lines pass1 held that final does not:     {dropped}")
    for doc, page, text in examples[:10]:
        print(f"  + {doc:<26} p{page:<5} {text}")

    return 0 if restored and not shrunk else 1


if __name__ == "__main__":
    raise SystemExit(main())
