"""Take delivery of the declaration-block set and hash it. AKSHAR.md §16, §18.

    python scripts/ingest_declaration_blocks.py "38_images_asked withproperlabelling"
    python scripts/ingest_declaration_blocks.py "<drop>" --dry-run
    python scripts/ingest_declaration_blocks.py --manifest-only

---------------------------------------------------------------------------
WHY THIS IS NOT `ingest_originals.py`
---------------------------------------------------------------------------
That script builds the *training* corpus, and everything in it exists to answer
one question: is this frame millimetre-grade, or did a messaging app destroy the
two numbers that make a pixel measurable? It matches transcodes to camera
originals by dHash, reads EXIF, and records which frame supersedes which.

This set answers a different question and needs none of that. These 38
photographs are an **evaluation set with per-image field labels**: for each one,
a human has read the panel and written down which of the statutory declarations
are printed on it and what they say. Nothing here is trained on. Nothing here is
measured in millimetres — several frames are e-commerce renders with no EXIF at
all, and the labels are about *text*, which survives a transcode intact.

So the provenance this script records is the provenance that matters for a
labelled set: the SHA-256 of every image as delivered, so that a score reported
six months from now can be shown to have been computed against these exact
bytes, and so a re-delivery that quietly swaps a file is caught rather than
averaged in.

---------------------------------------------------------------------------
FILENAMES ARE NORMALISED; THE ORIGINAL IS KEPT
---------------------------------------------------------------------------
The drop contains `coconut oil.jpg`, `liquid detergent.jpg` and `venus
creme.webp`. Spaces in a path are a running source of quoting bugs in shell
pipelines and in the CSV/JSON round trips this set will go through, so the
stored name is lowercased and underscored. `source_filename` keeps what was
delivered, because that is what the photographer will call it when we ask them
about it.

**Bytes are copied, never re-encoded.** `Path.write_bytes`, not Pillow, for the
reason `ingest_originals.py` gives at length: opening and saving re-quantises
the image, and then the SHA-256 in the manifest is the hash of our copy rather
than of what we were given, which makes it worthless as a provenance claim.
`.webp` frames stay `.webp`; OpenCV decodes them and converting to JPEG would
add a generation of loss to eight of the thirty-eight images for no gain.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

DEST = ROOT / "data" / "declaration_blocks"
IMAGES = DEST / "images"
MANIFEST = DEST / "manifest.json"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def normalise(name: str) -> str:
    """`venus creme.webp` -> `venus_creme.webp`. Suffix lowercased, never changed."""
    stem, _, suffix = name.rpartition(".")
    stem = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")
    return f"{stem}.{suffix.lower()}"


@dataclass
class Block:
    """One delivered photograph of a declaration panel."""

    image: str
    """Filename under `data/declaration_blocks/images/`. The key everything joins on."""

    source_filename: str
    """As delivered. Kept because it is what the photographer will call it."""

    sha256: str
    width: int
    height: int
    megapixels: float
    bytes: int


def measure(data: bytes, source_filename: str) -> Block | None:
    array = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        return None
    height, width = image.shape[:2]
    return Block(
        image=normalise(source_filename),
        source_filename=source_filename,
        sha256=hashlib.sha256(data).hexdigest(),
        width=width,
        height=height,
        megapixels=round(width * height / 1e6, 2),
        bytes=len(data),
    )


def collect(source: Path) -> tuple[list[tuple[Block, bytes]], list[str]]:
    found: list[tuple[Block, bytes]] = []
    unreadable: list[str] = []
    for path in sorted(source.iterdir()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        data = path.read_bytes()
        block = measure(data, path.name)
        if block is None:
            unreadable.append(path.name)
            continue
        found.append((block, data))
    return found, unreadable


def existing() -> list[Block]:
    if not IMAGES.is_dir():
        return []
    blocks: list[Block] = []
    for path in sorted(IMAGES.iterdir()):
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        block = measure(path.read_bytes(), path.name)
        if block is not None:
            blocks.append(block)
    return blocks


def build_manifest(blocks: list[Block], delivered_from: str | None) -> dict[str, object]:
    return {
        "schema": 1,
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan_section": "18",
        "note": (
            "Declaration-block evaluation set. One photograph per pack, each showing "
            "the statutory declaration panel. Labelled by hand in ground_truth.json; "
            "never trained on. The images are gitignored, this manifest is tracked, "
            "so a score can be tied to the exact bytes it was computed against."
        ),
        "delivered_from": delivered_from,
        "counts": {
            "images": len(blocks),
            "by_suffix": {
                suffix: sum(1 for b in blocks if b.image.endswith(suffix))
                for suffix in sorted({b.image.rpartition(".")[2] for b in blocks})
            },
        },
        "images": [asdict(block) for block in sorted(blocks, key=lambda b: b.image)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", help="folder of delivered photographs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="rebuild the manifest from what is already in data/declaration_blocks/",
    )
    args = parser.parse_args()

    if args.manifest_only:
        blocks = existing()
        MANIFEST.write_text(
            json.dumps(build_manifest(blocks, None), indent=2) + "\n", encoding="utf-8"
        )
        print(f"manifest rebuilt from {len(blocks)} images already on disk")
        return 0

    if not args.source:
        parser.error("give a source folder, or --manifest-only")

    source = Path(args.source)
    if not source.is_dir():
        print(f"not a directory: {source}", file=sys.stderr)
        return 1

    found, unreadable = collect(source)
    for name in unreadable:
        print(f"  SKIPPED (cannot decode): {name}", file=sys.stderr)

    names = [block.image for block, _ in found]
    clashes = {name for name in names if names.count(name) > 1}
    if clashes:
        print(f"filename clash after normalising: {sorted(clashes)}", file=sys.stderr)
        return 1

    copied = skipped = 0
    if not args.dry_run:
        IMAGES.mkdir(parents=True, exist_ok=True)
    for block, data in found:
        target = IMAGES / block.image
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == block.sha256:
            skipped += 1
            continue
        if not args.dry_run:
            target.write_bytes(data)
        copied += 1

    print(f"{len(found)} images read from {source}")
    print(f"  {copied} copied, {skipped} already present and identical")
    if args.dry_run:
        print("  --dry-run: nothing written")
        return 0

    MANIFEST.write_text(
        json.dumps(build_manifest(existing(), str(source)), indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"  manifest written to {MANIFEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
