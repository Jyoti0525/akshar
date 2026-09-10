"""Does a declaration reach the crop budget at all? Dev corpus only.

U1 is not failing on measurement. It is failing because 36 of 40 frames read no
MRP, and the first trace blamed the ranking: 83 to 176 regions proposed, eight
read, and the eight were marketing copy. Reading deeper disproved that --
recall@24 came back identical to recall@8, so the declaration was not sitting
just below the cut. It was not being *assembled*. DBNet proposes words, and
`'MRP Rs.'` and `'10'` are two proposals that each classify as `other`.

So this bench answers one question, before and after `vision.ocr.lines`: how
often does a real declaration land inside the top N regions we are willing to
read? `regex_tier` stands in for labels we do not have -- it is a strict
hand-written matcher, so it will miss declarations it cannot parse and every
number here is a *lower* bound. That is the right direction for a bench to err.

**It runs on `data/corpus/` and never on `data/test_split/`.** The sealed forty
may be used to report a result, never to obtain one; `assert_not_sealed` makes
that structural rather than a promise. `--sweep` exists so the one real constant
in `vision.ocr.lines` is chosen here, on images allowed to teach us something.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import cv2

from vision import runtime
from vision.classify import regex_tier
from vision.detect import detector
from vision.ocr import detect_text, recognise, roi
from vision.ocr.lines import merge_into_lines
from vision.rectify.rectify import rectify
from vision.scale import tier_a
from vision.scale.resolve import resolve_scale
from vision.types import TextRegion

WANTED = ("mrp", "net_quantity")
"""The two U1 cares about, and the two `regex_tier` recognises most reliably."""

SEALED = "test_split"

NO_MERGE = -1.0
"""Sentinel gap ratio meaning "leave the proposals exactly as detected"."""


def assert_not_sealed(path: Path) -> None:
    if SEALED in path.parts:
        raise SystemExit(
            f"{path} is inside the sealed test split. This bench chooses constants, "
            "and a constant chosen on the test split makes the test split "
            "meaningless. Point it at data/corpus/."
        )


class Frame:
    """Everything about one image that does not depend on the gap ratio.

    Detection, rectification and scale cost far more than recognition here and
    do not vary across a sweep, so they are paid once. Recognition is cached by
    box as well, because most crops are identical between adjacent gap values.
    """

    def __init__(self, image) -> None:
        try:
            detection = detector.detect(image)
        except runtime.ModelUnavailableError:
            detection = None

        package_box = None
        if detection is not None and (best := detection.best_package()):
            package_box = best.box

        marker = tier_a.marker_quad(image)
        flat = rectify(image, marker=marker, package_box=package_box)
        scale = resolve_scale(
            image,
            flat.image,
            homography=flat.homography,
            rectify_method=flat.method,
            edge_mm=tier_a.MARKER_EDGE_MM,
            dictionary=tier_a.DEFAULT_DICTIONARY,
            cache_key="bench",
        )

        self.flat = flat.image
        self.mm_per_px = scale.mm_per_px
        self.pdp = None
        if detection is not None:
            panels = detection.panels()
            if panels and panels[0].polygon:
                from vision.rectify.rectify import map_point

                self.pdp = [map_point(flat.homography, p) for p in panels[0].polygon]

        self.regions, _, _ = detect_text.propose_regions(self.flat, mm_per_px=self.mm_per_px)
        self._cache: dict[tuple[int, int, int, int], str] = {}

    def _read(self, region: TextRegion) -> str:
        box = region.box
        key = (int(box.x), int(box.y), int(box.w), int(box.h))
        if key in self._cache:
            return self._cache[key]
        crop, _, _ = roi._crop(self.flat, box)
        text = ""
        if crop.size:
            try:
                text = recognise.read(crop, "latin")[0].text
            except runtime.ModelUnavailableError:
                text = ""
        self._cache[key] = text
        return text

    def first_declaration_rank(self, *, gap: float, depth: int) -> tuple[int | None, int, list[str]]:
        regions = self.regions if gap == NO_MERGE else merge_into_lines(self.regions, gap_ratio=gap)
        keep, _ = roi.rank_regions(regions, pdp_polygon=self.pdp, limit=depth, mm_per_px=self.mm_per_px)

        first: int | None = None
        found: list[str] = []
        for rank, region in enumerate(keep):
            text = self._read(region)
            if not text.strip():
                continue
            guess = regex_tier.classify_text(text)
            if guess.field in WANTED:
                found.append(f"{rank}:{guess.field}:{text.strip()[:32]}")
                if first is None:
                    first = rank
        return first, len(regions), found


def _recall(ranks: list[int | None], n: int, *, over: list[int] | None = None) -> float:
    """Fraction of frames whose first declaration landed inside the top `n`.

    `over` restricts the denominator to given frame indices. It matters more
    than it sounds: the dev corpus is photographs of packs from every angle,
    and most faces of a pack carry no MRP at all -- the top of a sunscreen
    carton has a brand name, an SPF claim and a barcode, and nothing this
    bench is looking for. Scoring those as misses measures how often a
    declaration was photographed, not how often one was found.
    """
    pool = list(range(len(ranks))) if over is None else list(over)
    if not pool:
        return 0.0
    return sum(1 for i in pool if ranks[i] is not None and ranks[i] < n) / len(pool)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("images", type=Path, nargs="?", default=Path("data/corpus/images"))
    ap.add_argument("--sample", type=int, default=60, help="images to draw (0 = all)")
    ap.add_argument("--depth", type=int, default=16, help="how far down the ranking to read")
    ap.add_argument("--seed", type=int, default=20260909)
    ap.add_argument(
        "--sweep",
        type=str,
        default="",
        help="comma-separated gap ratios to compare, e.g. 0.5,1.0,1.5,2.0,3.0. "
        "'none' means no merging at all.",
    )
    ap.add_argument("--out", type=Path, default=Path("bench/rank_recall.json"))
    args = ap.parse_args()

    assert_not_sealed(args.images)

    gaps: list[float] = [NO_MERGE]
    if args.sweep:
        gaps = [NO_MERGE if g.strip() == "none" else float(g) for g in args.sweep.split(",")]

    paths = sorted(
        p
        for p in args.images.rglob("*")
        if p.suffix.lower() in {".jpg", ".jpeg", ".png"} and p.is_file()
    )
    if args.sample and args.sample < len(paths):
        paths = random.Random(args.seed).sample(paths, args.sample)

    ranks: dict[float, list[int | None]] = {g: [] for g in gaps}
    counts: dict[float, list[int]] = {g: [] for g in gaps}
    detail: list[dict] = []

    for i, path in enumerate(paths, 1):
        image = cv2.imread(str(path))
        if image is None:
            continue
        frame = Frame(image)
        row = {"image": str(path.relative_to(args.images)), "proposed": len(frame.regions)}
        for gap in gaps:
            first, n_regions, found = frame.first_declaration_rank(gap=gap, depth=args.depth)
            ranks[gap].append(first)
            counts[gap].append(n_regions)
            row[f"gap_{gap}"] = {"first": first, "regions": n_regions, "found": found}
        detail.append(row)
        summary = "  ".join(
            f"{'raw' if g == NO_MERGE else g}:{row[f'gap_{g}']['first']}" for g in gaps
        )
        print(f"  {i}/{len(paths)}  {len(frame.regions):>3}->  {summary}", flush=True)

    n = len(detail)
    # A frame demonstrably contains a findable declaration if *any* configuration
    # found one. That is the only honest denominator available without labels,
    # and it errs the safe way: a frame every configuration missed is excluded,
    # so no configuration is credited for it.
    findable = [i for i in range(n) if any(ranks[g][i] is not None for g in gaps)]
    print(f"\nframes: {n}   with a findable declaration: {len(findable)}\n")
    header = "gap".ljust(6) + "regions".rjust(9) + "".join(f"@{k}".rjust(8) for k in (4, 8, 12, 16))
    print(header)
    print("-" * len(header))
    for gap in gaps:
        median = sorted(counts[gap])[n // 2] if n else 0
        label = "raw" if gap == NO_MERGE else f"{gap:g}"
        cells = "".join(
            f"{_recall(ranks[gap], k, over=findable):>7.0%}" + " "
            for k in (4, 8, 12, 16)
            if k <= args.depth
        )
        print(f"{label:<6}{median:>9}  {cells}")
    print('\\n(recall is over the frames that demonstrably contain a declaration)')

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(detail, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
