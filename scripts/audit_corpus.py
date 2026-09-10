"""Survey a photo corpus before anything is trained on it. AKSHAR.md section 14, section 18b.

**This script labels nothing and trains nothing.** It measures, clusters and
flags, and every threshold it applies is a *relative* one. That distinction is
the whole point: an absolute blur threshold silently discards good photographs
of plain packages, because variance-of-Laplacian measures how much fine detail a
label carries as much as it measures sharpness. A dark navy tea box shot
perfectly will always score below a busy biscuit wrapper shot badly.

So the output is a shortlist for a human, not a verdict. Section 14's rule that
the corpus is real photographs applies to its *curation* too — the person who
took them is better at "is there a package in this frame" than any heuristic
available here.

Three measurements, in descending order of how much they can be trusted:

1. **Exact duplicates** (SHA-256). Certain. Two identical files are one photo.
2. **Near-duplicates** (dHash, Hamming distance). Reliable for "same shot",
   and *useless* for "same product, different angle" — a perceptual hash
   compares layout, and two faces of one carton look about as alike as two
   unrelated cartons. So the range it reports bounds redundancy, which is what
   a train/test split needs; it is not a product count, and does not pretend to
   be one.
3. **Blur and exposure.** Indicative only, reported as percentiles.

Usage:
    python scripts/audit_corpus.py data/corpus/images --out data/corpus/audit.json
    python scripts/audit_corpus.py data/corpus/images --contact-sheet review.jpg
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}

# Normalising every image to this shortest side before measuring sharpness is
# what makes the blur numbers comparable at all: variance-of-Laplacian scales
# with resolution, so a 4000px phone photo and an 800px crop of the same scene
# score an order of magnitude apart if left alone.
BLUR_NORMALISE_PX = 512

# dHash at 8x8 gives a 64-bit fingerprint. Ten bits is the conventional
# "probably the same scene" threshold; we group with it, then report the
# grouping as a range, because angle changes push genuine same-product pairs
# past it while near-identical SKUs (same brand, different flavour) fall inside.
NEAR_DUPLICATE_BITS = 10
STRICT_DUPLICATE_BITS = 4

# Fraction of pixels pinned at the top or bottom of the range before a frame is
# worth a second look. Clipping destroys the strokes Rule 7(2) measures.
CLIP_FRACTION_FLAG = 0.08


@dataclass
class ImageStat:
    """One photograph, measured. Nothing here is a judgement beyond the numbers."""

    path: str
    width: int
    height: int
    megapixels: float
    bytes: int
    sha256: str
    dhash: str
    blur_score: float
    """Variance of the Laplacian at a normalised size. Higher is sharper.
    Content-dependent — compare within this corpus, never across corpora."""

    edge_density: float
    """Fraction of pixels Canny calls an edge, after denoising. The measurement
    that actually separates "a package" from "a wall, a floor, or a thumb over
    the lens" — a featureless frame has almost none, however noisy it is."""

    mean_luma: float
    dark_fraction: float
    bright_fraction: float
    orientation: str


@dataclass
class Audit:
    root: str
    count: int
    total_bytes: int
    exact_duplicate_groups: list[list[str]] = field(default_factory=list)
    near_duplicate_groups: list[list[str]] = field(default_factory=list)
    distinct_low: int = 0
    """Lower bound on distinct SHOTS, not products — see `audit()`."""
    distinct_high: int = 0
    blur_percentiles: dict[str, float] = field(default_factory=dict)
    edge_density_percentiles: dict[str, float] = field(default_factory=dict)
    featureless: list[dict[str, Any]] = field(default_factory=list)
    """The likely "no package in frame" set — wall, floor, ceiling, a thumb.
    Ranked, not decided: the corpus owner confirms before anything is deleted."""

    blurriest: list[dict[str, Any]] = field(default_factory=list)
    exposure_flags: list[dict[str, Any]] = field(default_factory=list)
    tiny: list[dict[str, Any]] = field(default_factory=list)
    orientation_counts: dict[str, int] = field(default_factory=dict)
    resolution_percentiles: dict[str, float] = field(default_factory=dict)
    unreadable: list[str] = field(default_factory=list)


def imread_unicode(path: Path) -> np.ndarray | None:
    """cv2.imread cannot open a Windows path containing non-ASCII characters.

    Reading the bytes ourselves and decoding from memory sidesteps it. Not
    hypothetical: a corpus collected on a phone arrives with whatever filenames
    the phone and the messaging app chose.
    """
    try:
        buffer = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if buffer.size == 0:
        return None
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


