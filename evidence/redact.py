"""Face redaction on the evidence copy. AKSHAR.md section 18.

    "Faces blurred on upload."   -- section 18, privacy

An officer photographing a packet in a shop catches whoever was standing behind
it. That person is not under inspection, they did not consent, and their image
would sit in an evidence bucket under a seven-year governance lock. The DPDP
Act 2023 treats it as personal data; section 18 treats it as something we simply
do not want.

Three decisions here are load-bearing.

**Redaction is synchronous, and the hash chain is why.** Section 6 stores an
`image_sha256` inside the scan row, and that row is hash-chained — it cannot be
edited afterwards. So the digest must be taken over the bytes that will actually
exist in the bucket, which means the blur has to happen *before* the row is
written, not in the worker that uploads it. Only the network transfer is
deferrable. Get this backwards and the chain attests to an image nobody can
reproduce, which is exactly the false tamper alarm `evidence/chain.py` warns
about.

**A face printed on the packaging is not a bystander, and blurring it would
destroy the label.** Indian retail is full of them: the Amul girl, a baby on an
infant-formula tin, a model on a shampoo sachet, a face on a soap carton. A
frontal-face cascade cannot tell those from a person, but geometry can — a
printed face is *inside the package box*, and a bystander is not. So a detection
that sits mostly within the detected package is kept, and the count of kept
faces is reported rather than swallowed. Blurring a declaration off a pack in
the name of privacy would be a self-inflicted evidence failure.

**Blur is not enough on its own.** A Gaussian blur is a convolution, and a
convolution is invertible in principle; published deblurring work recovers
recognisable faces from exactly this kind of redaction. So the region is first
reduced to a coarse mosaic — a genuine, lossy discard of information — and only
then softened so the result does not read as a deliberate censor bar. What is
thrown away is thrown away.

**Nothing here raises.** If OpenCV is absent or the cascade will not load, the
result reports `available=False` and the caller decides. The upload handler
fails *closed* on that — it stores no image rather than an unredacted one — while
still writing the scan record, because section 5's L4 rule is that the officer
walks away with a timestamped record no matter what broke.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MOSAIC_BLOCKS = 12
"""Longest side of the mosaic grid a face is reduced to.

Twelve blocks across a face is well below what any recognition system needs and
well below what a person needs. It is chosen as a *count* rather than a pixel
size so a face filling the frame and a face forty pixels wide are destroyed
equally; a fixed block size would leave the large one readable.
"""

ON_PACKAGE_OVERLAP = 0.6
"""Fraction of a face box that must lie inside the package box before we treat
it as printed artwork rather than a person.

