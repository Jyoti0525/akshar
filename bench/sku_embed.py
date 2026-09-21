"""Does the SKU embedder actually recognise the same pack twice?

The audit already found 15 groups of byte-identical frames and 20 groups of
near-identical ones in the corpus. Those are free ground truth for exactly the
question this model exists to answer, and no labelling was needed to get them:
a *near*-duplicate pair is two photographs of one pack, which is the case the
hash misses and the embedding is the third rung of the ladder for.

    section 15b: "SKU near-duplicate: MobileNetV3-Small penultimate layer,
    576-d -> PCA to 512-d [...] It catches what the hash cannot -- a repackaged
    SKU whose artwork was refreshed, the 100 g and 200 g packs of the same
    product, a photo taken so differently that the DCT block moves more than
    eight bits."

**This measures separation, not accuracy of anything a rule reads.** Nothing in
the declaration pipeline consumes an embedding; a hit turns a 1190 ms scan into
a 48 ms one. The number to want is a clear gap between "same pack" and
"different pack", because a threshold can only be set where a gap exists.
"""

from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vision.identify.embed import cosine, embed, is_available  # noqa: E402

CORPUS = ROOT / "data" / "corpus"
PAIRS_PER_GROUP = 3
RANDOM_PAIRS = 400


def imread(path: Path) -> np.ndarray | None:
    buf = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR) if buf.size else None


def main() -> None:
    if not is_available():
        raise SystemExit(
            "the embedder is not built. Run: python -m training.identify.export_embed"
        )

    audit = json.loads((CORPUS / "audit.json").read_text(encoding="utf-8"))
    vectors: dict[str, list[float]] = {}

    def vector_for(name: str) -> list[float] | None:
        if name not in vectors:
            image = imread(CORPUS / "images" / name)
            if image is None:
                return None
            vectors[name] = embed(image)
        return vectors[name]

    same: list[float] = []
    for key in ("exact_duplicate_groups", "near_duplicate_groups"):
        for group in audit.get(key, []):
            for left, right in list(combinations(group, 2))[:PAIRS_PER_GROUP]:
                a, b = vector_for(left), vector_for(right)
                if a and b:
                    same.append(cosine(a, b))

    names = sorted(p.name for p in (CORPUS / "images").iterdir() if p.is_file())
    grouped = {n for key in ("exact_duplicate_groups", "near_duplicate_groups")
               for g in audit.get(key, []) for n in g}
    singles = [n for n in names if n not in grouped]

    rng = np.random.default_rng(20260920)
    different: list[float] = []
    for _ in range(RANDOM_PAIRS):
        left, right = rng.choice(len(singles), size=2, replace=False)
        a, b = vector_for(singles[left]), vector_for(singles[right])
        if a and b:
            different.append(cosine(a, b))

    s = np.array(same)
    d = np.array(different)

    print("=" * 66)
    print("SKU EMBEDDING — separation between same pack and different pack")
    print("=" * 66)
    print(f"{'':22} {'n':>5} {'mean':>8} {'p5':>8} {'p50':>8} {'p95':>8}")
    print(f"{'same pack (dup pairs)':22} {len(s):5} {s.mean():8.4f} "
          f"{np.percentile(s, 5):8.4f} {np.percentile(s, 50):8.4f} {np.percentile(s, 95):8.4f}")
    print(f"{'different packs':22} {len(d):5} {d.mean():8.4f} "
          f"{np.percentile(d, 5):8.4f} {np.percentile(d, 50):8.4f} {np.percentile(d, 95):8.4f}")

    gap = float(np.percentile(s, 5) - np.percentile(d, 95))
    print()
    print(f"  gap between the 5th percentile of SAME and the 95th of DIFFERENT: {gap:+.4f}")
    if gap > 0:
        print(f"  A threshold anywhere in ({np.percentile(d, 95):.4f}, "
              f"{np.percentile(s, 5):.4f}) separates them on this sample.")
    else:
        print("  The two distributions OVERLAP at those percentiles. No threshold "
              "separates them cleanly here.")

    out = {
        "same_pairs": len(s),
        "different_pairs": len(d),
        "same_mean": round(float(s.mean()), 4),
        "same_p5": round(float(np.percentile(s, 5)), 4),
        "different_mean": round(float(d.mean()), 4),
        "different_p95": round(float(np.percentile(d, 95)), 4),
        "gap": round(gap, 4),
    }
    (ROOT / "bench" / "sku_embed.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("\nwritten to bench/sku_embed.json")


if __name__ == "__main__":
    main()
