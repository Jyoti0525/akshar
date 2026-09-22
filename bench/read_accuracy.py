"""How accurately do we *read* the characters, separately from finding them?

---------------------------------------------------------------------------
THE GAP THIS FILLS
---------------------------------------------------------------------------
Every bench in this folder so far measures whether a declaration was found and
named: `declaration_blocks.py` scores presence, `funnel.py` says which stage
lost the ones that were missed. None of them measures the thing the whole chain
rests on — **whether the characters we recognised are the characters that are
printed**.

That matters because a rules engine is only as honest as the text beneath it. A
pack whose address reads `FACTOP DAKSHNDAR AOAD KOLATA` has been *found*; it has
not been *read*. Presence recall counts it as a success. An officer reading the
report sees gibberish, and every downstream comparison — a net quantity against
a permitted unit, an MRP against a printed one, a country against a lexicon —
is matching on corrupted input.

---------------------------------------------------------------------------
HOW IT IS MEASURED
---------------------------------------------------------------------------
Ground truth records the exact string the pack prints. The recogniser's output
for a whole frame is one long `raw_text`, in which that string appears somewhere,
surrounded by everything else on the panel. So the question is not "are these
two strings equal" but **"what is the closest this frame came to printing what
the pack prints"**.

That is infix edit distance: Levenshtein with a free start and a free end on the
haystack, which finds the minimum edit distance between the pattern and *any*
substring of the text. `dp[0][j] = 0` makes the start free; taking the minimum
across the final row makes the end free.

    CER = edits / len(printed string)

0.00 is a perfect read. 1.00 means every character had to be changed, which in
practice means the words never reached `raw_text` at all.

**A high CER here does not distinguish "read badly" from "never read".** That is
deliberate — `funnel.py` already separates those two, and duplicating the
distinction here would give two files that can disagree. What this file adds is
the *severity* axis the funnel has no notion of: the difference between a
declaration read with two letters wrong and one read as noise.

---------------------------------------------------------------------------
WHY IT IS SPLIT BY SCRIPT
---------------------------------------------------------------------------
`vision/ocr/recognise.py` maps **both** scripts to one model file:

    MODEL_FILENAMES = {"latin": "ppocrv5_rec_devanagari.onnx",
                       "devanagari": "ppocrv5_rec_devanagari.onnx"}

The Devanagari head's character table does contain Latin — 52 letters, the ten
digits, `₹` and ordinary punctuation — so English text does not fail loudly. It
degrades. Whether that degradation is small enough to live with is an empirical
question that nothing in this repository has ever asked, and it is the question
that decides whether fetching a dedicated Latin head is worth a bundle megabyte.

So: CER bucketed by the script of the *printed* string. If the Latin bucket is
materially worse than the Devanagari one on the same frames, read by the same
detector, through the same crops, the recognition head is the difference.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench.declaration_blocks import (  # noqa: E402
    DATA,
    DEFAULT_PACK_HEIGHT_MM,
    GROUND_TRUTH,
)
from vision.ocr import dictionary, recognise  # noqa: E402
from vision.pipeline import scan  # noqa: E402

HEADS: dict[str, tuple[str, str]] = {
    "devanagari": ("ppocrv5_rec_devanagari.onnx", "devanagari_dict.txt"),
    "en": ("ppocrv5_rec_en.onnx", "en_dict.txt"),
    "latin": ("ppocrv5_rec_latin.onnx", "latin_dict.txt"),
}
"""Candidate recognition heads for **Latin** text, by `--head`.

This flag is the whole point of the file's `BY SCRIPT` section, and it exists
because section 15b asked for a measurement rather than an assumption:

    "v5's Devanagari recogniser covers Hindi and Marathi and handles English
     too. Benchmark whether a second English-only head earns its bundle size;
     do not assume it."

`devanagari` is the shipped default -- one head serving both scripts. The other
two are PaddlePaddle's own ONNX releases of the same v5 mobile architecture,
Apache-2.0, within 200 KB of the same size, so the comparison is between
character tables and training sets rather than between model families:

    head          table   what it was trained on
    devanagari      568   Hindi/Marathi, with 94 ASCII characters carried along
    en              436   English only
    latin           836   Latin-script languages as a family

