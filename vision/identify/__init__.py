"""M9 identity — barcode (exact), pHash (near-exact), embedding (similar).

Computed before any model runs, because exit zero depends on it: a repeat SKU
returns a stored verdict in about 60 ms without touching the detector or OCR.
"""

from __future__ import annotations

import time

from vision import runtime
from vision.identify import barcode, embed, phash
from vision.identify.phash import MAX_HAMMING, from_hex, hamming, matches, to_hex
from vision.types import Identity, Image

__all__ = [
    "MAX_HAMMING",
    "Identity",
    "barcode",
    "embed",
    "from_hex",
    "hamming",
    "identify",
    "matches",
    "phash",
    "to_hex",
]


def identify(
    rectified: Image,
    raw: Image | None = None,
    *,
    with_embedding: bool = False,
) -> tuple[Identity, float]:
    """Everything we can cheaply know about which product this is.

    Returns (identity, elapsed_ms). The barcode is looked for in the RAW frame
    when one is supplied: rectification warps to the label face and a barcode
    on a side panel is often cropped away by it.

    The embedding is off by default. It is a model inference, and exit zero
    must stay cheap — section 4 budgets 18 ms for hash plus cache lookup, and
    a 224x224 MobileNet pass would triple that on every scan to help only the
    minority that miss both exact keys.
    """
    started = time.perf_counter()

    code = barcode.decode(raw if raw is not None else rectified)
    if code is None and raw is not None:
        code = barcode.decode(rectified)

    vector = None
    if with_embedding:
        try:
            vector = embed.embed(rectified)
        except runtime.ModelUnavailableError:
            vector = None

    identity = Identity(phash=phash.phash(rectified), barcode=code, embedding=vector)
    return identity, (time.perf_counter() - started) * 1000.0
