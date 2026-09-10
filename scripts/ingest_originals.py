"""Take delivery of camera originals and rebuild `data/manifest.json`. AKSHAR.md §14, §16.

    python scripts/ingest_originals.py "new original images"
    python scripts/ingest_originals.py "new original images" --dry-run
    python scripts/ingest_originals.py --manifest-only

**Why this is a separate script from `audit_corpus.py`.** The audit measures a
directory and reports on it. This one changes what the directory *is*, and the
change it makes is a provenance claim: that a particular full-resolution frame
is the same photograph as a particular transcoded one, and supersedes it. That
claim is the entire reason the originals were asked for, so it is made in code
that can be re-run and argued with rather than by dragging files around.

---------------------------------------------------------------------------
THE PROBLEM THIS EXISTS TO SOLVE
---------------------------------------------------------------------------
The first 469 photographs arrived through WhatsApp, which is not a file
transfer: it re-encodes to a 1600 px long side, strips EXIF wholesale, and
converts to progressive JPEG. `docs/corpus.md` records the measurement. Those
frames are fine for detection, panel segmentation and text detection, all of
which are scale-free. They are useless for anything that has to reason in
millimetres, because the two facts that make a pixel measurable — the sensor
resolution it was captured at, and the focal length it was captured with — are
exactly the two the transcode destroys.

So the corpus is now two populations with different capabilities, and the point
of the manifest is that no downstream script has to guess which is which. A
frame carries `millimetre_grade: true` or it does not, and §18b's ground truth
may only be drawn from the ones that do.

---------------------------------------------------------------------------
MATCHING, AND WHY IT IS dHASH RATHER THAN A FILENAME
---------------------------------------------------------------------------
WhatsApp renames everything to its own timestamp of *sending*, so the only link
back to `IMG_0639.JPG` is the picture itself. dHash at 8x8 compares layout after
a heavy downscale, which is precisely the invariant a transcode preserves and a
different shot of the same product does not.

The threshold is 10 bits, the same one `audit_corpus.py` uses, and the match is
reported with its distance so the tail can be inspected rather than trusted: in
the delivery of 2026-09-09, 290 of 362 matches were at distance 0 and the worst
was 5, which is a transcode-pair distribution and not a coincidence one. A frame
whose nearest neighbour is further than the threshold is recorded as having no
counterpart, which is a fact worth having — it is how we know 248 of the 469
still have no original behind them.

**Nothing is deleted.** The transcoded frame stays where it is even once
superseded. `training/detector/tasks.json` holds 16,285 pre-labelled regions
keyed on those filenames; the coordinates are percentages and therefore survive
a resolution change, but the keys do not, and throwing away the only copy of a
photograph to save 70 MB would be a poor trade in any case.

---------------------------------------------------------------------------
BYTES ARE COPIED, NEVER RE-ENCODED
---------------------------------------------------------------------------
`Path.write_bytes`, not Pillow. Opening and saving a JPEG re-quantises it and
rewrites the EXIF block through Pillow's own serialiser, and this script exists
because somebody else's re-encode destroyed the corpus once already. The SHA-256
in the manifest is therefore the hash of the file as it left the camera, which
is also what makes the ingest idempotent: a second run recognises every frame it
already holds and copies nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import ExifTags, Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}

NEAR_DUPLICATE_BITS = 10
"""Same threshold as `audit_corpus.py`. Kept equal on purpose: if the two
scripts disagreed about what "the same photograph" means, the manifest would
contradict the audit and there would be no way to tell which was right."""

MILLIMETRE_GRADE_MIN_SIDE = 2400
"""Long side below which a frame is not offered to millimetre work.

Not a resolution snobbery threshold — a transcode detector. Every phone in this
corpus captures at 4032 or 4096 px; WhatsApp's ceiling is 1600. Nothing lands
between the two by accident, so any value in the wide gap separates the
populations. It is set well above 1600 rather than just above it so that a
future messaging app with a 2048 px ceiling is also caught."""

CORPUS_TARGETS: dict[str, dict[str, Any]] = {
    "distinct_skus": {"target": 100, "unit": "SKUs", "source": "annotation"},
    "photos": {"target": 400, "unit": "photos", "source": "count"},
    "detector_negatives": {"target": 60, "unit": "photos", "source": "annotation"},
    "curved_surfaces": {"target": 0.25, "unit": "fraction", "source": "annotation"},
    "foil_or_reflective": {"target": 0.15, "unit": "fraction", "source": "annotation"},
    "hindi_or_bilingual": {"target": 0.25, "unit": "fraction", "source": "annotation"},
    "hard_negatives": {"target": 30, "unit": "photos", "source": "annotation"},
    "non_food": {"target": 0.30, "unit": "fraction", "source": "annotation"},
    "test_split_ruler": {"target": 40, "unit": "photos", "source": "count"},
    "test_split_skus": {"target": 20, "unit": "SKUs", "source": "count"},
}
"""§16's corpus table, verbatim, as machine-readable rows.

