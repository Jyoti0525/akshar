"""PP-OCR baseline before any fine-tuning. AKSHAR.md §14, §17 M4.

    python -m training.ocr.baseline --speed            # ROI vs full-image
    python -m training.ocr.baseline --worksheet out.csv  # transcription sheet
    python -m training.ocr.baseline --cer transcriptions.csv

Section 14 is unusually direct about the order of work here:

    "Don't start here. Run the PP-OCRv5 baseline and record CER by surface type.
     Fine-tune only if it fails, only on what fails, recognition head only, CTC
     loss."

So this module measures. It does not train, and there is deliberately no
`train.py` beside it yet -- writing one before the baseline exists would be
starting exactly where the plan says not to.

---------------------------------------------------------------------------
M4 HAS TWO HALVES AND ONLY ONE NEEDS A HUMAN
---------------------------------------------------------------------------
Section 17's M4: *"Done when: baseline CER recorded per surface type before any
fine-tuning decision, and the ROI path at least 5x faster than full-image on the
same photos."*

The second half needs no ground truth at all -- it is a stopwatch on two code
paths over the same frames -- so `--speed` runs today and writes a number into
`RESULTS.md`. The first half needs somebody to type what the packet actually
says, which is why `--worksheet` exists: it runs the pipeline, writes what the
recogniser read into a CSV with an empty `truth` column beside it, and `--cer`
scores the two columns once a person has filled it in.

That split matters because it is the difference between *"we have not measured
CER"* and *"we cannot measure CER"*. We can; it costs a person an hour.

---------------------------------------------------------------------------
SURFACE TYPE, AND WHY IT IS A COLUMN RATHER THAN A MODEL
---------------------------------------------------------------------------
Section 14 predicts where this will fail: *"foil glare, stylised brand fonts,
curved bottles, low-contrast kraft paper."* A single corpus-wide CER would
average those together with flat printed cartons and report a number that
describes no real photograph.

Nothing here can tell foil from card, so the surface type is a column the
annotator fills, from the fixed vocabulary below. A heuristic guess would put a
fabricated grouping under a real measurement, which is worse than no grouping.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from vision.ocr import detect_text, recognise  # noqa: E402
from vision.ocr.roi import _line_height_px  # noqa: E402

SURFACES = (
    "flat_carton",
    "foil_or_metallised",
    "curved_bottle",
    "curved_can",
    "kraft_paper",
    "clear_plastic",
    "stylised_brand_face",
    "other",
)
"""Section 14's four predicted failure modes, plus the surfaces they must be
compared against. Fixed, because a free-text column produces `foil`, `Foil`,
`foil wrapper` and `metallised` and then groups them as four surfaces."""

MANIFEST = ROOT / "data" / "manifest.json"


def live_frames(*, millimetre_grade_only: bool = True) -> list[Path]:
    """Corpus frames, superseded transcodes dropped.

    Millimetre-grade by default -- not because CER needs the resolution, but
    because these are the frames the recogniser will actually be given once the
    capture protocol is fixed, and a baseline measured on a downscale would set
    the fine-tuning decision against the wrong input.
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return [
        ROOT / frame["path"]
        for frame in manifest["frames"]
        if frame["set"] == "corpus"
        and frame.get("superseded_by") is None
        and (frame["millimetre_grade"] or not millimetre_grade_only)
    ]


# ---------------------------------------------------------------------------
# M4, half two: the ROI path against full-image OCR
# ---------------------------------------------------------------------------


def _crop(image, box):
    """One text region out of the frame, or None if it has no area.

    `Box` carries floats -- `vision/ocr/detect_text.py` scales the probability
    map back to source coordinates and does not round -- and numpy slicing with
    a float raises `TypeError` rather than truncating. Clamped as well as
    rounded, because `_unclip` deliberately dilates a region past the polygon it
    was fitted to and a declaration printed at the edge of the pack lands
    outside the image.
    """
    x = max(0, round(box.x))
    y = max(0, round(box.y))
    right = min(image.shape[1], round(box.x + box.w))
    bottom = min(image.shape[0], round(box.y + box.h))
    if right <= x or bottom <= y:
        return None
    crop = image[y:bottom, x:right]
    return crop if crop.size else None


