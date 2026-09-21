"""Export the SKU embedder and fit its PCA. AKSHAR.md §15b, M9.

    python -m training.identify.export_embed
    python -m training.identify.export_embed --images data/corpus/images --limit 200

    "SKU near-duplicate: MobileNetV3-Small penultimate layer, 576-d -> PCA to
     512-d, ~4 MB. Reuses a model already in the bundle. A dedicated embedding
     model for label matching is not worth 90 MB."        -- section 15b

---------------------------------------------------------------------------
THE ONE MODEL HERE THAT NEEDS NO LABELS
---------------------------------------------------------------------------
Of the three absent models, this is the only one that can be built today. The
detector needs boxes drawn on a few hundred frames and the address head needs
those four fields named by a person; this needs neither, because the backbone
arrives pretrained on ImageNet and the projection is unsupervised.

What it buys is **not accuracy**. Nothing in the declaration pipeline consumes
an embedding: it is the third rung of M9's identity ladder, after barcode and
pHash, and its whole job is recognising that this photograph is of a pack we
have already scanned. That turns a 1190 ms scan into a 48 ms cache hit. Worth
having, worth not overselling.

---------------------------------------------------------------------------
WHY THE PCA IS FITTED HERE AND SHIPPED
---------------------------------------------------------------------------
`vision/identify/embed.py` refuses to fit it at runtime, and says why: *"Fitting
PCA on whatever happens to be in the database changes the embedding space every
time it is refitted, silently invalidating every vector already stored."* So it
is fitted once, here, over the development corpus, and versioned alongside the
model.

**It is fitted on `data/corpus/`, never on `data/test_split/`.** The seal covers
every use, and "we only fitted an unsupervised projection on it" is exactly the
kind of leak that sounds harmless and is not.

---------------------------------------------------------------------------
576 -> 512 IS BARELY A REDUCTION, AND THAT IS THE POINT
---------------------------------------------------------------------------
PCA here is not compression, it is decorrelation plus a fixed basis. Dropping
64 of 576 dimensions discards the directions the corpus never varies along --
mostly ImageNet texture channels no retail label excites -- and leaves a space
whose axes are stable across refits of the *database* because the basis itself
is frozen in a file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from vision.identify.embed import (  # noqa: E402
    EMBED_DIM,
    INPUT_SIZE,
    MODEL_FILENAME,
    PCA_FILENAME,
    RAW_DIM,
    _preprocess,
)

MODELS = ROOT / "data" / "models"
CORPUS = ROOT / "data" / "corpus" / "images"
SEALED = ROOT / "data" / "test_split"

SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def build_backbone():
    """MobileNetV3-Small, ImageNet weights, truncated to the 576-d penultimate.

    `features` then a global pool is the penultimate activation the plan names.
    The classifier head is dropped entirely -- we want the representation, not
    ImageNet's thousand classes.
    """
    import torch
    from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

    net = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1)
    net.eval()

    class Embedder(torch.nn.Module):
        def __init__(self, base):
            super().__init__()
            self.features = base.features
            self.pool = torch.nn.AdaptiveAvgPool2d(1)

        def forward(self, x):
            return torch.flatten(self.pool(self.features(x)), 1)

    return Embedder(net).eval()


def export_onnx(model, out: Path) -> None:
    import torch

    dummy = torch.zeros(1, 3, INPUT_SIZE, INPUT_SIZE)
    with torch.no_grad():
        width = int(model(dummy).shape[1])
    if width != RAW_DIM:
        raise SystemExit(
            f"backbone produced {width}-d, but vision/identify/embed.py declares "
            f"RAW_DIM={RAW_DIM}. One of the two is wrong; do not paper over it."
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        model,
        dummy,
        str(out),
        input_names=["image"],
        output_names=["embedding"],
        opset_version=17,
        dynamo=False,
    )
    print(f"  exported {out.name}  {out.stat().st_size / 1e6:.1f} MB  ({width}-d)")


CROPS_PER_FRAME = 4
"""Views taken from each corpus frame: the whole thing, then three sub-crops.

**Two reasons, and the second is the one that matters.**

The arithmetic one: a PCA with 512 components needs at least 512 observations,
and the corpus holds 469 frames. One row per frame cannot fill the basis --
`vision/identify/embed.py` catches that and refuses to load, which is how this
was found rather than shipped.

