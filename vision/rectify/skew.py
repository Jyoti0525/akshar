"""Residual baseline skew — the number M1 is graded on.

M1's acceptance criterion is *"printed lines deviate under 2 degrees from
horizontal after warping, across the 40 test photos"*. That is a measurement,
so it needs a measuring function rather than an eyeball, and it needs to be the
same function in the test harness and in the runtime deskew pass.

Method: binarise, dilate horizontally so the characters of one line merge into
a single blob, then take the median orientation of the blobs that look like
text lines. Median rather than mean because one long blob across a barcode or a
pack seam would otherwise drag the estimate several degrees.
"""

from __future__ import annotations

import cv2
import numpy as np

from vision.types import Image

_MIN_ASPECT = 2.5
"""A text line is wider than it is tall. Below this it is a logo, a character
or noise, and its orientation says nothing about the baseline."""

_MIN_BLOB_AREA_FRAC = 0.0002
_MAX_BLOB_AREA_FRAC = 0.35
"""Upper bound rejects a blob that has swallowed the whole panel — usually a
dark background that binarised the wrong way round."""


def _line_blobs(gray: Image) -> list[tuple[float, float]]:
    """Return (angle_deg, area) for each blob that plausibly is a text line."""
    h, w = gray.shape[:2]
    if h < 16 or w < 16:
        return []

    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 12
    )

    # Merge characters along the writing direction. The kernel is sized from
    # the image width so it behaves the same on a 400 px crop and a 2000 px one.
    kernel_w = max(5, int(w * 0.02) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_w, 1))
    merged = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)

    # RETR_LIST, not RETR_EXTERNAL. An outer contour hides everything inside
    # it, and text is very often inside something: a printed border box around
    # the declarations, or — on an unrectified frame — the pack's own outline
    # against a darker shelf. With EXTERNAL those photographs reported no text
    # lines at all and the skew estimate silently returned None. Area and
    # aspect filtering already rejects the enclosing shapes themselves.
    contours, _ = cv2.findContours(merged, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    frame_area = float(h * w)
    out: list[tuple[float, float]] = []

    for contour in contours:
        area = cv2.contourArea(contour)
        if not (frame_area * _MIN_BLOB_AREA_FRAC <= area <= frame_area * _MAX_BLOB_AREA_FRAC):
            continue
        (_, _), (rw, rh), angle = cv2.minAreaRect(contour)
        if rw <= 0 or rh <= 0:
            continue

        # cv2 reports the angle of the rectangle's first edge, which flips as
        # the box passes 45 degrees. Normalise to "how far off horizontal is
        # the LONG axis", which is the only thing a baseline means.
        if rw < rh:
            rw, rh = rh, rw
            angle = angle - 90.0
        if rh <= 0 or rw / rh < _MIN_ASPECT:
            continue

        angle = ((angle + 45.0) % 90.0) - 45.0
        out.append((angle, area))

    return out


def estimate_skew(image: Image) -> float | None:
    """Median baseline deviation from horizontal, in degrees.

    Positive means the text runs downhill to the right. Returns None when the
    crop contains nothing line-shaped — a blank panel or a failed rectification
    — because reporting 0.0 there would claim a perfectly level label we never
    actually measured.
    """
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blobs = _line_blobs(gray)
    if len(blobs) < 2:
        return None
    angles = np.array([a for a, _ in blobs], dtype=np.float64)
    return float(np.median(angles))


def deskew(image: Image, max_correction_deg: float = 15.0) -> tuple[Image, float]:
    """Rotate out the residual skew. Returns (image, degrees applied).

    Capped at ``max_correction_deg``: a larger estimate means the blob analysis
    latched onto something that is not text, and rotating a photo 40 degrees on
    that basis would turn a recoverable scan into an unrecoverable one.
    """
    angle = estimate_skew(image)
    if angle is None or abs(angle) < 0.1 or abs(angle) > max_correction_deg:
        return image, 0.0

    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    rotated = cv2.warpAffine(
        image,
        matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rotated, angle


__all__ = ["deskew", "estimate_skew"]
