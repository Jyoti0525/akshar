"""SKU embedding — near-duplicate search when the hash misses.

    "SKU near-duplicate: MobileNetV3-Small penultimate layer, 576-d -> PCA to
     512-d, ~4 MB. Reuses a model already in the bundle. A dedicated embedding
     model for label matching is not worth 90 MB."        -- section 15b

The third rung of M9's identity ladder: barcode (exact), pHash (near-exact),
then this (similar). It catches what the hash cannot — a repackaged SKU whose
artwork was refreshed, the 100 g and 200 g packs of the same product, a photo
taken so differently that the DCT block moves more than eight bits.

Stored as `vector(512)` in Postgres with an HNSW index, `m=16`,
`ef_construction=64`. Section 15b is explicit that this is the one place an
index *is* justified: SKU count grows without bound, unlike the 1,700-row rule
corpus where a sequential scan wins.

**Why the PCA matrix is a shipped artifact, not something fitted at runtime.**
Fitting PCA on whatever happens to be in the database changes the embedding
space every time it is refitted, silently invalidating every vector already
stored. It is fitted once during training, exported, versioned, and loaded.
"""

from __future__ import annotations

import cv2
import numpy as np

from vision import runtime
from vision.types import Image

MODEL_FILENAME = "mobilenetv3_small_embed.onnx"
PCA_FILENAME = "sku_pca_512.npz"

INPUT_SIZE = 224
RAW_DIM = 576
"""MobileNetV3-Small penultimate width."""

EMBED_DIM = 512
"""After PCA. The Postgres column is `vector(512)`; changing this is a migration."""

_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

_PCA: tuple[np.ndarray, np.ndarray] | None = None


def _preprocess(image: Image) -> np.ndarray:
    resized = cv2.resize(image, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_AREA)
    if resized.ndim == 2:  # pragma: no cover
        resized = cv2.cvtColor(resized, cv2.COLOR_GRAY2BGR)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    normalised = (rgb - _MEAN) / _STD
    return np.ascontiguousarray(np.transpose(normalised, (2, 0, 1))[np.newaxis, ...])


def _load_pca() -> tuple[np.ndarray, np.ndarray]:
    global _PCA
    if _PCA is not None:
        return _PCA

    path = runtime.resolve(PCA_FILENAME)
    if not path.is_file():
        raise runtime.ModelUnavailableError(
            f"PCA projection {PCA_FILENAME!r} not found at {path}. It is fitted once "
            f"during training and shipped; refitting it at runtime would invalidate "
            f"every vector already stored."
        )
    with np.load(path) as data:
        components = np.asarray(data["components"], dtype=np.float32)
        mean = np.asarray(data["mean"], dtype=np.float32)

    if components.shape != (EMBED_DIM, RAW_DIM):
        raise runtime.ModelUnavailableError(
            f"PCA components are {components.shape}, expected {(EMBED_DIM, RAW_DIM)}"
        )
    _PCA = (components, mean)
    return _PCA


def embed(image: Image, *, model_name: str = MODEL_FILENAME) -> list[float]:
    """512-d L2-normalised embedding of a rectified label.

    L2-normalised so pgvector's cosine distance is a plain dot product, and so
    a brighter photograph of the same pack does not land further away purely
    because its activations are larger.
    """
    model = runtime.load(model_name)
    components, mean = _load_pca()

    raw = np.asarray(model.session.run(None, {model.input_name: _preprocess(image)})[0])
    vector = raw.reshape(-1)[:RAW_DIM].astype(np.float32)

    projected = components @ (vector - mean)
    norm = float(np.linalg.norm(projected))
    if norm > 0:
        projected = projected / norm
    return [float(v) for v in projected]


def cosine(left: list[float], right: list[float]) -> float:
    a, b = np.asarray(left, dtype=np.float32), np.asarray(right, dtype=np.float32)
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b / denominator) if denominator > 0 else 0.0


def is_available(model_name: str = MODEL_FILENAME) -> bool:
    return runtime.available(model_name) and runtime.resolve(PCA_FILENAME).is_file()


__all__ = [
    "EMBED_DIM",
    "MODEL_FILENAME",
    "PCA_FILENAME",
    "RAW_DIM",
    "cosine",
    "embed",
    "is_available",
]