The real one: `embed()` is never called on a whole photograph. It is called on
a **rectified label**, so fitting the basis on whole frames would fit it on a
distribution the runtime never sees -- wide shots with shelves and hands in
them, when every vector ever stored will be a cropped pack face. Sub-crops are
a closer approximation to what the thing is for, and they happen to fix the
rank problem on the way past.
"""


def _views(image: np.ndarray, rng: np.random.Generator) -> list[np.ndarray]:
    """The frame, plus sub-crops standing in for a rectified label."""
    height, width = image.shape[:2]
    views = [image]
    for _ in range(CROPS_PER_FRAME - 1):
        scale = float(rng.uniform(0.45, 0.85))
        h, w = int(height * scale), int(width * scale)
        if h < 32 or w < 32:
            continue
        top = int(rng.integers(0, max(1, height - h)))
        left = int(rng.integers(0, max(1, width - w)))
        views.append(image[top : top + h, left : left + w])
    return views


def corpus_features(session, input_name: str, images: Path, limit: int) -> np.ndarray:
    """Raw 576-d activations over the development corpus."""
    if SEALED.resolve() in images.resolve().parents or images.resolve() == SEALED.resolve():
        raise SystemExit(
            "REFUSING: data/test_split/ is sealed. Section 16 forbids fitting anything "
            "on it, and an unsupervised projection is still something."
        )

    paths = sorted(p for p in images.iterdir() if p.suffix.lower() in SUFFIXES)
    if limit:
        paths = paths[:limit]

    # Seeded: two people running this must get the same basis, or the vectors
    # in one database cannot be compared with those in another.
    rng = np.random.default_rng(20260920)

    rows: list[np.ndarray] = []
    for index, path in enumerate(paths, 1):
        buf = np.fromfile(str(path), dtype=np.uint8)
        image = cv2.imdecode(buf, cv2.IMREAD_COLOR) if buf.size else None
        if image is None:
            continue
        for view in _views(image, rng):
            raw = session.run(None, {input_name: _preprocess(view)})[0]
            rows.append(np.asarray(raw).reshape(-1)[:RAW_DIM].astype(np.float32))
        if index % 50 == 0:
            print(f"    {index}/{len(paths)} frames, {len(rows)} views", flush=True)
    return np.vstack(rows)


def fit_pca(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mean and the top `EMBED_DIM` right singular vectors.

    Plain SVD rather than scikit-learn: the whole operation is one call, the
    result is deterministic, and it saves a dependency the runtime does not
    have and must never acquire.
    """
    if matrix.shape[0] < EMBED_DIM:
        raise SystemExit(
            f"only {matrix.shape[0]} observations for {EMBED_DIM} components. SVD cannot "
            f"produce a basis it has no data for, and padding one with arbitrary "
            f"directions would make part of every stored vector meaningless. Give this "
            f"more frames."
        )

    mean = matrix.mean(axis=0)
    centred = matrix - mean
    _, singular, vt = np.linalg.svd(centred, full_matrices=False)
    components = vt[:EMBED_DIM].astype(np.float32)

    kept = float((singular[:EMBED_DIM] ** 2).sum() / max((singular**2).sum(), 1e-12))
    print(f"  PCA fitted on {matrix.shape[0]} views; "
          f"{EMBED_DIM} of {RAW_DIM} dimensions keep {kept:.4%} of the variance")
    return components, mean.astype(np.float32)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, default=CORPUS)
    parser.add_argument("--limit", type=int, default=0, help="stop after N frames")
    parser.add_argument("--out", type=Path, default=MODELS)
    args = parser.parse_args(argv)

    print("building MobileNetV3-Small backbone (ImageNet weights)...")
    export_onnx(build_backbone(), args.out / MODEL_FILENAME)

    import onnxruntime as ort

    session = ort.InferenceSession(
        str(args.out / MODEL_FILENAME), providers=["CPUExecutionProvider"]
    )
    input_name = session.get_inputs()[0].name

    print(f"\nfitting PCA over {args.images}...")
    matrix = corpus_features(session, input_name, args.images, args.limit)
    components, mean = fit_pca(matrix)

    pca_path = args.out / PCA_FILENAME
    np.savez_compressed(pca_path, components=components, mean=mean)
    print(f"  wrote {pca_path.name}  {pca_path.stat().st_size / 1e6:.1f} MB")

    from vision.identify import embed as embed_mod

    print("\nchecking the runtime can load what was just written...")
    print("  is_available():", embed_mod.is_available())

    probe = cv2.imdecode(
        np.fromfile(
            str(sorted(p for p in args.images.iterdir() if p.suffix.lower() in SUFFIXES)[0]),
            dtype=np.uint8,
        ),
        cv2.IMREAD_COLOR,
    )
    vector = embed_mod.embed(probe)
    print(f"  embed() returned {len(vector)}-d, |v| = {np.linalg.norm(vector):.6f}")
    print(f"  self-similarity {embed_mod.cosine(vector, vector):.6f} (must be 1.0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