def measure_speed(paths: list[Path], *, mm_per_px: float | None) -> dict[str, float]:
    """Time three recognition strategies over the same frames. No ground truth needed.

    **Getting the comparison right matters more than running it.** The first
    version of this function timed the ROI path against `recognise.read(image)`
    -- the whole frame handed to the recognition head as one crop -- and
    reported the ROI path as *eight times slower*. That number was real and
    meaningless: the head resizes its input to a fixed 48 px height, so a
    4032 px frame becomes a 48 px smear, costs one cheap forward pass, and reads
    nothing at all. It is measured below and reported as `degenerate_ms`,
    because a reader who tries the obvious comparison deserves to be told why it
    is not the one section 4 makes.

    Section 4's actual claim: *"the expensive recognition head runs only on the
    four to eight crops that could plausibly be declarations. That alone is
    roughly 5x on the stage that dominates everything."* The naive pipeline it
    is 5x faster than reads **every** region the detector proposes, at native
    resolution, and throws most of the results away. So that is what
    `all_regions_ms` times, and the speedup is against it.

    **`mm_per_px` is not optional here, and the first run got it wrong.** With
    it omitted, `detect_text.input_side` returns the 640 px floor, so a 4032 px
    frame is detected at a 6.3x downscale and the small print -- the print Rule
    7(2) is actually about -- is never proposed at all. The naive baseline is
    then only 16 regions, the ROI path reads 8 of them, and the measured saving
    is 1.8x rather than 5x. That is a true measurement of the wrong pipeline:
    the real one recovers scale from the marker card first and sizes detection
    from the statute, up to `LIMIT_SIDE_MAX`.

    So the caller supplies a scale, and the default is the one section 18b
    actually measured on the ruler corpus (4.9-11.7 px/mm, so ~0.1 mm/px). Both
    figures are reported, because the difference between them *is* the finding:
    the ROI saving is a function of how many regions detection proposes, and
    that is a function of the scale tier.
    """
    roi_ms: list[float] = []
    all_ms: list[float] = []
    degenerate_ms: list[float] = []
    crops_per_frame: list[int] = []
    regions_per_frame: list[int] = []

    for index, path in enumerate(paths, 1):
        image = cv2.imread(str(path))
        if image is None:
            continue

        regions, _detect_ms, _version = detect_text.propose_regions(image, mm_per_px=mm_per_px)
        crops = [crop for region in regions if (crop := _crop(image, region.box)) is not None]
        if not crops:
            continue
        # Section 4 budgets 4-8. Taking the tallest is what `roi.rank_regions`
        # does, for the same reason: a declaration is large print.
        order = sorted(
            range(len(crops)),
            key=lambda i: _line_height_px(regions[i]),
            reverse=True,
        )
        chosen = [crops[i] for i in order[:8]]

        started = time.perf_counter()
        for crop in chosen:
            recognise.read(crop)
        roi_ms.append((time.perf_counter() - started) * 1000.0)

        started = time.perf_counter()
        for crop in crops:
            recognise.read(crop)
        all_ms.append((time.perf_counter() - started) * 1000.0)

        started = time.perf_counter()
        recognise.read(image)
        degenerate_ms.append((time.perf_counter() - started) * 1000.0)

        crops_per_frame.append(len(chosen))
        regions_per_frame.append(len(crops))

        if index % 10 == 0 or index == len(paths):
            print(f"  {index}/{len(paths)}", flush=True)

    roi_median = statistics.median(roi_ms)
    all_median = statistics.median(all_ms)
    return {
        "frames": len(roi_ms),
        "detector_input_px": detect_text.input_side(image, mm_per_px),
        "median_crops": statistics.median(crops_per_frame),
        "median_regions": statistics.median(regions_per_frame),
        "roi_median_ms": round(roi_median, 1),
        "all_regions_median_ms": round(all_median, 1),
        "degenerate_whole_frame_ms": round(statistics.median(degenerate_ms), 1),
        "speedup": round(all_median / roi_median, 2) if roi_median else 0.0,
    }