def dhash(gray: np.ndarray, size: int = 8) -> str:
    """Difference hash: compare each pixel with its right-hand neighbour.

    Chosen over pHash because it is stable under the JPEG re-encoding and
    downscaling a photo picks up passing through a messaging app, which is how
    this corpus arrived.
    """
    small = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    bits = small[:, 1:] > small[:, :-1]
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def measure(path: Path) -> ImageStat | None:
    image = imread_unicode(path)
    if image is None:
        return None

    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    scale = BLUR_NORMALISE_PX / min(height, width)
    normalised = (
        cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if scale < 1.0
        else gray
    )
    # Denoise BEFORE measuring sharpness. Measured on the raw frame instead,
    # this corpus ranked a featureless dark blur at the median: sensor noise in
    # an underexposed frame is high-frequency content, and variance-of-Laplacian
    # cannot tell it from a printed serif. A 3x3 median kills the noise and
    # leaves real strokes intact, which is exactly the discrimination we want.
    denoised = cv2.medianBlur(normalised, 3)
    blur_score = float(cv2.Laplacian(denoised, cv2.CV_64F).var())
    edges = cv2.Canny(denoised, 50, 150)
    edge_density = float(np.count_nonzero(edges) / edges.size)

    total = gray.size
    dark_fraction = float(np.count_nonzero(gray < 16) / total)
    bright_fraction = float(np.count_nonzero(gray > 239) / total)

    if width > height * 1.05:
        orientation = "landscape"
    elif height > width * 1.05:
        orientation = "portrait"
    else:
        orientation = "square"

    return ImageStat(
        path=path.name,
        width=width,
        height=height,
        megapixels=round(width * height / 1e6, 2),
        bytes=path.stat().st_size,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        dhash=dhash(gray),
        blur_score=round(blur_score, 1),
        edge_density=round(edge_density, 4),
        mean_luma=round(float(gray.mean()), 1),
        dark_fraction=round(dark_fraction, 4),
        bright_fraction=round(bright_fraction, 4),
        orientation=orientation,
    )