Only the Latin mapping moves. Devanagari text is read by the Devanagari head in
every configuration, so any change in the Devanagari row of the output would be
noise and a warning that the run was not controlled.
"""


def use_head(name: str) -> None:
    """Point the Latin script at one of `HEADS` for the rest of the process.

    Mutating the module tables rather than threading a parameter through
    `scan`: the head choice is deliberately a deployment fact, not a per-call
    one -- `vision/ocr/roi.py` deduplicates its two candidate heads by comparing
    exactly this pair of names, so a benchmark that bypassed them would measure
    a routing path production does not have.
    """
    model, table = HEADS[name]
    recognise.MODEL_FILENAMES["latin"] = model
    dictionary.DICT_FILENAMES["latin"] = table
    dictionary.load_dictionary.cache_clear()


MIN_CHARS = 6
"""Shorter strings give a CER too coarse to mean anything.

A four-character value scores in steps of 0.25, so a single mis-read letter is
indistinguishable from a quarter of the string being wrong. Values this short
are mostly dates and quantities, which `declaration_blocks.py` already scores
against a parsed contract rather than as free text.
"""


def normalise(text: str) -> str:
    """Fold everything neither the rules nor an officer would care about.

    Case and run-length of whitespace are not properties of the print; the
    recogniser loses both constantly and no rule reads either. Unicode is
    NFC-folded so a Devanagari string composed differently by the annotator than
    by the model is not scored as an error it is not.
    """
    text = unicodedata.normalize("NFC", text or "")
    return re.sub(r"\s+", " ", text).strip().lower()


def infix_distance(pattern: str, haystack: str) -> int:
    """Minimum edit distance between `pattern` and any substring of `haystack`.

    Two rows rather than a full matrix: the haystack is a whole panel of text and
    the pattern a single declaration, so the full table would be megabytes for a
    number we read once.
    """
    if not pattern:
        return 0
    if not haystack:
        return len(pattern)

    # Row 0 is all zeros: starting anywhere in the haystack is free.
    previous = [0] * (len(haystack) + 1)
    for i, pchar in enumerate(pattern, 1):
        current = [i] + [0] * len(haystack)
        for j, hchar in enumerate(haystack, 1):
            current[j] = min(
                previous[j] + 1,               # delete from pattern
                current[j - 1] + 1,            # insert from haystack
                previous[j - 1] + (pchar != hchar),
            )
        previous = current
    # Ending anywhere is free.
    return min(previous)


def script_of(text: str) -> str:
    """Which script the *printed* string is in, by which has more letters."""
    devanagari = sum(1 for c in text if "ऀ" <= c <= "ॿ")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    if devanagari and devanagari >= latin:
        return "devanagari"
    return "latin" if latin else "other"


def imread(path: Path) -> np.ndarray | None:
    buf = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR) if buf.size else None


def band(cer: float) -> str:
    """Severity, because a mean CER hides the shape of the distribution."""
    if cer <= 0.05:
        return "clean"
    if cer <= 0.20:
        return "usable"
    if cer <= 0.50:
        return "corrupt"
    return "absent"


BANDS = ("clean", "usable", "corrupt", "absent")
BAND_MEANING = {
    "clean": "<=0.05  every word recoverable",
    "usable": "<=0.20  a human reads it; fuzzy matching can reach it",
    "corrupt": "<=0.50  words are mangled; exact patterns cannot match",
    "absent": " >0.50  effectively not on the frame",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--head", choices=sorted(HEADS), default="devanagari",
                        help="which recognition head reads Latin text")
    parser.add_argument("--out", default="read_accuracy.json",
                        help="filename under bench/ to write, so a comparison "
                             "run does not overwrite the shipped baseline")
    args = parser.parse_args()
    use_head(args.head)

    truth = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))

    rows: list[dict] = []
    for entry in truth["images"]:
        image = imread(DATA / "images" / entry["image"])
        if image is None:
            continue
        outcome = scan(image, quality_gate=False, operator_height_mm=DEFAULT_PACK_HEIGHT_MM)
        raw = normalise(outcome.declarations.raw_text if outcome.declarations else "")

        for field, value in (entry.get("fields") or {}).items():
            for item in value if isinstance(value, list) else [value]:
                if item is None:
                    continue
                printed = normalise(str(item))
                if len(printed) < MIN_CHARS:
                    continue
                edits = infix_distance(printed, raw)
                rows.append({
                    "image": entry["image"],
                    "field": field,
                    "script": script_of(str(item)),
                    "chars": len(printed),
                    "cer": round(edits / len(printed), 4),
                })

    if not rows:
        print("no comparable strings in ground truth")
        return 1

    def summarise(subset: list[dict]) -> tuple[float, float]:
        """Mean CER, and character-weighted CER.

        The weighted figure is the one to trust for "how much of the panel did
        we read": an unweighted mean lets a six-character value count as much as
        a 120-character address.
        """
        if not subset:
            return float("nan"), float("nan")
        mean = sum(r["cer"] for r in subset) / len(subset)
        chars = sum(r["chars"] for r in subset)
        weighted = sum(r["cer"] * r["chars"] for r in subset) / max(chars, 1)
        return mean, weighted

    print("=" * 74)
    print(f"LATIN HEAD: {args.head}  ({HEADS[args.head][0]})")
    print("CHARACTER ERROR RATE — printed string vs what the recogniser produced")
    print("=" * 74)
    mean, weighted = summarise(rows)
    print(f"  {len(rows)} strings, {sum(r['chars'] for r in rows)} characters")
    print(f"  mean CER {mean:.4f}   character-weighted CER {weighted:.4f}")

    print("\n" + "-" * 74)
    print("BY SCRIPT OF THE PRINTED STRING  (both go through one model file)")
    print(f"{'script':14} {'n':>5} {'chars':>7} {'mean CER':>10} {'weighted':>10}")
    for name in ("latin", "devanagari", "other"):
        subset = [r for r in rows if r["script"] == name]
        if not subset:
            continue
        m, w = summarise(subset)
        print(f"{name:14} {len(subset):5} {sum(r['chars'] for r in subset):7} "
              f"{m:10.4f} {w:10.4f}")

    print("\n" + "-" * 74)
    print("SEVERITY")
    for name in BANDS:
        n = sum(1 for r in rows if band(r["cer"]) == name)
        bar = "#" * round(n / len(rows) * 40)
        print(f"  {name:8} {n:4} {n / len(rows):6.1%}  {bar}")
        print(f"           {BAND_MEANING[name]}")

    print("\n" + "-" * 74)
    print("BY FIELD")
    print(f"{'field':20} {'n':>4} {'mean CER':>10} {'clean':>7} {'absent':>7}")
    fields = sorted({r["field"] for r in rows})
    for field in sorted(fields, key=lambda f: -summarise([r for r in rows if r["field"] == f])[0]):
        subset = [r for r in rows if r["field"] == field]
        m, _ = summarise(subset)
        clean = sum(1 for r in subset if band(r["cer"]) == "clean")
        absent = sum(1 for r in subset if band(r["cer"]) == "absent")
        print(f"{field:20} {len(subset):4} {m:10.4f} {clean:7} {absent:7}")

    print("\n" + "-" * 74)
    print("WORST READS THAT ARE STILL ON THE FRAME (0.20 < CER <= 0.60)")
    print("  — these are the ones a better recognition head would recover;")
    print("    above 0.60 the text was probably never extracted at all.")
    middle = sorted((r for r in rows if 0.20 < r["cer"] <= 0.60), key=lambda r: -r["cer"])
    for r in middle[:12]:
        print(f"  {r['cer']:.3f}  {r['script']:11} {r['field']:18} {r['image'][:28]}")

    out = ROOT / "bench" / args.out
    out.write_text(json.dumps({
        "head": args.head,
        "strings": len(rows),
        "mean_cer": round(mean, 4),
        "weighted_cer": round(weighted, 4),
        "by_script": {
            s: {
                "n": len([r for r in rows if r["script"] == s]),
                "mean_cer": round(summarise([r for r in rows if r["script"] == s])[0], 4),
                "weighted_cer": round(summarise([r for r in rows if r["script"] == s])[1], 4),
            }
            for s in ("latin", "devanagari") if any(r["script"] == s for r in rows)
        },
        "bands": {b: sum(1 for r in rows if band(r["cer"]) == b) for b in BANDS},
        "rows": rows,
    }, indent=1), encoding="utf-8")
    print(f"\nwritten to {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