# ---------------------------------------------------------------------------
# M4, half one: CER, once a person has said what the packet says
# ---------------------------------------------------------------------------


def write_worksheet(paths: list[Path], out: Path, *, per_frame: int = 6) -> int:
    """What the recogniser read, with an empty column beside it for the truth.

    The `read` column is filled in deliberately. An empty sheet would be faster
    to generate and far slower to fill: correcting a line is quicker than typing
    one, and a line the recogniser got right needs only a glance. It is also the
    same argument `scripts/prelabel_corpus.py` makes for proposing boxes.

    **The risk of pre-filling is anchoring** -- an annotator who sees `MPEE`
    may accept it. So the instructions row says, in the file, that a blank truth
    cell means "not checked" and is dropped from the score rather than counted
    as agreement.
    """
    rows = []
    for index, path in enumerate(paths, 1):
        image = cv2.imread(str(path))
        if image is None:
            continue
        regions, _ms, _version = detect_text.propose_regions(image)
        chosen = sorted(regions, key=lambda region: _line_height_px(region), reverse=True)
        for region in chosen[:per_frame]:
            box = region.box
            crop = _crop(image, box)
            if crop is None:
                continue
            read, _crop_used, _pad = recognise.read(crop)
            rows.append(
                {
                    "image": path.relative_to(ROOT).as_posix(),
                    "x": box.x,
                    "y": box.y,
                    "w": box.w,
                    "h": box.h,
                    "read": read.text,
                    "confidence": round(read.confidence, 3),
                    "truth": "",
                    "surface": "",
                }
            )
        if index % 10 == 0 or index == len(paths):
            print(f"  {index}/{len(paths)}  {len(rows)} lines", flush=True)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["image", "x", "y", "w", "h", "read", "confidence", "truth", "surface"]
        )
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def levenshtein(a: str, b: str) -> int:
    """Edit distance. Iterative, two rows, because these strings are short and
    a full matrix over 3,000 lines is pointless memory."""
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            )
        previous = current
    return previous[-1]


