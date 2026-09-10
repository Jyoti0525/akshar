"""EAN-13 decode — tried before the perceptual hash, because it is exact.

    "Barcode lookup first, then pHash exact match, then pgvector cosine for
     near-duplicates."                                    -- section 17, M9

Order matters. A barcode is an exact key assigned by GS1; a perceptual hash is
a similarity measure with a threshold, and a threshold can be wrong. When a
barcode is readable we do not need to reason about Hamming distance at all.

**It is an identity key and nothing more.** We never look the barcode up
against an external product database. Two reasons: an inspection must work with
no network (section 5), and a third-party database's idea of a product's net
quantity is not evidence of what is printed on *this* packet. The barcode tells
us which SKU we are looking at, so we can reuse a verdict *we* produced. It
never supplies a fact that a rule then judges.

**Implementation.** OpenCV 4.x ships `cv2.barcode.BarcodeDetector`, so no
native `pyzbar`/`zbar` dependency is needed — which matters because that
dependency is a recurring source of Windows install failures and this project
has to build on a teammate's laptop the week before a demo. `pyzbar` is used
if present, as a second opinion on hard crops.
"""

from __future__ import annotations

import re

import cv2

from vision.types import Image

_EAN13 = re.compile(r"^\d{13}$")
_EAN8 = re.compile(r"^\d{8}$")
_UPCA = re.compile(r"^\d{12}$")

_INDIA_PREFIXES = ("890",)
"""GS1 prefix for India. Not used to accept or reject — a lawfully imported
product carries a foreign prefix — only to annotate the report, where "GS1
prefix 890 (India)" is a useful line beside a country-of-origin declaration."""


def checksum_valid(code: str) -> bool:
    """GS1 modulo-10 check digit.

    Worth verifying rather than trusting the decoder: a misread digit produces
    a valid-looking 13-character string that would key the cache to the wrong
    product and replay another SKU's verdicts onto this one. That is a wrong
    verdict with no visible cause, so the check digit is not optional.
    """
    if not code.isdigit() or len(code) not in (8, 12, 13):
        return False
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    # Weights alternate 3 and 1 from the rightmost body digit leftwards.
    total = sum(d * (3 if (len(body) - index) % 2 == 1 else 1) for index, d in enumerate(body))
    return (10 - total % 10) % 10 == check


def _with_opencv(image: Image) -> list[str]:
    try:
        detector = cv2.barcode.BarcodeDetector()
    except AttributeError:  # pragma: no cover - very old OpenCV
        return []
    ok, decoded, *_ = detector.detectAndDecodeWithType(image)
    if not ok or not decoded:
        return []
    return [text for text in decoded if text]


def _with_pyzbar(image: Image) -> list[str]:  # pragma: no cover - optional extra
    try:
        from pyzbar import pyzbar
    except ImportError:
        return []
    try:
        return [obj.data.decode("ascii", "ignore") for obj in pyzbar.decode(image)]
    except Exception:
        return []


def decode(image: Image) -> str | None:
    """First checksum-valid EAN-13/EAN-8/UPC-A in the frame, else None.

    Returns None rather than a best guess. An unreadable barcode simply means
    the pHash path runs instead, which costs 12 ms — far cheaper than a wrong
    identity.
    """
    if image is None or image.size == 0:
        return None

    for candidate in (*_with_opencv(image), *_with_pyzbar(image)):
        text = candidate.strip()
        if (_EAN13.match(text) or _EAN8.match(text) or _UPCA.match(text)) and checksum_valid(text):
            return text
    return None


def is_indian_prefix(code: str | None) -> bool:
    return bool(code) and code.startswith(_INDIA_PREFIXES)  # type: ignore[union-attr]


__all__ = ["checksum_valid", "decode", "is_indian_prefix"]