`source` is the honest half. `count` means this script can answer it by
counting files. `annotation` means it cannot — nothing here knows whether a
surface is curved or a declaration is bilingual, and a heuristic that guessed
would put a fabricated number in the one document whose job is to say what we
actually have. Those rows report `null` until Label Studio fills them, and
`unmet` is not the same as `unknown`."""


@dataclass
class Frame:
    """One photograph in the dataset, and everything known about its provenance."""

    path: str
    """Repository-relative, forward slashes, so the manifest reads the same on
    every platform and diffs cleanly."""

    set: str
    """`corpus`, `test_split` or `negatives`."""

    origin: str
    """`camera` for a file that came off a device, `messaging_transcode` for one
    that came through WhatsApp. This is the field everything else keys on."""

    sha256: str
    dhash: str
    width: int
    height: int
    megapixels: float
    bytes: int
    millimetre_grade: bool
    """May §18b's ground truth be drawn from this frame? Requires both an intact
    EXIF block and a long side above the transcode threshold — either alone is
    forgeable by a tool that copies metadata onto a downscale."""

    device: str | None = None
    captured_at: str | None = None
    focal_mm: float | None = None
    focal_35mm: int | None = None
    exif_tags: int = 0
    supersedes: str | None = None
    """Path of the transcoded frame this original replaces, if one was found."""

    superseded_by: str | None = None
    match_distance: int | None = None
    """Hamming distance of the supersede link. Kept so the tail of the
    distribution can be re-examined without re-running the whole ingest."""


def dhash_int(image: np.ndarray, size: int = 8) -> int:
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(grey, (size + 1, size), interpolation=cv2.INTER_AREA)
    bits = resized[:, 1:] > resized[:, :-1]
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bit)
    return value


def _clean(value: Any) -> str | None:
    """EXIF strings are fixed-width and NUL-padded by most Android vendors.

    `LAVA\\x00\\x00...` is what `Make` actually contains; left alone it makes the
    manifest unreadable and every `Counter` over devices wrong.
    """
    if value is None:
        return None
    text = str(value).replace("\x00", "").strip()
    return text or None


def read_exif(data: bytes) -> dict[str, Any]:
    try:
        exif = Image.open(io.BytesIO(data)).getexif()
    except Exception:  # a frame with unreadable EXIF is still a frame
        return {"exif_tags": 0}
    tags = {ExifTags.TAGS.get(key, key): value for key, value in exif.items()}
    sub = exif.get_ifd(0x8769)
    make, model = _clean(tags.get("Make")), _clean(tags.get("Model"))
    device = " ".join(part for part in (make, model) if part) or None
    # A model name that already starts with the maker ("LAVA LXX504") would read
    # as "LAVA LAVA LXX504" if the two were concatenated blindly.
    if make and model and model.upper().startswith(make.upper()):
        device = model
    focal = sub.get(0x920A)
    focal35 = sub.get(0xA405)
    return {
        "device": device,
        "captured_at": _clean(sub.get(0x9003) or tags.get("DateTime")),
        "focal_mm": round(float(focal), 3) if focal else None,
        # A 35 mm equivalent of 0 is how MediaTek's camera app says "not
        # recorded"; storing it as 0 would let somebody divide by it later.
        "focal_35mm": int(focal35) if focal35 else None,
        "exif_tags": len(tags) + len(sub),
    }


def measure(data: bytes, path: str, set_name: str, origin: str) -> Frame | None:
    array = np.frombuffer(data, np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        return None
    height, width = int(image.shape[0]), int(image.shape[1])
    exif = read_exif(data)
    return Frame(
        path=path,
        set=set_name,
        origin=origin,
        sha256=hashlib.sha256(data).hexdigest(),
        dhash=f"{dhash_int(image):016x}",
        width=width,
        height=height,
        megapixels=round(width * height / 1e6, 2),
        bytes=len(data),
        millimetre_grade=(
            exif["exif_tags"] > 4 and max(width, height) >= MILLIMETRE_GRADE_MIN_SIDE
        ),
        **{k: v for k, v in exif.items() if k != "exif_tags"},
        exif_tags=exif["exif_tags"],
    )


@dataclass
class Delivery:
    """What a source directory turned out to contain, before anything is copied."""

    files: list[tuple[str, bytes]] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)


def collect(source: Path) -> Delivery:
    """Every image under `source`, including inside any zip, deduplicated by content.

    Zips are walked rather than skipped because that is how the delivery of
    2026-09-09 arrived: 231 loose files plus a 324 MB archive whose 151 members
    were byte-for-byte copies of 151 of the loose ones. Unpacking it by hand
    would have doubled a third of the corpus silently.
    """
    delivery = Delivery()
    seen: set[str] = set()

    def offer(name: str, data: bytes) -> None:
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            delivery.duplicates.append(name)
            return
        seen.add(digest)
        delivery.files.append((name, data))

    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in IMAGE_SUFFIXES:
            offer(path.name, path.read_bytes())
        elif path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                for member in sorted(archive.namelist()):
                    if Path(member).suffix.lower() in IMAGE_SUFFIXES:
                        offer(Path(member).name, archive.read(member))
    return delivery


def existing_frames(directory: Path, set_name: str, origin: str) -> list[Frame]:
    frames = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            frame = measure(
                path.read_bytes(), path.relative_to(ROOT).as_posix(), set_name, origin
            )
            if frame is not None:
                frames.append(frame)
    return frames


def link_supersedes(originals: list[Frame], transcodes: list[Frame]) -> int:
    """Point each original at the transcoded frame it replaces. Mutates both.

    Greedy nearest-neighbour, and deliberately not a global assignment: a
    transcode may legitimately be claimed by only one original, but two
    originals of the same shot (burst frames) will both sit at distance 0 from
    it, and the first one is as good a choice as any. What matters is that the
    *transcode* is claimed once, so the count of superseded frames is not
    inflated by ties.
    """
    taken: set[str] = set()
    linked = 0
    for original in originals:
        best: Frame | None = None
        best_distance = 65
        left = int(original.dhash, 16)
        for candidate in transcodes:
            if candidate.path in taken:
                continue
            distance = bin(left ^ int(candidate.dhash, 16)).count("1")
            if distance < best_distance:
                best_distance, best = distance, candidate
        if best is not None and best_distance <= NEAR_DUPLICATE_BITS:
            original.supersedes = best.path
            original.match_distance = best_distance
            best.superseded_by = original.path
            best.match_distance = best_distance
            taken.add(best.path)
            linked += 1
    return linked


def tracker(frames: list[Frame]) -> list[dict[str, Any]]:
    """§16's corpus table with our own numbers beside it, and `null` where we cannot count.

    The distinction between `false` and `null` in `met` is the whole value of
    this table. `false` means we counted and fell short; `null` means the fact
    lives in an annotation nobody has drawn yet. Reporting the second as the
    first would make the dataset look worse than it is; reporting it as `true`
    would be a fabrication, which §14 forbids in more words than this.
    """
    corpus = [f for f in frames if f.set == "corpus" and f.superseded_by is None]
    split = [f for f in frames if f.set == "test_split"]
    negatives = [f for f in frames if f.set == "negatives"]
    have: dict[str, int | None] = {
        "photos": len(corpus),
        "test_split_ruler": len(split),
        "test_split_skus": len({Path(f.path).parent.name for f in split}),
        "detector_negatives": len(negatives) or None,
        "distinct_skus": None,
        "curved_surfaces": None,
        "foil_or_reflective": None,
        "hindi_or_bilingual": None,
        "hard_negatives": None,
        "non_food": None,
    }
    rows = []
    for name, spec in CORPUS_TARGETS.items():
        actual = have[name]
        target = spec["target"]
        if actual is None:
            met = None
        elif spec["unit"] == "fraction":
            met = (actual / len(corpus) if corpus else 0.0) >= target
        else:
            met = actual >= target
        rows.append(
            {
                "property": name,
                "target": target,
                "unit": spec["unit"],
                "have": actual,
                "met": met,
                "measurable_here": spec["source"] == "count",
            }
        )
    return rows


def build_manifest(frames: list[Frame], deliveries: list[dict[str, Any]]) -> dict[str, Any]:
    corpus = [f for f in frames if f.set == "corpus"]
    live = [f for f in corpus if f.superseded_by is None]
    return {
        "schema": 1,
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan_section": "16",
        "note": (
            "Generated by scripts/ingest_originals.py. Every count here is measured, "
            "never estimated; rows this script cannot measure report null rather than "
            "a guess. See AKSHAR.md section 16 for the targets and docs/corpus.md for "
            "what the messaging transcode cost us."
        ),
        "counts": {
            "frames_total": len(frames),
            "corpus_frames_on_disk": len(corpus),
            "corpus_frames_live": len(live),
            "corpus_superseded_transcodes": len(corpus) - len(live),
            "millimetre_grade": sum(1 for f in live if f.millimetre_grade),
            "transcode_only": sum(1 for f in live if not f.millimetre_grade),
            "test_split": sum(1 for f in frames if f.set == "test_split"),
            "negatives": sum(1 for f in frames if f.set == "negatives"),
        },
        "devices": dict(Counter(f.device or "unknown (EXIF stripped)" for f in live).most_common()),
        "targets": tracker(frames),
        "deliveries": deliveries,
        "frames": [asdict(f) for f in sorted(frames, key=lambda f: (f.set, f.path))],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, help="directory of camera originals")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "corpus" / "originals")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "manifest.json")
    parser.add_argument("--dry-run", action="store_true", help="report, copy nothing")
    parser.add_argument(
        "--manifest-only", action="store_true", help="rebuild the manifest from what is on disk"
    )
    args = parser.parse_args()

    deliveries: list[dict[str, Any]] = []
    if args.source and not args.manifest_only:
        if not args.source.is_dir():
            parser.error(f"{args.source} is not a directory")
        print(f"reading {args.source} ...", flush=True)
        delivery = collect(args.source)
        print(f"  {len(delivery.files)} unique images, {len(delivery.duplicates)} duplicate copies")

        args.out.mkdir(parents=True, exist_ok=True)
        copied = kept = 0
        for name, data in delivery.files:
            destination = args.out / name
            if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == (
                hashlib.sha256(data).hexdigest()
            ):
                kept += 1
                continue
            if args.dry_run:
                copied += 1
                continue
            destination.write_bytes(data)
            copied += 1
        print(f"  {copied} copied, {kept} already present" + (" (dry run)" if args.dry_run else ""))
        deliveries.append(
            {
                "received_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": str(args.source),
                "unique_images": len(delivery.files),
                "duplicate_copies": len(delivery.duplicates),
                "unreadable": delivery.unreadable,
            }
        )
        if args.dry_run:
            return 0

    print("measuring the dataset ...", flush=True)
    originals = existing_frames(args.out, "corpus", "camera") if args.out.is_dir() else []
    transcodes = existing_frames(ROOT / "data" / "corpus" / "images", "corpus", "messaging_transcode")
    split = existing_frames(ROOT / "data" / "test_split" / "images", "test_split", "camera")
    negatives_dir = ROOT / "data" / "corpus" / "negatives"
    negatives = existing_frames(negatives_dir, "negatives", "camera") if negatives_dir.is_dir() else []

    linked = link_supersedes(originals, transcodes)
    frames = originals + transcodes + split + negatives

    # Carry forward every earlier delivery, so the manifest is a log and not a
    # snapshot: which batch a photograph arrived in is the first question asked
    # when a batch turns out to be bad.
    if args.manifest.exists():
        previous = json.loads(args.manifest.read_text(encoding="utf-8")).get("deliveries", [])
        known = {(d.get("source"), d.get("unique_images")) for d in deliveries}
        deliveries = [d for d in previous if (d.get("source"), d.get("unique_images")) not in known] + deliveries

    manifest = build_manifest(frames, deliveries)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    counts = manifest["counts"]
    print(f"\nwrote {args.manifest.relative_to(ROOT).as_posix()}")
    print(f"  corpus frames live      {counts['corpus_frames_live']}")
    print(f"    millimetre grade      {counts['millimetre_grade']}")
    print(f"    transcode only        {counts['transcode_only']}")
    print(f"  superseded transcodes   {counts['corpus_superseded_transcodes']} (linked {linked})")
    print(f"  test split              {counts['test_split']}")
    print(f"  negatives               {counts['negatives']}")
    print("\n  target                     have  target  met")
    for row in manifest["targets"]:
        have = "    ?" if row["have"] is None else f"{row['have']:5}"
        mark = {True: "yes", False: "NO", None: "unlabelled"}[row["met"]]
        print(f"  {row['property']:24} {have}  {row['target']!s:>6}  {mark}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