def score_cer(sheet: Path) -> dict[str, dict[str, float]]:
    """CER per surface type, from a filled-in worksheet.

    CER is `edits / len(truth)`, summed over lines rather than averaged over
    them -- a per-line mean lets one wrong character on a two-character line
    count as much as twenty wrong on a forty-character one, and the second is
    the more serious failure.
    """
    by_surface: dict[str, list[tuple[int, int]]] = defaultdict(list)
    skipped = 0
    with sheet.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            truth = (row.get("truth") or "").strip()
            if not truth:
                skipped += 1  # not checked; never counted as agreement
                continue
            surface = (row.get("surface") or "").strip() or "unlabelled"
            by_surface[surface].append((levenshtein(row.get("read") or "", truth), len(truth)))

    report: dict[str, dict[str, float]] = {}
    for surface, pairs in sorted(by_surface.items()):
        edits = sum(edit for edit, _ in pairs)
        characters = sum(length for _, length in pairs)
        report[surface] = {
            "lines": len(pairs),
            "characters": characters,
            "cer": round(edits / characters, 4) if characters else 0.0,
        }
    total_edits = sum(e for pairs in by_surface.values() for e, _ in pairs)
    total_chars = sum(c for pairs in by_surface.values() for _, c in pairs)
    report["ALL"] = {
        "lines": sum(len(p) for p in by_surface.values()),
        "characters": total_chars,
        "cer": round(total_edits / total_chars, 4) if total_chars else 0.0,
        "unchecked_lines_skipped": skipped,
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speed", action="store_true", help="M4 half two: ROI vs full image")
    parser.add_argument("--worksheet", type=Path, help="write a transcription sheet here")
    parser.add_argument("--cer", type=Path, help="score a filled-in worksheet")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--all-frames", action="store_true", help="include transcodes")
    parser.add_argument(
        "--mm-per-px",
        type=float,
        default=0.1,
        help="scale to size detection from; 0.1 is what section 18b measured (default)",
    )
    args = parser.parse_args(argv)

    if args.cer:
        report = score_cer(args.cer)
        print(f"\nCER by surface type -- {args.cer}\n")
        print(f"  {'surface':24} {'lines':>7} {'chars':>8} {'CER':>8}")
        for surface, values in report.items():
            print(
                f"  {surface:24} {values['lines']:7.0f} {values['characters']:8.0f} "
                f"{values['cer']:8.4f}"
            )
        unchecked = report["ALL"].get("unchecked_lines_skipped", 0)
        if unchecked:
            print(f"\n  {unchecked:.0f} line(s) had an empty `truth` and were not scored.")
        print("\nSection 14: fine-tune only what fails, only the recognition head, CTC loss.")
        return 0

    if not (args.speed or args.worksheet):
        parser.error("choose --speed, --worksheet or --cer")

    if not detect_text.is_available():
        print("the detector is not on this machine; run scripts/fetch_models.py")
        return 1

    paths = live_frames(millimetre_grade_only=not args.all_frames)
    if args.limit:
        paths = paths[: args.limit]
    print(f"{len(paths)} frames")

    if args.worksheet:
        written = write_worksheet(paths, args.worksheet)
        print(f"\nwrote {written} lines to {args.worksheet}")
        print("Fill in `truth` and `surface`. A blank `truth` is 'not checked' and is dropped.")
        print(f"Surfaces: {', '.join(SURFACES)}")
        return 0

    print("\nM4 half two -- ROI-only OCR against reading every region, same frames\n")
    header = (
        f"  {'scale':>18}  {'det px':>7}  {'regions':>8}  {'crops':>6}  "
        f"{'ROI ms':>8}  {'all ms':>8}  {'x':>6}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))

    results = {}
    # Tier C first, then the scale the real pipeline recovers from the marker.
    # Reported together because the gap between them is the finding.
    for label, scale in (("tier C (no marker)", None), (f"{args.mm_per_px} mm/px", args.mm_per_px)):
        result = measure_speed(paths, mm_per_px=scale)
        results[label] = result
        print(
            f"  {label:>18}  {result['detector_input_px']:7.0f}  "
            f"{result['median_regions']:8.0f}  {result['median_crops']:6.0f}  "
            f"{result['roi_median_ms']:8.1f}  {result['all_regions_median_ms']:8.1f}  "
            f"{result['speedup']:6.2f}"
        )

    best = max(r["speedup"] for r in results.values())
    print(f"\nSection 17 M4 asks for at least 5x. Met: {best >= 5.0}  (best {best:.2f}x)")
    print(
        "\n  The two rows differ only in the detector's input size, which section 8b\n"
        "  derives from the recovered scale. More input pixels means more regions\n"
        "  proposed, the ROI path still reads its eight, and the saving grows. The\n"
        "  ROI argument is therefore strongest exactly where the pipeline is\n"
        "  healthiest -- and at tier C, where it is weakest, there is less to skip."
    )
    print(
        f"\n  (For completeness: handing a whole frame to the recognition head as one\n"
        f"   crop costs {results['tier C (no marker)']['degenerate_whole_frame_ms']:.1f} ms "
        f"and reads essentially nothing -- the head resizes its\n"
        f"   input to 48 px. That is not the comparison section 4 makes.)"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
