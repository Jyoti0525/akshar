"""Weak supervision for the address head — labels from the patterns, not a model.

    .venv/Scripts/python.exe -m training.classifier.harvest
    .venv/Scripts/python.exe -m training.classifier.harvest --limit 40 --verbose

---------------------------------------------------------------------------
WHY THIS EXISTS, AND WHY IT DOES NOT BREAK THE GUARD
---------------------------------------------------------------------------
`training/detector/convert.py` refuses Label Studio `predictions` and takes only
`annotations`, and `rows_from_export` in this package carries the same rule for
the same reason: a model trained on its own output learns its own mistakes and
hands them back as confidence. That guard is right and it is not relaxed here.

This script is a different operation, and the difference is the whole argument.
The labels it emits come from `vision/classify/regex_tier.py` — hand-written
patterns, most of them living in the rulepack, every one readable aloud in a
hearing. The regex tier is an **independent labeller**: it was never trained, it
holds no weights, and it cannot have learned anything from the head it is
supervising. Distant supervision from a rule-based labeller is not self-training.

What this must never do is launder a model prediction into a label. So the
harvest calls `classify_lines` with **no** `model_tier_predictions`, which is
the only route by which a model opinion could enter.

---------------------------------------------------------------------------
THE CAPTION IS STRIPPED, AND THAT IS THE POINT
---------------------------------------------------------------------------
This is the one decision the exercise turns on.

The head is invoked on exactly one population: lines regex could **not** label,
which is to say addresses printed with no caption. If we harvested

    Manufactured by: PARAG MILK FOODS LTD., MANCHAR, PUNE 410503

and trained on it whole, the model would learn the two words `Manufactured by` —
by far the strongest signal in the string — and would learn nothing else. It
would then score beautifully on validation and be worthless in production,
because at inference the caption is precisely what is missing. The training
distribution and the serving distribution would not overlap at all.

So the caption is cut away and only the body is kept. What remains is a company
and a street, which is what the head is actually handed, and the only signals
left to separate the four classes are the ones section 14 says are the real
ones: *"position and context, not vocabulary."*

For the same reason a row is dropped unless the **body alone** still satisfies
`is_address_like`. That function gates the candidate list at inference; a row
that passes it only with its caption attached is a row the head never sees.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import cv2

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from rules.loader import load_rulepack  # noqa: E402
from vision.classify import assemble, continuation, regex_tier  # noqa: E402
from vision.classify.model_tier import CLASSES  # noqa: E402
from vision.pipeline import scan  # noqa: E402

IMAGES = ROOT / "data" / "corpus" / "images"
OUT = ROOT / "training" / "classifier" / "weak_labels.json"

MIN_CONFIDENCE = 0.55
"""A weak label is still a label. Below this the regex tier is hedging, and a
hedged label teaches the head to be wrong with conviction."""

MIN_BODY_CHARS = 12
"""Shorter than this and what survived the cut is a fragment rather than an
address: `by:`, `LTD.`, a line the detector split badly."""


def _caption_patterns() -> dict[str, list[re.Pattern[str]]]:
    """The caption for each class, from the same source the classifier used.

    Read out of the rulepack rather than restated, for the reason
    `regex_tier._RULEPACK_LOCATE` gives: two copies of "what a manufacturer
    caption looks like" drift apart, and the drift is silent.
    """
    pack = load_rulepack()
    out: dict[str, list[re.Pattern[str]]] = {name: [] for name in CLASSES}
    for field, pattern_name in (
        ("manufacturer", "manufacturer_locate"),
        ("importer", "importer_locate"),
        ("consumer_care", "consumer_care_locate"),
        # `Packed by` lives inside `manufacturer_locate` as well, so a packer
        # line carries that caption too and it has to be cut from both.
        ("packer", "manufacturer_locate"),
    ):
        entry = pack.pattern(pattern_name)
        if entry is None:  # pragma: no cover - regex_tier raises on this first
            continue
        out[field].extend(re.compile(source) for source in entry.by_script.values())
    # `packer` is a local pattern in regex_tier, not a rulepack one.
    for source in (r"(?i)\bpacked\s*by\b", r"पैकर|पैक\s*किया"):
        out["packer"].append(re.compile(source))
    return out


_LEADING_PUNCTUATION = re.compile(r"^[\s:;,.\-/|)\]]+")


def strip_caption(text: str, field: str, captions: dict[str, list[re.Pattern[str]]]) -> str:
    """Everything after the caption that named this field.

    Cut at the END of the match rather than the start, so `Mfg. & Pkd. by: ACME
    FOODS` yields `ACME FOODS` and not `& Pkd. by: ACME FOODS`. Punctuation the
    caption left behind goes with it.
    """
    cut = 0
    for pattern in captions.get(field, ()):
        for match in pattern.finditer(text):
            cut = max(cut, match.end())
    return _LEADING_PUNCTUATION.sub("", text[cut:]).strip()


def rows_from_image(path: Path, *, verbose: bool = False) -> list[dict[str, Any]]:
    """Captioned addresses on one photograph, with their captions removed."""
    image = cv2.imread(str(path))
    if image is None:
        return []

    outcome = scan(image, quality_gate=False, online=False)
    lines = list(outcome.ocr.lines) if outcome.ocr else []
    rectified = outcome.rectified
    if not lines or rectified is None:
        return []

    # No `model_tier_predictions`. The labels come from the patterns alone --
    # see the module docstring. Passing them would make this self-training.
    guesses = assemble.classify_lines(lines)
    captions = _caption_patterns()
    height, width = rectified.shape[:2]

    rows: list[dict[str, Any]] = []

    def emit(index: int, field: str, text: str, source: str, confidence: float) -> None:
        line = lines[index]
        rows.append(
            {
                "image": path.name,
                "label": CLASSES.index(field),
                "field": field,
                "text": text,
                "source": source,
                "raw_text": line.text,
                "confidence": round(confidence, 4),
                "box": [line.box.x, line.box.y, line.box.w, line.box.h],
                "cap_height_px": line.cap_height_px,
                "script": line.script,
                "panel_id": line.panel_id or "unknown",
                "label_w": float(width),
                "label_h": float(height),
            }
        )
        if verbose:
            print(f"    {source:10} {field:14} {text[:52]!r}")

    anchors: dict[int, tuple[str, float]] = {}
    for index, (line, guess) in enumerate(zip(lines, guesses, strict=True)):
        if guess.field not in CLASSES or guess.confidence < MIN_CONFIDENCE:
            continue
        anchors[index] = (guess.field, guess.confidence)

        # Source two: the caption and the address share one printed line.
        body = strip_caption(line.text, guess.field, captions)
        if len(body) >= MIN_BODY_CHARS and regex_tier.is_address_like(body):
            emit(index, guess.field, body, "same_line", guess.confidence)

    # Source one, and the one that yields: the caption is a line of its own and
    # the address runs down the lines beneath it. `Marketed By:` strips to the
    # empty string, but the four lines under it are the address, and they are
    # *already* in the uncaptioned form the head meets at inference. Their
    # label is the caption's. This is the label propagating downward, and it is
    # the same downward walk `continuation.find` performs for the extractor, so
    # the rows are drawn from exactly the grouping the pipeline believes in.
    for joined in continuation.find(lines, guesses):
        if joined.anchor not in anchors:
            continue
        field, confidence = anchors[joined.anchor]
        text = lines[joined.line].text
        if len(text) < MIN_BODY_CHARS or not regex_tier.is_address_like(text):
            continue
        emit(joined.line, field, text, "continuation", confidence)

    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harvest weak address labels from the corpus")
    parser.add_argument("--images", type=Path, default=IMAGES)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--limit", type=int, default=0, help="stop after N photographs")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if "test_split" in args.images.parts:
        raise SystemExit("data/test_split/ is sealed until day 36. Not a training input.")

    paths = sorted(
        path
        for path in args.images.rglob("*")
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if args.limit:
        paths = paths[: args.limit]
    print(f"{len(paths)} photographs from {args.images}")

    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    for number, path in enumerate(paths, start=1):
        if args.verbose:
            print(f"  [{number}/{len(paths)}] {path.name}")
        try:
            found = rows_from_image(path, verbose=args.verbose)
        except Exception as exc:  # a bad frame is not a reason to lose the run
            print(f"  [{number}/{len(paths)}] {path.name}: {type(exc).__name__}: {exc}")
            continue
        rows.extend(found)
        if number % 25 == 0 or number == len(paths):
            rate = (time.perf_counter() - started) / number
            remaining = rate * (len(paths) - number)
            print(
                f"  [{number}/{len(paths)}] {len(rows)} rows"
                f"  {rate:.1f} s/photo  ~{remaining / 60:.0f} min left"
            )

    counts = Counter(row["field"] for row in rows)
    photographs = len({row["image"] for row in rows})
    print(f"\n{len(rows)} weakly-labelled addresses from {photographs} photographs")
    for name in CLASSES:
        print(f"  {name:16} {counts.get(name, 0):5}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
