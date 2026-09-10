"""Layout features for the address classifier — AKSHAR.md section 15b.

    "Input: `MiniLM-L6` sentence embedding (384-d, frozen) || normalised box
     [x,y,w,h] || relative font size || panel one-hot || script one-hot"

Defined in its own module because the *training* code and the *inference* code
must build this vector identically, down to the ordering of the one-hot slots.
Feature skew between train and serve is silent — nothing errors, the model just
becomes slightly wrong in a way no test detects — and it is the most common way
a working classifier degrades after deployment. One function, imported by both.

The text embedding is supplied by the caller rather than computed here, so this
module stays free of the sentence-transformer dependency and can be exercised
in a unit test with a zero vector.
"""

from __future__ import annotations

import numpy as np

from vision.types import Box, OcrLine, PanelId, Script

EMBEDDING_DIM = 384
"""MiniLM-L6 sentence embedding, frozen. Section 15b."""

PANELS: tuple[PanelId, ...] = ("pdp", "side", "back", "top", "bottom", "unknown")
SCRIPTS: tuple[Script, ...] = ("latin", "devanagari", "other")

GEOMETRY_DIM = 5
"""x, y, w, h normalised to the label, plus relative font size."""

FEATURE_DIM = EMBEDDING_DIM + GEOMETRY_DIM + len(PANELS) + len(SCRIPTS)


def _one_hot(value: object, options: tuple[object, ...]) -> np.ndarray:
    vector = np.zeros(len(options), dtype=np.float32)
    if value in options:
        vector[options.index(value)] = 1.0
    return vector


def geometry_features(
    box: Box,
    *,
    label_w: float,
    label_h: float,
    cap_height_px: float | None,
    median_cap_height_px: float | None,
) -> np.ndarray:
    """Position and prominence, both normalised.

    **Position is the whole point of this model.** Manufacturer, packer,
    importer and consumer care are all addresses with the same vocabulary; what
    separates them is where they sit and what they sit near. So the box is
    normalised against the label rather than the frame — a declaration two
    thirds of the way down the pack is in the same place whether the officer
    stood close or far.

    Font size is likewise *relative*, against the median line on this label.
    Absolute pixel height would encode camera distance, which is noise.
    """
    width = max(label_w, 1.0)
    height = max(label_h, 1.0)

    relative_size = 1.0
    if cap_height_px and median_cap_height_px and median_cap_height_px > 0:
        relative_size = cap_height_px / median_cap_height_px

    return np.array(
        [
            box.x / width,
            box.y / height,
            box.w / width,
            box.h / height,
            min(relative_size, 6.0),
        ],
        dtype=np.float32,
    )


def build_features(
    line: OcrLine,
    embedding: np.ndarray,
    *,
    label_w: float,
    label_h: float,
    median_cap_height_px: float | None,
) -> np.ndarray:
    """The full feature vector for one line, in the frozen order.

    Raises on a wrong-sized embedding rather than padding it. A silently
    truncated embedding is exactly the train/serve skew this module exists to
    prevent.
    """
    embedding = np.asarray(embedding, dtype=np.float32).ravel()
    if embedding.size != EMBEDDING_DIM:
        raise ValueError(f"expected a {EMBEDDING_DIM}-d MiniLM-L6 embedding, got {embedding.size}")

    return np.concatenate(
        [
            embedding,
            geometry_features(
                line.box,
                label_w=label_w,
                label_h=label_h,
                cap_height_px=line.cap_height_px,
                median_cap_height_px=median_cap_height_px,
            ),
            _one_hot(line.panel_id or "unknown", PANELS),
            _one_hot(line.script, SCRIPTS),
        ]
    ).astype(np.float32)


def median_cap_height(lines: list[OcrLine]) -> float | None:
    heights = [line.cap_height_px for line in lines if line.cap_height_px]
    return float(np.median(heights)) if heights else None


__all__ = [
    "EMBEDDING_DIM",
    "FEATURE_DIM",
    "GEOMETRY_DIM",
    "PANELS",
    "SCRIPTS",
    "build_features",
    "geometry_features",
    "median_cap_height",
]