def group_near_duplicates(stats: list[ImageStat], bits: int) -> list[list[str]]:
    """Union-find over the Hamming graph.

    Transitive closure is the right call for "same product, several angles": A
    resembles B and B resembles C is exactly what a rotation sequence looks
    like, even when A and C differ by more than the threshold. It does mean one
    wrong link merges two products, which is why the caller reports a range
    rather than a count.
    """
    parent = list(range(len(stats)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    values = [int(s.dhash, 16) for s in stats]
    for i in range(len(stats)):
        for j in range(i + 1, len(stats)):
            if bin(values[i] ^ values[j]).count("1") <= bits:
                union(i, j)

    clusters: dict[int, list[str]] = {}
    for index, stat in enumerate(stats):
        clusters.setdefault(find(index), []).append(stat.path)
    return [sorted(members) for members in clusters.values() if len(members) > 1]


def audit(root: Path) -> tuple[Audit, list[ImageStat]]:
    paths = sorted(p for p in root.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    stats: list[ImageStat] = []
    unreadable: list[str] = []

    for path in paths:
        stat = measure(path)
        if stat is None:
            unreadable.append(path.name)
            continue
        stats.append(stat)

    report = Audit(
        root=str(root),
        count=len(stats),
        total_bytes=sum(s.bytes for s in stats),
        unreadable=unreadable,
    )
    if not stats:
        return report, stats

    by_sha: dict[str, list[str]] = {}
    for stat in stats:
        by_sha.setdefault(stat.sha256, []).append(stat.path)
    report.exact_duplicate_groups = [sorted(v) for v in by_sha.values() if len(v) > 1]

    report.near_duplicate_groups = group_near_duplicates(stats, NEAR_DUPLICATE_BITS)
    strict = group_near_duplicates(stats, STRICT_DUPLICATE_BITS)

    # Two bounds on "how many distinct SHOTS" — and measured against a real
    # corpus, NOT a usable proxy for how many distinct products.
    #
    # On the 469-image set received 2026-09-07 this reported 436-451 while the
    # photographer counted ~207 products. The gap is the method's, not theirs: a
    # perceptual hash compares layout, and two faces of the same carton have
    # about as much in common visually as two unrelated cartons. Angles are
    # exactly what dHash cannot merge.
    #
    # The numbers are still worth having — they bound how much *redundancy* is
    # in the set, which is what matters for a train/test split. They are not a
    # product count, and the printed labels say so.
    loose_merged = sum(len(g) - 1 for g in report.near_duplicate_groups)
    strict_merged = sum(len(g) - 1 for g in strict)
    report.distinct_low = len(stats) - loose_merged
    report.distinct_high = len(stats) - strict_merged

    blurs = np.array([s.blur_score for s in stats])
    report.blur_percentiles = {
        f"p{q}": round(float(np.percentile(blurs, q)), 1) for q in (5, 10, 25, 50, 75, 95)
    }
    densities = np.array([s.edge_density for s in stats])
    report.edge_density_percentiles = {
        f"p{q}": round(float(np.percentile(densities, q)), 4) for q in (1, 5, 10, 25, 50, 95)
    }
    # Both signals must agree before a frame is called featureless. Low edges
    # alone catches a legitimately plain white carton; low sharpness alone
    # catches a soft photograph of a real package. Together they mean there is
    # nothing in the frame to be sharp about.
    edge_cut = float(np.percentile(densities, 10))
    blur_cut = float(np.percentile(blurs, 20))
    report.featureless = sorted(
        (
            {"path": s.path, "edge_density": s.edge_density, "blur_score": s.blur_score}
            for s in stats
            if s.edge_density <= edge_cut and s.blur_score <= blur_cut
        ),
        key=lambda row: (row["edge_density"], row["blur_score"]),
    )

    cutoff = float(np.percentile(blurs, 10))
    report.blurriest = [
        {"path": s.path, "blur_score": s.blur_score}
        for s in sorted(stats, key=lambda s: s.blur_score)
        if s.blur_score <= cutoff
    ]

    report.exposure_flags = [
        {
            "path": s.path,
            "mean_luma": s.mean_luma,
            "dark_fraction": s.dark_fraction,
            "bright_fraction": s.bright_fraction,
        }
        for s in stats
        if s.dark_fraction > CLIP_FRACTION_FLAG or s.bright_fraction > CLIP_FRACTION_FLAG
    ]

    megapixels = np.array([s.megapixels for s in stats])
    report.resolution_percentiles = {
        f"p{q}": round(float(np.percentile(megapixels, q)), 2) for q in (5, 50, 95)
    }
    report.tiny = [
        {"path": s.path, "width": s.width, "height": s.height}
        for s in stats
        if min(s.width, s.height) < 640
    ]

    for stat in stats:
        report.orientation_counts[stat.orientation] = (
            report.orientation_counts.get(stat.orientation, 0) + 1
        )

    return report, stats


def contact_sheet(
    root: Path, names: list[str], out: Path, *, cols: int = 6, cell: int = 320
) -> None:
    """One JPEG of the flagged frames, so a human reviews thirty files, not 469."""
    if not names:
        return
    rows = (len(names) + cols - 1) // cols
    sheet = np.full((rows * cell, cols * cell, 3), 32, dtype=np.uint8)
    for index, name in enumerate(names):
        image = imread_unicode(root / name)
        if image is None:
            continue
        h, w = image.shape[:2]
        scale = cell / max(h, w)
        thumb = cv2.resize(image, (max(1, int(w * scale)), max(1, int(h * scale))))
        th, tw = thumb.shape[:2]
        r, c = divmod(index, cols)
        y, x = r * cell, c * cell
        sheet[y : y + th, x : x + tw] = thumb
        cv2.putText(
            sheet,
            str(index + 1),
            (x + 6, y + 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Survey a photo corpus.")
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--per-image", type=Path, default=None)
    parser.add_argument("--contact-sheet", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        print(f"No such directory: {args.root}", file=sys.stderr)
        return 2

    report, stats = audit(args.root)

    print(f"{report.count} readable images, {report.total_bytes / 1e6:.0f} MB")
    if report.unreadable:
        print(f"  unreadable             : {len(report.unreadable)} -> {report.unreadable[:5]}")
    print(f"  exact duplicate groups : {len(report.exact_duplicate_groups)}")
    print(f"  near-duplicate groups  : {len(report.near_duplicate_groups)}")
    print(
        f"  distinct SHOTS         : between {report.distinct_low} and {report.distinct_high}"
        "  (NOT a product count — ask the photographer)"
    )
    print(f"  resolution (MP)        : {report.resolution_percentiles}")
    print(f"  orientation            : {report.orientation_counts}")
    print(f"  blur percentiles       : {report.blur_percentiles}")
    print(f"  edge density pct       : {report.edge_density_percentiles}")
    print(f"  likely no package      : {len(report.featureless)} images  <- review these")
    print(f"  softest decile         : {len(report.blurriest)} images")
    print(f"  exposure flags         : {len(report.exposure_flags)} images")
    print(f"  under 640px            : {len(report.tiny)} images")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
        print(f"  wrote {args.out}")
    if args.per_image:
        args.per_image.parent.mkdir(parents=True, exist_ok=True)
        args.per_image.write_text(
            json.dumps([asdict(s) for s in stats], indent=2), encoding="utf-8"
        )
        print(f"  wrote {args.per_image}")
    if args.contact_sheet:
        # Worst first, so the frames most likely to be junk are the top row.
        flagged = [f["path"] for f in report.featureless]
        for group in (report.blurriest, report.exposure_flags):
            flagged += [f["path"] for f in group if f["path"] not in flagged]
        contact_sheet(args.root, flagged, args.contact_sheet)
        print(f"  wrote {args.contact_sheet} ({len(flagged)} frames)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
