"""`ScanContext` — one package, its photographs, and one named slot per block.

AKSHAR.md section 8b:

    ScanContext { scan_id, original_image }
      +B1 quality        +B2 package_region   +B3 geometry, transforms, scale
      +B4 product_match  +B5 evidence_plan    +B6/B7 recognised_regions
      +B8 DeclarationSet +B9 measurements     +B10 verdicts

    "Additive-only is what makes a finding reproducible six months later. If B9
     could overwrite B7's output, we could not show what the system actually
     read."

**Two deviations from the sketch above, both stated rather than absorbed.**

*First, the per-block additivity was already structural and is not re-implemented
here.* `ScanOutcome` is a frozen dataclass carrying one named field per block —
`quality`, `framing`, `detection`, `rectified`, `scale`, `identity`, `ocr`,
`declarations` — and it is constructed once, at the end of `scan()`, from local
variables. There is no code path that can overwrite a block's output because
there is no assignment to overwrite: a frozen dataclass built in one expression
is a stronger guarantee than a context object with a `set()` that raises, and
`test_context.py` asserts the frozen-ness rather than trusting it. What this
module adds is the dimension that was genuinely missing, which is *frames*.

*Second, there is no `verdicts` slot.* This module lives in `vision/`, and a
slot for verdicts here would mean the extractor holds the decision — the exact
wall section 3 draws and `tests/test_boundaries.py` enforces. `api/scanning.py`
pairs a context with the verdict list it produced; the two travel together and
neither owns the other.

---------------------------------------------------------------------------
WHAT THE CONTEXT IS FOR
---------------------------------------------------------------------------
An officer photographs a pack from three sides. Three frames go through `scan()`
independently — each gets its own quality gate, its own rectification, its own
scale, because each is a different photograph of a different plane. The context
holds all three, nominates one as primary for the geometry that can only belong
to a single image, and hands `rules.engine` the union of what they read.

A frame that B1 rejected, or that showed no package, stays in `frames`. It
contributed no declaration and it is still part of the record: "the second
photograph was too blurred to measure" is a thing the officer is entitled to be
told, and it is a thing an auditor is entitled to find six months later.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from contracts import CaptureQuality, DeclarationSet, Framing
from vision.multiframe import primary_frame, union

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from vision.pipeline import ScanOutcome
    from vision.types import XYWH, DetectionResult, Identity, Image, OcrResult, ScaleEstimate


@dataclass(frozen=True, slots=True)
class ScanContext:
    """The frames of one scan. Frames are appended and never replaced."""

    scan_id: str
    frames: tuple[ScanOutcome, ...] = ()

    # -- additive-only -------------------------------------------------------

    def add(self, outcome: ScanOutcome) -> ScanContext:
        """Append one photograph's outcome. Returns a new context.

        The only mutator this class has, and it only ever grows the tuple.
        There is deliberately no `replace_frame`, no `set_quality`, and no
        setter of any kind: the way to guarantee nothing silently overwrites
        anything is to write no code that could.
        """
        return replace(self, frames=(*self.frames, outcome))

    @classmethod
    def of(cls, scan_id: str, outcomes: Sequence[ScanOutcome]) -> ScanContext:
        return cls(scan_id=scan_id, frames=tuple(outcomes))

    # -- which frame the geometry belongs to ---------------------------------

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def read_frames(self) -> tuple[int, ...]:
        """Indices of the photographs that produced declarations.

        The others — rejected by B1, no package in frame, nothing legible — are
        still in `frames`, and their `quality` and `framing` are what the
        officer's screen has to say about them.
        """
        return tuple(
            index
            for index, frame in enumerate(self.frames)
            if frame.declarations is not None
        )

    @property
    def primary_index(self) -> int | None:
        """The frame whose geometry the union carries. See `multiframe`."""
        read = self.read_frames
        if not read:
            return None
        sets = [self.frames[index].declarations for index in read]
        return read[primary_frame(sets)]  # type: ignore[arg-type]

    @property
    def primary(self) -> ScanOutcome | None:
        index = self.primary_index
        if index is None:
            return self.frames[0] if self.frames else None
        return self.frames[index]

    # -- one named slot per block, read off the primary frame ----------------
    #
    # A block's output describes the photograph it ran on, so on a multi-frame
    # scan these name the primary frame's. `frames` is there for anything that
    # needs all of them, and `declarations` below is the only slot that is a
    # genuine combination rather than a choice.

    @property
    def rectified(self) -> Image | None:  # B3
        """The primary frame's flattened label, for `evidence/annotate.py`.

        Section 8b's sketch names an `original_image` slot and this is not it:
        `ScanOutcome` deliberately does not retain the photograph it was handed,
        and adding a slot for it here would keep every frame's full-resolution
        pixels alive for the length of a request in exchange for nothing —
        `api/scanning.py` already holds the bytes it decoded, and it is the only
        caller that wants them.
        """
        return getattr(self.primary, "rectified", None)

    @property
    def quality(self) -> CaptureQuality | None:  # B1
        return getattr(self.primary, "quality", None)

    @property
    def framing(self) -> Framing | None:  # B1, second half
        return getattr(self.primary, "framing", None)

    @property
    def package_region(self) -> XYWH | None:  # B2
        detection = getattr(self.primary, "detection", None)
        best = detection.best_package() if detection is not None else None
        return best.box if best is not None else None

    @property
    def detection(self) -> DetectionResult | None:  # B2
        return getattr(self.primary, "detection", None)

    @property
    def scale(self) -> ScaleEstimate | None:  # B3
        return getattr(self.primary, "scale", None)

    @property
    def product_match(self) -> Identity | None:  # B4
        return getattr(self.primary, "identity", None)

    @property
    def recognised_regions(self) -> OcrResult | None:  # B6/B7
        return getattr(self.primary, "ocr", None)

    @property
    def declarations(self) -> DeclarationSet | None:  # B8
        """The union of every frame that read something. The engine's input.

        `None` when no frame produced one, which is the multi-frame form of
        section 5's L4: the photographs, their time and their place are still
        recorded, and there is nothing that could honestly be judged.
        """
        read = self.read_frames
        if not read:
            return None
        sets = [self.frames[index].declarations for index in read]
        return union(sets, frame_ids=read)  # type: ignore[arg-type]

    # -- what to tell the officer -------------------------------------------

    def unread_frames(self) -> tuple[tuple[int, str], ...]:
        """`(frame index, why it contributed nothing)` for each frame that did.

        Reported rather than dropped. Three photographs of which one was
        unusable is a different scan from two photographs, and the officer who
        took three deserves to know which one to take again.
        """
        return tuple(
            (index, frame.message or frame.exit_path)
            for index, frame in enumerate(self.frames)
            if frame.declarations is None
        )


__all__ = ["ScanContext"]
