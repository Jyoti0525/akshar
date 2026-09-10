"""Letterbox to 640 px — and the arithmetic to get back out again.

    "Detection runs at 640 px because it only needs to find boxes. Recognition
     runs at native resolution, but only on crops. A twelve-megapixel photo is
     never processed whole."                              -- section 4

The subtlety is the return journey. Every box the detector emits is in
letterboxed 640-space, and every box the *measurement* stage uses is in the
original photograph's pixels. Getting the inverse wrong does not crash — it
produces boxes that are plausibly placed and systematically the wrong size,
which is the worst kind of bug this project can have, because a wrong size is a
wrong millimetre reading is a wrong verdict.

So the forward transform returns its own inverse alongside the tensor, and
nothing reconstructs it by hand.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from vision.types import XYWH, Image

IMG_SIZE = 640


@dataclass(frozen=True, slots=True)
class Letterbox:
    """The resize-and-pad that was applied, and how to undo it."""

    scale: float
    pad_x: float
    pad_y: float
    original_w: int
    original_h: int

    def to_original(self, box: XYWH) -> XYWH:
        """Map a box from letterboxed 640-space back to the source photograph."""
        x, y, w, h = box
        return (
            (x - self.pad_x) / self.scale,
            (y - self.pad_y) / self.scale,
            w / self.scale,
            h / self.scale,
        )

    def clip(self, box: XYWH) -> XYWH:
        """Clamp to the frame. A box half off the edge is common and legitimate
        — an officer's hand crops the pack — but a negative width is not."""
        x, y, w, h = box
        x0 = min(max(x, 0.0), float(self.original_w))
        y0 = min(max(y, 0.0), float(self.original_h))
        x1 = min(max(x + w, 0.0), float(self.original_w))
        y1 = min(max(y + h, 0.0), float(self.original_h))
        return (x0, y0, max(x1 - x0, 1.0), max(y1 - y0, 1.0))


def letterbox(image: Image, size: int = IMG_SIZE) -> tuple[np.ndarray, Letterbox]:
    """Resize preserving aspect ratio, pad to square, return NCHW float32 RGB.

    Padding is grey (114) rather than black, matching the value the model was
    trained with. Padding with black shifts the input distribution and costs
    real mAP on packs photographed near the frame edge.
    """
    h, w = image.shape[:2]
    scale = min(size / float(w), size / float(h))
    new_w, new_h = round(w * scale), round(h * scale)

    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    pad_x, pad_y = (size - new_w) // 2, (size - new_h) // 2
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = (
        resized if resized.ndim == 3 else cv2.cvtColor(resized, cv2.COLOR_GRAY2BGR)
    )

    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    tensor = np.transpose(rgb, (2, 0, 1))[np.newaxis, ...]
    return np.ascontiguousarray(tensor), Letterbox(scale, float(pad_x), float(pad_y), w, h)


__all__ = ["IMG_SIZE", "Letterbox", "letterbox"]
