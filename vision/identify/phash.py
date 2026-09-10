"""Perceptual hash — exit zero, and the reason the system gets faster with use.

    "Perceptual hash: pHash (DCT-based), 64-bit, Hamming <= 8. dHash and aHash
     are faster but break under the lighting variation of shop photography,
     which is exactly our condition."                     -- section 15b

    "Exit zero — the cache. Computing a perceptual hash costs about 12 ms. We
     do it *before* touching a model. If this SKU has been seen before, we
     replay the stored verdict and finish in roughly 60 ms."  -- section 4

**Why this is the single most important optimisation.** Section 3, principle
four: *a violation is printed at design time, so it's identical on every packet
of that SKU across the country. Photograph one and you've settled it for all of
them.* The hash is what recognises "one we have already settled".

**The claim it supports.** "The system gets faster the more it is used, because
cache hit rate climbs with coverage. Manual inspection has no such property —
the millionth packet costs exactly what the first did."

Computed on the *rectified* label, not the raw frame, so two photographs of the
same pack taken from different angles hash to the same value. Hashing the raw
frame would make the cache miss on precisely the variation it exists to absorb.
"""

from __future__ import annotations

import cv2
import numpy as np

from vision.types import Image

HASH_SIZE = 8
"""8x8 low-frequency block, excluding DC — 64 bits, matching section 15b."""

DCT_SIZE = 32
"""Input is reduced to 32x32 before the DCT. Larger buys nothing: we keep only
the top-left 8x8 either way, and the cost is quadratic."""

MAX_HAMMING = 8
"""Section 15b. Two images of the same SKU under different shop lighting
typically differ by 2-6 bits; different SKUs from the same brand family
typically differ by 15 or more. Eight sits in the gap, not at either edge."""


def phash(image: Image) -> int:
    """64-bit DCT perceptual hash of a rectified label.

    The DC coefficient is excluded deliberately: it encodes overall
    brightness, which is exactly the thing that varies between a photograph
    taken under a tube light and one taken in a doorway. Keeping it would make
    the hash sensitive to the one variable we most need it to ignore.
    """
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    reduced = cv2.resize(gray, (DCT_SIZE, DCT_SIZE), interpolation=cv2.INTER_AREA)

    coefficients = cv2.dct(reduced.astype(np.float32))
    block = coefficients[:HASH_SIZE, :HASH_SIZE].flatten()

    # Median over the block WITHOUT the DC term, then compare all 64 including
    # the DC position — this is the standard pHash formulation and keeps the
    # output exactly 64 bits.
    median = float(np.median(block[1:]))

    bits = 0
    for index, value in enumerate(block):
        if value > median:
            bits |= 1 << index
    return bits


NORMALISE_SIZE = 256
"""Working resolution for the cheap pre-hash flatten. See `normalise_for_hash`."""


def normalise_for_hash(image: Image, size: int = NORMALISE_SIZE) -> Image:
    """Flatten the label cheaply, purely so the hash is angle-invariant.

    SPEC DELTA (docs/spec-deltas.md). Section 4 puts "pHash + cache lookup" at
    18 ms *before* detection, and lists "Rectify" at 55 ms afterwards — which
    implies hashing the raw frame. But a raw-frame hash moves by far more than
    eight bits when the same packet is photographed from a different angle, so
    exit zero would miss the cache on exactly the variation it exists to
    absorb. That is the same argument section 15b uses to reject dHash and
    aHash for being lighting-sensitive; perspective is the other axis of shop
    photography.

    The resolution is that the 55 ms figure is for rectifying at full
    resolution, which is only needed for *measurement*. Finding the quad on a
    256 px thumbnail costs a couple of milliseconds and is ample for a hash
    computed on a 32x32 DCT. So the cheap flatten runs before the hash, and the
    expensive one runs only on a cache miss.
    """
    from vision.rectify.rectify import find_label_quad, warp_to_quad

    h, w = image.shape[:2]
    scale = min(1.0, size / float(max(h, w)))
    small = (
        cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if scale < 1.0
        else image
    )

    quad = find_label_quad(small)
    if quad is None:
        return small
    warped, _, _ = warp_to_quad(small, quad)
    return warped


def hamming(left: int, right: int) -> int:
    return int((left ^ right).bit_count())


def matches(left: int, right: int, *, threshold: int = MAX_HAMMING) -> bool:
    return hamming(left, right) <= threshold


def to_hex(value: int) -> str:
    """Sixteen hex characters — the form stored in `skus.phash` and IndexedDB."""
    return f"{value & ((1 << 64) - 1):016x}"


def from_hex(text: str) -> int:
    return int(text, 16)


__all__ = [
    "DCT_SIZE",
    "HASH_SIZE",
    "MAX_HAMMING",
    "NORMALISE_SIZE",
    "from_hex",
    "hamming",
    "matches",
    "normalise_for_hash",
    "phash",
    "to_hex",
]
