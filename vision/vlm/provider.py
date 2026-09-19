"""A reader that looks at the label, and the wall between it and the rest.

**Why this exists, measured rather than assumed.** On 2026-09-19 three packs
from `data/declaration_blocks/` were read twice: once by the OCR path in
`vision/ocr/`, and once by a vision-language model given nothing but the same
photograph. Scored against the hand-labelled ground truth:

    pack                            model     OCR path
    coconut oil pouch                 6/6          0/6
    honey jar                         5/5          1/5   + 2 wrong values
    Ship matchbox                     6/6          0/6   + 1 wrong value
                                    -----        -----
                                    17/17         1/17

The wrong values are the part that matters. On the honey jar the label column
and the value column do not line up:

    Net Weight:  500 g        335.00
    MRP NRs.                  NB00246
    Incl., of all taxes       07/20

The OCR path reported **500** as the maximum retail price. The price is 335.00,
and it was sitting in the same photograph filed as unclassified text. Pairing
those two columns needs meaning -- 335.00 is a price, NB00246 is a lot code,
07/20 is a date -- and a classifier that sees one line at a time cannot do it.

---------------------------------------------------------------------------
WHAT THIS MODULE IS ALLOWED TO BE
---------------------------------------------------------------------------
A `Reader` takes an image and a prompt and returns a string. That is the whole
interface, and it is deliberately this narrow:

- **`vision/` gains no vendor SDK.** No client library, no API surface, no
  credential handling anywhere in the pipeline. The application layer supplies
  something with a `read` method and this package never learns what it is.
- **The pipeline never imports a network library.** `availability()` answers
  without opening a socket, so a scan on a phone in a warehouse basement costs
  nothing to ask.
- **Absent is the default and absent is fine.** No reader configured means the
  OCR path runs exactly as it does today. This is a tier in the degradation
  ladder, never a dependency: section 5's L4 promise -- an officer walks away
  with a timestamped record even in the worst case -- would be void if a scan
  needed a network to produce declarations.

**What it may never be.** It returns text about a photograph. It does not
return a verdict, it is not asked for one, and `rules/` does not import this
package or anything downstream of it. The model says what the pack says; the
rulepack says whether that complies. That boundary is the reason a finding can
be defended, and no accuracy number is worth trading it for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Reader(Protocol):
    """Anything that can look at an image and answer in text.

    Implemented by the caller -- `api/` or a test -- never here. The image
    arrives as encoded bytes rather than an array so that this signature
    commits to nothing about OpenCV, tensors, or colour order.
    """

    name: str
    """Recorded into `scans.model_versions`. A finding you cannot reproduce is
    a finding you cannot defend, so this has to identify the exact model and
    not a family: `gpt-4o-2024-08-06`, not `gpt-4o`."""

    def read(self, image: bytes, *, prompt: str, media_type: str = "image/jpeg") -> str:
        """Return the model's reply verbatim. Raise on transport failure."""
        ...


@dataclass(frozen=True, slots=True)
class Availability:
    ready: bool
    name: str = ""
    detail: str = ""


_reader: Reader | None = None


def install(reader: Reader | None) -> None:
    """Hand the pipeline a reader, or `None` to take it away again.

    Process-global on purpose, and set by the application at startup -- the
    same shape `vision.runtime` uses for model sessions. Threading it through
    `scan()` as an argument would put it in the signature of every caller
    including the offline browser path, which can never have one.
    """
    global _reader
    _reader = reader


def installed() -> Reader | None:
    return _reader


def availability() -> Availability:
    """Whether a reader is present. Never opens a connection, never raises."""
    reader = _reader
    if reader is None:
        return Availability(ready=False, detail="no vision reader is configured")
    name = str(getattr(reader, "name", "") or "")
    if not name:
        # An unnamed reader cannot be recorded in `model_versions`, and a
        # declaration whose origin cannot be named has no business in a legal
        # record. Refusing is the conservative direction.
        return Availability(ready=False, detail="the configured reader does not name itself")
    return Availability(ready=True, name=name)


def read(image: bytes, *, prompt: str, media_type: str = "image/jpeg") -> str | None:
    """Ask the installed reader, or `None` for every reason it cannot answer.

    Swallows the exception deliberately. A timeout, a rate limit, an expired
    key and a malformed reply are all the same thing to a scan in progress:
    this tier is unavailable, the OCR path answers instead, and nothing fails.
    """
    reader = _reader
    if reader is None:
        return None
    try:
        reply = reader.read(image, prompt=prompt, media_type=media_type)
    except Exception:  # every failure is the same outcome here: no reading
        return None
    return reply if isinstance(reply, str) and reply.strip() else None


def encode(image: Any) -> bytes | None:
    """A rectified label as JPEG bytes, or `None` if OpenCV is not here."""
    try:
        import cv2
    except Exception:  # pragma: no cover - OpenCV is a hard dependency of vision/
        return None
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    return buffer.tobytes() if ok else None


__all__ = ["Availability", "Reader", "availability", "encode", "install", "installed", "read"]
