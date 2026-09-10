"""Pre-annotate the detection corpus so a human corrects rather than draws.

Section 16 wants five things marked on each of 469 photographs: the package
box, the PDP polygon, the other panel polygons, one box per declaration with
its field and script, and a box on the marker card. Drawn from scratch that is
days of work. Corrected from a proposal it is hours, and correction is the
better task for a person anyway -- judging a box is faster and more consistent
than placing one.

**These are proposals, not labels.** Nothing here is ground truth and nothing
here may be trained on unconfirmed. Every region is emitted into Label Studio's
`predictions` block rather than its `annotations` block, which is the
difference between "the machine thinks" and "a human says" and is enforced by
the tool: predictions show up for correction and are never exported as truth
until a person has accepted them.

What the proposals are worth, honestly, differs by field:

* **Declaration boxes** come from the real detector and are usually well
  placed. Their *field names* come from the regex tier and are frequently
  wrong -- `other` is emitted whenever the text did not match, which on small
  or garbled print is most of the time. Expect to retype many.
* **The package box** is the union of detected text, which is a decent
  approximation only because packs fill most of these frames. It will be loose.
* **Panels** are not proposed at all. Nothing in the pipeline can guess a panel
  before the detector this corpus exists to train, and a confident wrong
  polygon is worse than an empty one -- a person correcting a plausible mistake
  is slower than a person drawing on an empty image.

**Which frames it walks, and why it is not simply a directory.** The corpus is
two populations: camera originals at full sensor resolution, and the WhatsApp
transcodes that arrived first at a 1600 px long side. 221 of the transcodes have
since been superseded by the original of the same photograph, and annotating a
superseded copy is work thrown away -- the boxes would be drawn on a downscale
of a frame we hold at 2.56x the resolution, and no millimetre claim may ever be
drawn from them.

So the default source is `data/manifest.json` rather than a folder: every live
frame, originals preferred, superseded transcodes skipped. `--source images`
restores the old behaviour for anyone reproducing the first run.

Usage:

    python -m scripts.prelabel_corpus --out training/detector/tasks.json
    python -m scripts.prelabel_corpus --source images     # the pre-2026-09-09 set
    python -m scripts.prelabel_corpus --limit 20          # a taste, for checking

Then in Label Studio: create a project with `training/detector/label_config.xml`,
set up local file serving for `data/corpus` (note: the parent, so that both
`images/` and `originals/` resolve), and import the JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts import Box  # noqa: E402
from vision.classify import regex_tier  # noqa: E402
from vision.ocr import detect_text, recognise  # noqa: E402
from vision.ocr import script as script_mod  # noqa: E402

IMAGES = ROOT / "data" / "corpus" / "images"
ORIGINALS = ROOT / "data" / "corpus" / "originals"
MANIFEST = ROOT / "data" / "manifest.json"
DEFAULT_OUT = ROOT / "training" / "detector" / "tasks.json"

MODEL_VERSION = "akshar-prelabel-2"
"""Stamped on every proposal. Label Studio groups predictions by this, so a
later re-run with a better pipeline can be told apart from this one instead of
silently mixing two vintages of guess in the same project.