Deliberately not 0.95. A pack photographed at an angle has a printed face
crossing the box edge, and a bystander standing behind a small packet overlaps
it slightly. 0.6 separates those two cases; it is a judgement, and the count of
skipped faces is reported so it can be audited rather than trusted.
"""

MIN_FACE_PX = 24
"""Below this the cascade is mostly reporting texture. Blurring noise costs
nothing, but it inflates the reported count and hides real detections."""

_CASCADE_FILE = "haarcascade_frontalface_default.xml"

Box = tuple[int, int, int, int]
"""x, y, w, h in raw image pixels — same convention as `vision.types.XYWH`,
integers because this indexes an array rather than measuring anything."""


@dataclass(frozen=True, slots=True)
class Redaction:
    """What redaction did, in enough detail to defend it later.

    `skipped_on_package` is reported separately from `blurred` on purpose. "We
    blurred two faces" and "we blurred two faces and deliberately left one that
    was printed on the carton" are different statements, and the second is the
    one a manufacturer asking why their brand mascot survived will want.
    """

    image: Any
    """The redacted array, or the input unchanged when nothing was found."""

    available: bool
    """False when OpenCV or the cascade could not be loaded. The image is then
    the input, untouched — the caller must not treat it as redacted."""

    blurred: int = 0
    skipped_on_package: int = 0
    detail: str = ""

    @property
    def changed(self) -> bool:
        return self.blurred > 0

    @property
    def safe_to_store(self) -> bool:
        """May these bytes go into the evidence bucket under a privacy policy?

        True when redaction actually ran, regardless of whether it found
        anything: a photograph with no faces in it is already safe. False only
        when we could not look, because "we did not check" and "there was
        nothing to remove" must never collapse into the same answer.
        """
        return self.available


_cascade: Any | None = None
_cascade_tried = False


def _load_cascade() -> Any | None:
    """Load the frontal-face cascade once per process, or give up quietly.

    A Haar cascade rather than a DNN face detector, and that is a considered
    choice for this job: it ships inside the `opencv-python-headless` wheel we
    already depend on, so there is no extra download, no licence question and no
    `scripts/fetch_models.py` entry that could go missing in a field deployment
    where a blurred face is a legal obligation. It is weaker than a modern
    detector on profile and small faces, which is why `MIN_FACE_PX` is low and
    the scale factor below is fine-grained — we would rather over-detect and
    blur a doorknob than miss a bystander.
    """
    global _cascade, _cascade_tried
    if _cascade_tried:
        return _cascade
    _cascade_tried = True
    try:
        import cv2

        classifier = cv2.CascadeClassifier(cv2.data.haarcascades + _CASCADE_FILE)
        _cascade = None if classifier.empty() else classifier
    except Exception:  # pragma: no cover - opencv missing or built without data
        _cascade = None
    return _cascade


def _overlap_fraction(face: Box, package: Box) -> float:
    """How much of `face` lies inside `package`, as a fraction of the face."""
    fx, fy, fw, fh = face
    px, py, pw, ph = package
    ix = max(0, min(fx + fw, px + pw) - max(fx, px))
    iy = max(0, min(fy + fh, py + ph) - max(fy, py))
    area = fw * fh
    return 0.0 if area <= 0 else (ix * iy) / area


def find_faces(image: Any) -> list[Box]:
    """Frontal faces in raw image space. Empty when unavailable — never raises."""
    classifier = _load_cascade()
    if classifier is None:
        return []
    try:
        import cv2

        grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        grey = cv2.equalizeHist(grey)
        found = classifier.detectMultiScale(
            grey,
            scaleFactor=1.08,
            minNeighbors=5,
            minSize=(MIN_FACE_PX, MIN_FACE_PX),
        )
    except Exception:  # pragma: no cover - defensive; a bad array must not 500
        return []
    return [(int(x), int(y), int(w), int(h)) for x, y, w, h in found]


def mosaic_region(image: Any, box: Box, *, blocks: int = MOSAIC_BLOCKS) -> None:
    """Destroy one region in place: downsample to a grid, then soften.

    The downsample is the redaction — information the array no longer holds
    cannot be recovered from it. The blur afterwards is cosmetic, so the stored
    evidence photograph does not look like it has been censored by hand; a
    report that reads as edited invites the question of what else was edited.
    """
    import cv2

    x, y, w, h = box
    height, width = image.shape[:2]
    x, y = max(0, x), max(0, y)
    w, h = min(w, width - x), min(h, height - y)
    if w <= 0 or h <= 0:
        return

    region = image[y : y + h, x : x + w]
    grid_w = max(1, min(blocks, w))
    grid_h = max(1, min(blocks, h))
    small = cv2.resize(region, (grid_w, grid_h), interpolation=cv2.INTER_AREA)
    coarse = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)

    # Kernel tied to the region, not fixed: a 40 px face and a 400 px face must
    # end up equally unreadable.
    kernel = max(3, (min(w, h) // 6) | 1)
    image[y : y + h, x : x + w] = cv2.GaussianBlur(coarse, (kernel, kernel), 0)


def redact_faces(image: Any, *, package_box: Box | None = None) -> Redaction:
    """Blur bystanders on a copy of `image`; leave printed faces alone.

    The input array is never modified. The pipeline may still be holding it —
    and more importantly, the *measurement* was taken from the unredacted frame
    while the *evidence* is the redacted one. Those are allowed to differ, and
    the scan row's `image_sha256` covers the second.
    """
    if _load_cascade() is None:
        return Redaction(
            image=image,
            available=False,
            detail=(
                "face detection unavailable (OpenCV or its cascade data is "
                "absent); no image may be stored under section 18"
            ),
        )

    faces = find_faces(image)
    if not faces:
        return Redaction(image=image, available=True, detail="no faces detected")

    working = image.copy()
    blurred = 0
    skipped = 0
    for face in faces:
        if package_box is not None and _overlap_fraction(face, package_box) >= ON_PACKAGE_OVERLAP:
            # Printed on the pack. Blurring it would remove label content, which
            # is the evidence — and the person it depicts consented at the point
            # the artwork was commissioned.
            skipped += 1
            continue
        mosaic_region(working, face)
        blurred += 1

    if blurred == 0:
        # Every detection was on the package. Return the ORIGINAL array rather
        # than the untouched copy so the caller's identity check (`is` / hash)
        # sees that nothing changed.
        return Redaction(
            image=image,
            available=True,
            skipped_on_package=skipped,
            detail=f"{skipped} face(s) printed on the package, left intact",
        )

    parts = [f"{blurred} face(s) blurred"]
    if skipped:
        parts.append(f"{skipped} printed on the package, left intact")
    return Redaction(
        image=working,
        available=True,
        blurred=blurred,
        skipped_on_package=skipped,
        detail="; ".join(parts),
    )


def encode_jpeg(image: Any, *, quality: int = 92) -> bytes:
    """Encode the bytes that will be hashed, stored, and shown in a report.

    Quality 92 rather than the usual 85: this is the copy a measurement gets
    re-checked against six months later, and JPEG quantisation attacks exactly
    the thin strokes small print is made of. The extra ~30% in size buys back
    the legibility of a 1 mm numeral, and section 6's retention rules — not
    compression — are what keep the storage bill at 2.1 GB per 10,000 scans.
    """
    import cv2

    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:  # pragma: no cover - only on a malformed array
        raise ValueError("could not encode image as JPEG")
    return bytes(buffer.tobytes())


def decode_image(payload: bytes) -> Any:
    """Bytes off the wire to an array. Raises `ValueError` on anything else.

    Deliberately strict, and the only place in the upload path that is. A
    non-image upload is a malformed request — a 400 — not something to degrade
    around; section 5's degradation ladder is about *photographs we cannot
    read*, not about a client sending a PDF.
    """
    import cv2
    import numpy as np

    array = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if array is None:
        raise ValueError("upload is not a decodable image")
    return array


__all__ = [
    "MIN_FACE_PX",
    "MOSAIC_BLOCKS",
    "ON_PACKAGE_OVERLAP",
    "Box",
    "Redaction",
    "decode_image",
    "encode_jpeg",
    "find_faces",
    "mosaic_region",
    "redact_faces",
]
