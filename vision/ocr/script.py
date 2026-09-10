"""Which script is this region in — and therefore which recognition head runs.

    "Languages — the requirement that catches everyone out."   -- section 7

Rule 9(1) permits the declarations in Hindi *or* English. So a pack declaring
only in Devanagari is fully compliant, and a system that runs only the Latin
head reads nothing, finds nothing, and reports every declaration missing. That
is not a degraded result; it is a false accusation, generated at scale, against
exactly the domestic manufacturers the rules exist to regulate.

**Detected geometrically, not with a model.** Devanagari is written hanging
from a *shirorekha* — the horizontal head-line joining the letters of a word.
It is the single most distinctive visual feature of the script, and it shows up
in a horizontal ink projection as a sharp spike near the top of the text band.
Latin has no such line; its projection is broadest around the x-height.

That gives a discriminator that is free, deterministic, explainable in one
sentence, and does not need the 4 MB script-classifier head to be downloaded
before an officer can read a Hindi label. Where it is unsure, the caller runs
both heads and keeps the more confident reading — correctness bought with
latency, on the minority of regions only.
"""

from __future__ import annotations

import unicodedata

import cv2
import numpy as np

from vision.measure.cap_height import binarise
from vision.types import Image, Script

_SPIKE_RATIO = 1.85
"""How much denser the head-line row must be than the region's mean ink row to
count as a shirorekha. Latin text with a heavy underline can also spike, which
is why the spike must additionally sit in the TOP third of the ink band."""

_TOP_BAND = 0.38
"""The shirorekha sits at the top of the letters. An underline sits at the
bottom, and confusing the two would send Latin text to the Devanagari head."""

_MIN_CONFIDENT_MARGIN = 0.35


def script_of_text(text: str) -> Script:
    """Script of an already-decoded string — used by the listing_text channel.

    That channel has no pixels at all, so the geometric test cannot run and the
    Unicode block is the only evidence there is. It is also conclusive, which
    is why this is the simpler of the two functions.
    """
    devanagari = latin = 0
    for char in text:
        if not char.isalpha():
            continue
        try:
            name = unicodedata.name(char)
        except ValueError:  # pragma: no cover - unnamed codepoint
            continue
        if name.startswith("DEVANAGARI"):
            devanagari += 1
        elif name.startswith("LATIN"):
            latin += 1

    if devanagari == 0 and latin == 0:
        return "other"
    return "devanagari" if devanagari > latin else "latin"


def detect_script(crop: Image) -> tuple[Script, float]:
    """Script of a text crop, with a confidence in [0, 1].

    A confidence below `_MIN_CONFIDENT_MARGIN` means "run both heads"; see
    `vision.ocr.roi`. Returning a shrug is far better than committing to the
    wrong head, because the wrong head does not fail — it emits Latin letters
    for Devanagari glyphs and the field classifier then sees plausible junk.
    """
    if crop is None or crop.size == 0:
        return "other", 0.0
    gray = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if min(gray.shape[:2]) < 6:
        return "other", 0.0

    binary, _ = binarise(gray)
    ink_per_row = (binary > 0).sum(axis=1).astype(np.float64)
    inked = np.flatnonzero(ink_per_row > 0)
    if inked.size < 4:
        return "other", 0.0

    top, bottom = int(inked[0]), int(inked[-1])
    band = ink_per_row[top : bottom + 1]
    if band.size < 4 or band.mean() <= 0:
        return "other", 0.0

    peak_index = int(band.argmax())
    peak_ratio = float(band.max() / band.mean())
    relative_position = peak_index / max(band.size - 1, 1)

    has_headline = peak_ratio >= _SPIKE_RATIO and relative_position <= _TOP_BAND
    # Confidence scales with how pronounced the spike is, saturating at 2.5x.
    strength = min(1.0, max(0.0, (peak_ratio - 1.0) / 1.5))

    if has_headline:
        return "devanagari", strength
    return "latin", max(0.0, 1.0 - strength)


def needs_both_heads(confidence: float) -> bool:
    """Should the caller pay for a second recognition pass on this region?"""
    return confidence < _MIN_CONFIDENT_MARGIN


__all__ = ["detect_script", "needs_both_heads", "script_of_text"]