Bumped to 2 on 2026-09-09: the same pipeline, but run over the camera originals
rather than the messaging transcodes. The boxes are in percentages and would
have transferred, but the *text* behind the field names was read at 2.56x less
resolution, so the two vintages disagree about what a region says -- which is
exactly the thing this version number exists to keep separable."""

MAX_DECLARATIONS = 25
"""Per image. The pipeline's own budget is 8 because recognition is expensive;
here the budget is a person's patience, and a missed box costs them more than a
spurious one -- deleting is faster than drawing."""


def _rect(box, width: int, height: int, label: str, from_name: str) -> dict:
    """Label Studio rectangles are percentages of image size, not pixels."""
    return {
        "from_name": from_name,
        "to_name": "image",
        "type": "rectanglelabels",
        "original_width": width,
        "original_height": height,
        "image_rotation": 0,
        "value": {
            "x": 100.0 * box.x / width,
            "y": 100.0 * box.y / height,
            "width": 100.0 * box.w / width,
            "height": 100.0 * box.h / height,
            "rotation": 0,
            "rectanglelabels": [label],
        },
    }


def propose(path: Path) -> dict | None:
    image = cv2.imread(str(path))
    if image is None:
        return None
    height, width = image.shape[:2]

    regions, _, _ = detect_text.propose_regions(image)
    if not regions:
        return None
    regions = sorted(regions, key=lambda r: r.box.h, reverse=True)[:MAX_DECLARATIONS]

    result: list[dict] = []

    # The package: the extent of the text on it. Loose by construction, and
    # said to be loose in the module docstring rather than dressed up.
    x0 = min(r.box.x for r in regions)
    y0 = min(r.box.y for r in regions)
    x1 = max(r.box.x + r.box.w for r in regions)
    y1 = max(r.box.y + r.box.h for r in regions)

    package = Box(x=x0, y=y0, w=x1 - x0, h=y1 - y0)
    result.append(_rect(package, width, height, "package", "objects"))

    for region in regions:
        crop = image[
            max(int(region.box.y), 0) : int(region.box.y + region.box.h),
            max(int(region.box.x), 0) : int(region.box.x + region.box.w),
        ]
        if crop.size == 0:
            continue

        field, script_name = "other", None
        try:
            guess, _ = script_mod.detect_script(crop)
            read = recognise.recognise(crop, guess)
            if read and read.text.strip():
                # High precision, low recall, and that is the right shape for a
                # proposal: the patterns only fire on text that really looks
                # like the field, and everything else stays `other` rather than
                # becoming a confident guess a person has to argue with.
                field = regex_tier.classify_text(read.text, script=guess).field
            script_name = guess
        except Exception:
            # A proposal that cannot be made is simply not made. This script
            # must never fail a whole corpus because one crop was unreadable.
            pass

        entry = _rect(region.box, width, height, field, "declarations")
        result.append(entry)
        if script_name in {"latin", "devanagari", "other"}:
            result.append(
                {
                    "from_name": "script",
                    "to_name": "image",
                    "type": "choices",
                    "id": entry.get("id", ""),
                    "value": {"choices": [script_name]},
                }
            )

    return {
        # Relative to `data/`, because the two populations live in sibling
        # directories now and Label Studio's local-files root is the parent.
        # `as_posix()` matters: this JSON is read by a Linux container even when
        # it was written on Windows, and a backslash here is a 404 per task.
        "data": {"image": f"/data/local-files/?d={path.relative_to(ROOT / 'data').as_posix()}"},
        "predictions": [{"model_version": MODEL_VERSION, "result": result}],
    }


def frames_from_manifest() -> list[Path]:
    """Every live corpus frame, originals preferred, superseded transcodes dropped.

    `superseded_by` is set on a transcode when `scripts/ingest_originals.py`
    matched an original to it by dHash. Skipping those is the whole point:
    annotating both copies of one photograph would double the work and then
    disagree with itself at training time, because the two would carry
    independently-drawn boxes for the same shot.
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    frames = [
        frame
        for frame in manifest["frames"]
        if frame["set"] == "corpus" and frame.get("superseded_by") is None
    ]
    # Millimetre-grade first. An annotator who runs out of time has then spent
    # it on the frames a measurement may be drawn from, and `docs/annotation-
    # guide.md` tells them that is the order.
    frames.sort(key=lambda frame: (not frame["millimetre_grade"], frame["path"]))
    return [ROOT / frame["path"] for frame in frames]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-annotate the detection corpus.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=0, help="stop after N images")
    parser.add_argument(
        "--source",
        choices=("manifest", "originals", "images"),
        default="manifest",
        help="manifest: every live frame, originals preferred (default)",
    )
    args = parser.parse_args(argv)

    if not detect_text.is_available():
        print("the detector is not on this machine; run scripts/fetch_models.py")
        return 1

    if args.source == "manifest":
        if not MANIFEST.exists():
            print("no data/manifest.json; run scripts/ingest_originals.py --manifest-only")
            return 1
        paths = frames_from_manifest()
    else:
        directory = ORIGINALS if args.source == "originals" else IMAGES
        paths = sorted(
            path
            for pattern in ("*.jpeg", "*.jpg", "*.JPG", "*.JPEG", "*.png")
            for path in directory.glob(pattern)
        )
    if args.limit:
        paths = paths[: args.limit]
    print(f"{len(paths)} frames from {args.source}", flush=True)

    tasks, skipped = [], 0
    for n, path in enumerate(paths, 1):
        task = propose(path)
        if task is None:
            skipped += 1
        else:
            tasks.append(task)
        if n % 25 == 0 or n == len(paths):
            print(f"  {n}/{len(paths)}  proposed {len(tasks)}, skipped {skipped}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(tasks, indent=1), encoding="utf-8")

    boxes = sum(len(t["predictions"][0]["result"]) for t in tasks)
    print()
    print(f"{len(tasks)} tasks, {boxes} proposed regions -> {args.out}")
    print("These are proposals. A person confirms every one before it is truth.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
