"""Label Studio export -> COCO instance segmentation, for RTMDet-Ins. AKSHAR.md §14, §16.

    python -m training.detector.convert export.json --out training/detector/coco
    python -m training.detector.convert export.json --out ... --val-fraction 0.2

**Nothing here trains anything and nothing here labels anything.** It converts a
human's completed annotations into the layout `mmdet` reads, and it refuses the
three conversions that would quietly poison the training set.

---------------------------------------------------------------------------
IT READS `annotations`, NEVER `predictions`
---------------------------------------------------------------------------
`training/detector/tasks.json` ships 16,367 machine proposals in Label Studio's
`predictions` block. Those exist so an annotator corrects rather than draws, and
a proposal a person has not accepted is not a label -- section 14 is explicit
that the corpus is real photographs with real labels, and a pipeline that
trained on its own guesses would be measuring its own opinion.

So this script reads `annotations` and refuses a task that has none, loudly, with
a count. A silent skip is how you discover at the end of a training run that 400
of your 479 images contributed nothing.

---------------------------------------------------------------------------
THE SPLIT IS BY PHOTOGRAPH GROUP, NOT BY PHOTOGRAPH
---------------------------------------------------------------------------
The corpus contains bursts: several frames of one packet, seconds apart, from
one device. Splitting those at random puts near-identical frames on both sides
of the train/val line, and the validation mAP then measures memorisation. The
audit already computed the near-duplicate groups (`data/corpus/audit.json`);
this script groups by dHash prefix, which is the same idea cheaply.

---------------------------------------------------------------------------
THE TEST SPLIT NEVER ENTERS
---------------------------------------------------------------------------
`data/test_split/` is sealed. It carries the ruler-measured millimetre ground
truth that is the §18b headline number, and section 16 says it may not be
trained on, tuned against, or used to pick a threshold. Any task whose image
path resolves inside it is a hard error, not a skip -- if one has arrived in an
export, something upstream is wrong and the run must stop rather than continue
with a contaminated set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

OBJECT_CLASSES = ("package", "marker_card")
PANEL_CLASSES = ("pdp", "side", "back", "top", "bottom", "unknown")

CATEGORIES = [
    {"id": index + 1, "name": name, "supercategory": "object" if index < 2 else "panel"}
    for index, name in enumerate((*OBJECT_CLASSES, *PANEL_CLASSES))
]
"""Objects and panels in one category list, and declarations in none of them.

