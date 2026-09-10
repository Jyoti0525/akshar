"""Move the ruler set into `data/test_split/` and derive its ground truth.

    python -m scripts.seal_test_split 40_ruler_images

**This is the set AKSHAR.md section 19 calls the day-7 go/no-go**, and the data
tree calls "RULER GROUND TRUTH -- DO NOT TRAIN ON". Forty photographs, twenty
packets, two shots each, every one with the ChArUco card in frame and the MRP
declaration measured with a steel rule. There is no second copy of it: the
packets go back in the cupboard, the light changes, and a reshoot is a
different measurement. So this script **copies rather than moves**, and refuses
to overwrite a frame that is already sealed.

**The ground truth lives in the folder names**, which is why they are parsed
here rather than retyped. The photographer named each folder

    <product>_<pack size>_mrpsize=<height in mm>

and that name is the only record of what the rule read. Retyping forty numbers
into a spreadsheet is one transcription step, and a transcription step in the
ground truth is a silent error in the headline accuracy figure -- it would show
up as a large error on one frame and be indistinguishable from a bad
measurement by the pipeline. Parsing the name keeps the number the
photographer wrote.

The original folder name is carried into the `notes` column verbatim, so the
derivation is reversible by eye.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIELDS = ("filename", "product", "pack_size", "field", "character", "measured_mm", "notes")
"""Column order of `ground_truth.csv`, matching `scripts/u1_report.py`."""

_PACK_SIZE = re.compile(r"^\s*\d+(?:\.\d+)?\s*(?:mg|g|kg|ml|l|unit|units|pcs)\s*$", re.I)
_MEASURED = re.compile(r"^mr?p?size=(\d+(?:\.\d+)?)$", re.I)
"""`mrpsize=2`, and the one folder typed `mrsize=1`.

The typo is matched deliberately rather than corrected on disk. Renaming the
photographer's folder to fix a spelling would edit the only record of the
measurement, and the number -- which is the part that matters -- was never in
doubt."""

_TILT = re.compile(r"tilt", re.I)


@dataclass(frozen=True, slots=True)
class Frame:
    source: Path
    destination: Path
    product: str
    pack_size: str
    measured_mm: float
    shot: str
    folder: str


def parse_folder(name: str) -> tuple[str, str, float]:
    """`bodywash bottle_300ml_mrpsize=2` -> `("bodywash bottle", "300ml", 2.0)`.

    Raises rather than guessing. A folder this cannot read is a folder whose
    ground truth we do not know, and inventing one would put a fabricated
    number into the accuracy claim.
    """
    parts = name.split("_")
    measured = _MEASURED.match(parts[-1].strip())
    if measured is None:
        raise ValueError(
            f"{name!r} does not end in a measured height like `mrpsize=2.5`; "
            f"the ruler reading for this packet is not recorded anywhere else"
        )

    rest = [part for part in parts[:-1] if part.strip()]
    pack_size = ""
    if rest and _PACK_SIZE.match(rest[-1]):
        pack_size = rest[-1].strip()
        rest = rest[:-1]

    product = " ".join(rest).strip()
    if not product:
        raise ValueError(f"{name!r} names no product")
    return product, pack_size, float(measured.group(1))


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def plan(source_root: Path, images_dir: Path) -> list[Frame]:
    """Work out every copy before making one, so a bad folder stops the run."""
    frames: list[Frame] = []
    for folder in sorted(p for p in source_root.iterdir() if p.is_dir()):
        product, pack_size, measured_mm = parse_folder(folder.name)
        name = slug(f"{product} {pack_size}" if pack_size else product)

        shots = sorted(
            p for p in folder.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )
        seen: set[str] = set()
        for image in shots:
            shot = "tilt" if _TILT.search(image.stem) else "front"
            if shot in seen:
                raise ValueError(
                    f"{folder.name!r} holds two {shot} shots ({image.name}); "
                    f"section 19 wants one of each so repeatability is measurable"
                )
            seen.add(shot)
            frames.append(
                Frame(
                    source=image,
                    destination=images_dir / name / f"{shot}.jpg",
                    product=product,
                    pack_size=pack_size,
                    measured_mm=measured_mm,
                    shot=shot,
                    folder=folder.name,
                )
            )
        if seen != {"front", "tilt"}:
            raise ValueError(
                f"{folder.name!r} has only {sorted(seen)}; the pair is what makes "
                f"repeatability separable from ruler error (see u1_report)"
            )
    return frames


def rows_for(frames: list[Frame], root: Path) -> list[dict[str, str]]:
    return [
        {
            "filename": frame.destination.relative_to(root).as_posix(),
            "product": frame.product,
            "pack_size": frame.pack_size,
            "field": "mrp",
            "character": "",
            "measured_mm": f"{frame.measured_mm:g}",
            "notes": f"{frame.shot} shot; source folder {frame.folder!r}",
        }
        for frame in frames
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="the photographer's folder tree")
    parser.add_argument("--into", type=Path, default=ROOT / "data" / "test_split")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite frames already sealed (default: refuse, and say which)",
    )
    args = parser.parse_args()

    if not args.source.is_dir():
        print(f"{args.source} is not a directory")
        return 1

    images_dir = args.into / "images"
    try:
        frames = plan(args.source, images_dir)
    except ValueError as exc:
        print(f"refusing to seal an incomplete set: {exc}")
        return 1

    existing = [f.destination for f in frames if f.destination.exists()]
    if existing and not args.force:
        print(f"{len(existing)} frames are already sealed, first {existing[0]}")
        print("re-run with --force only if you mean to replace the ruler set")
        return 1

    for frame in frames:
        frame.destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(frame.source, frame.destination)

    rows = rows_for(frames, args.into)
    ground_truth = args.into / "ground_truth.csv"
    with ground_truth.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    skus = {(f.product, f.pack_size) for f in frames}
    print(f"sealed {len(frames)} frames over {len(skus)} SKUs into {images_dir}")
    print(f"wrote {ground_truth}")
    print(f"\nthe source tree at {args.source} is now a duplicate and can be removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