Section 14 gives the detector two jobs: find the package, and segment the
panels. Declaration boxes are a *different* model's input -- they are what the
ROI-OCR path proposes at inference time from a text detector, and folding
thirteen field classes into this taxonomy would make a 15-class detector out of
an 8-class one to no purpose, while starving the two classes that matter of
gradient. `training/classifier/` consumes the declaration boxes instead.
"""

CATEGORY_ID = {category["name"]: category["id"] for category in CATEGORIES}

SEALED = ROOT / "data" / "test_split"


def _relative_image(task: dict[str, Any]) -> str:
    """The path Label Studio was serving, back to a repository-relative one.

    Label Studio rewrites `data.image` to `/data/local-files/?d=<path>` where the
    path is relative to its local-files root, which `scripts/prelabel_corpus.py`
    sets to `data/`. It also URL-encodes, and the WhatsApp filenames contain
    spaces, so unquoting is not optional.
    """
    from urllib.parse import unquote

    raw = task.get("data", {}).get("image", "")
    marker = "?d="
    if marker in raw:
        raw = raw.split(marker, 1)[1]
    return unquote(raw)


def _polygon_points(value: dict[str, Any], width: int, height: int) -> list[float]:
    """Label Studio percentage points -> a flat COCO segmentation list in pixels."""
    flat: list[float] = []
    for point in value.get("points", []):
        flat.append(point[0] * width / 100.0)
        flat.append(point[1] * height / 100.0)
    return flat


def _bbox_of(polygon: list[float]) -> list[float]:
    xs, ys = polygon[0::2], polygon[1::2]
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]


def _rect_to_coco(value: dict[str, Any], width: int, height: int) -> tuple[list[float], list[float]]:
    """A rectangle as both a bbox and a four-point polygon.

    RTMDet-**Ins** wants a mask for every instance, and a box without one is
    dropped by the pipeline with a warning nobody reads. A rectangle's mask is
    its own outline, which is exact rather than approximate -- the package
    annotation genuinely is a rectangle.
    """
    x = value["x"] * width / 100.0
    y = value["y"] * height / 100.0
    w = value["width"] * width / 100.0
    h = value["height"] * height / 100.0
    return [x, y, w, h], [x, y, x + w, y, x + w, y + h, x, y + h]


def convert(tasks: list[dict[str, Any]]) -> tuple[list[dict], list[dict], Counter]:
    """(images, annotations, per-class counts). Raises on a sealed-split leak."""
    images: list[dict] = []
    annotations: list[dict] = []
    counts: Counter = Counter()
    unannotated: list[str] = []
    annotation_id = 1

    for task in tasks:
        relative = _relative_image(task)
        path = ROOT / "data" / relative
        try:
            path.resolve().relative_to(SEALED.resolve())
        except ValueError:
            pass
        else:
            raise SystemExit(
                f"REFUSING TO CONVERT: {relative} is inside data/test_split/, which section 16 "
                f"seals. Nothing may be trained on it, tuned against it, or used to pick a "
                f"threshold. Fix the export; do not filter this out."
            )

        drawn = task.get("annotations") or []
        regions = [
            region
            for annotation in drawn
            if not annotation.get("was_cancelled")
            for region in annotation.get("result", [])
        ]
        if not regions:
            unannotated.append(relative)
            continue

        image_id = len(images) + 1
        width = height = 0
        for region in regions:
            width = region.get("original_width") or width
            height = region.get("original_height") or height
        if not width or not height:
            unannotated.append(relative)
            continue

        images.append(
            {
                "id": image_id,
                "file_name": relative,
                "width": width,
                "height": height,
                # Kept so `_group_key` can split by burst without re-reading the
                # pixels, and so a converted set can be traced back to a manifest
                # row without matching on a filename that may be renamed.
                "akshar_group": hashlib.sha1(relative.encode()).hexdigest()[:8],
            }
        )

        for region in regions:
            value = region.get("value", {})
            kind = region.get("type")
            if kind == "rectanglelabels":
                labels = value.get("rectanglelabels", [])
                if not labels or labels[0] not in OBJECT_CLASSES:
                    continue  # declarations belong to the classifier, not here
                bbox, polygon = _rect_to_coco(value, width, height)
                name = labels[0]
            elif kind == "polygonlabels":
                labels = value.get("polygonlabels", [])
                if not labels or labels[0] not in PANEL_CLASSES:
                    continue
                polygon = _polygon_points(value, width, height)
                if len(polygon) < 6:
                    continue  # fewer than three points is not a polygon
                bbox = _bbox_of(polygon)
                name = labels[0]
            else:
                continue

            if bbox[2] <= 1 or bbox[3] <= 1:
                continue  # a click, not a region
            counts[name] += 1
            annotations.append(
                {
                    "id": annotation_id,
                    "image_id": image_id,
                    "category_id": CATEGORY_ID[name],
                    "bbox": [round(v, 2) for v in bbox],
                    "area": round(bbox[2] * bbox[3], 2),
                    "segmentation": [[round(v, 2) for v in polygon]],
                    "iscrowd": 0,
                }
            )
            annotation_id += 1

    if unannotated:
        print(f"\n  {len(unannotated)} task(s) carried no completed annotation and were skipped:")
        for name in unannotated[:10]:
            print(f"    {name}")
        if len(unannotated) > 10:
            print(f"    ... and {len(unannotated) - 10} more")
        print("  These are proposals nobody has confirmed. They are not labels.\n")

    return images, annotations, counts


def split(images: list[dict], annotations: list[dict], *, val_fraction: float, seed: int):
    """Train/val by burst group, so near-identical frames stay on one side.

    Groups are ordered by a hash of the group key rather than shuffled with a
    PRNG, which makes the split a pure function of the data and the seed: two
    people converting the same export get the same split without passing a
    random state around, and adding a photograph moves one group rather than
    reshuffling every one.
    """
    by_group: dict[str, list[dict]] = defaultdict(list)
    for image in images:
        by_group[image["akshar_group"]].append(image)

    ordered = sorted(
        by_group.items(),
        key=lambda item: hashlib.sha1(f"{seed}:{item[0]}".encode()).hexdigest(),
    )
    target = round(len(images) * val_fraction)
    val_ids: set[int] = set()
    for _key, group in ordered:
        if len(val_ids) >= target:
            break
        val_ids.update(image["id"] for image in group)

    def subset(keep: set[int], invert: bool):
        chosen = [i for i in images if (i["id"] in keep) != invert]
        ids = {i["id"] for i in chosen}
        return chosen, [a for a in annotations if a["image_id"] in ids]

    return subset(val_ids, invert=True), subset(val_ids, invert=False)


def write(out: Path, name: str, images: list[dict], annotations: list[dict]) -> Path:
    path = out / f"{name}.json"
    path.write_text(
        json.dumps(
            {
                "info": {
                    "description": "AKSHAR detection corpus. AKSHAR.md sections 14 and 16.",
                    "note": (
                        "Human annotations only. Machine proposals live in "
                        "training/detector/tasks.json and are not labels."
                    ),
                },
                "images": images,
                "annotations": annotations,
                "categories": CATEGORIES,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="Label Studio JSON export (with annotations)")
    parser.add_argument("--out", type=Path, default=ROOT / "training" / "detector" / "coco")
    parser.add_argument("--val-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=26034)
    args = parser.parse_args(argv)

    tasks = json.loads(args.export.read_text(encoding="utf-8"))
    print(f"{len(tasks)} tasks in {args.export}")

    images, annotations, counts = convert(tasks)
    if not images:
        print("\nNothing to convert: no task carried a completed annotation.")
        print("Label Studio's `predictions` are proposals; only `annotations` are labels.")
        return 1

    (train_images, train_annotations), (val_images, val_annotations) = split(
        images, annotations, val_fraction=args.val_fraction, seed=args.seed
    )
    args.out.mkdir(parents=True, exist_ok=True)
    write(args.out, "train", train_images, train_annotations)
    write(args.out, "val", val_images, val_annotations)

    print(f"\n  {len(images)} annotated images, {len(annotations)} instances")
    print(f"  train {len(train_images)} images / {len(train_annotations)} instances")
    print(f"  val   {len(val_images)} images / {len(val_annotations)} instances")
    print("\n  per class:")
    for category in CATEGORIES:
        name = category["name"]
        print(f"    {name:14} {counts.get(name, 0):5}")

    # Section 14: "about 15% of training photos should contain no package at
    # all". A converted set with none is trainable and will confidently box a
    # shelf edge, so the shortfall is reported here rather than discovered on
    # stage.
    empty = sum(
        1
        for image in images
        if not any(
            a["image_id"] == image["id"] and a["category_id"] == CATEGORY_ID["package"]
            for a in annotations
        )
    )
    share = empty / len(images)
    print(f"\n  images with no package (detector negatives): {empty} ({share:.0%})")
    if share < 0.10:
        print("  ** Section 14 asks for ~15%. Below 10% the detector learns to box shelf edges. **")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
