"""Capture quality — the pre-gate. AKSHAR.md section 8, block B1.

SPEC DELTA (P1). Section 9 freezes `DeclarationSet` without any of this;
section 8's B1 then names `CaptureQuality` as its output. Recorded in
docs/spec-deltas.md alongside `PackageContext`.

    "A blurry or glare-blown photo entering the pipeline produces a confident,
     wrong millimetre measurement. That is the single worst failure this project
     can have, and the fix costs nothing."                        -- section 8

**This is a measurement, not a verdict**, and the distinction is the same one
section 3 draws between B9 and B10. `usable=False` says the photograph cannot
support a measurement; it never says the package is non-compliant. A rejected
frame produces `NO_DATA` on the geometry rules and an L4 record, which is
section 5's answer, not a failure.

Nothing in `rules/` reads this. It lives in `contracts/` because the API and the
web app both show it to the officer — "move closer, there is glare on the
label" is only useful before the photograph is taken again.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

QualityFault = Literal["blur", "glare", "underexposed", "overexposed", "resolution"]
"""Why a frame was rejected. One value per check B1 performs.

Deliberately an enum rather than free text: the officer's screen has to render
different advice for each ("hold still" versus "tilt away from the light"), and
a string comparison against a sentence is how that quietly stops working.
"""

ADVICE: dict[QualityFault, str] = {
    "blur": "Hold the camera still, or move slightly further back and tap to focus.",
    "glare": "Tilt the pack away from the light, or shade it with your hand.",
    "underexposed": "There is not enough light on the label. Move into better light.",
    "overexposed": "The label is washed out. Move out of direct sun or reduce exposure.",
    "resolution": "Move closer so the pack fills more of the frame.",
}
"""What to tell the person holding the phone. Section 11: the screen has to be
usable one-handed in a shop, and "quality check failed" is not usable."""


class CaptureQuality(BaseModel):
    """Is this image usable at all?

    Every score is normalised to 0..1 with **higher meaning better**, including
    `glare_ratio`'s inverse `glare_score`. Mixing directions across a scoreboard
    is how a threshold ends up applied the wrong way round, and the wrong way
    round here means accepting the blurry frames and rejecting the sharp ones.
    """

    model_config = ConfigDict(frozen=True)

    usable: bool

    blur_score: float = Field(ge=0.0, le=1.0)
    """Variance of the Laplacian, normalised. 1.0 is knife-sharp, 0.0 is
    unreadable. It is a *relative* measure — a sharp photograph of a
    low-contrast kraft-paper label scores lower than a sharp photograph of
    glossy print — which is why the threshold is deliberately permissive and why
    B1 rejects rather than ranks."""

    glare_ratio: float = Field(ge=0.0, le=1.0)
    """Fraction of the frame that is blown-out specular highlight: bright and
    unsaturated at once. Plain white packaging is bright and unsaturated too,
    so this counts only pixels at the very top of the range."""

    exposure_score: float = Field(ge=0.0, le=1.0)
    """How much of the histogram is usable, rather than piled against either
    end. A correctly exposed label scores near 1.0."""

    width: int = Field(ge=0)
    height: int = Field(ge=0)

    faults: tuple[QualityFault, ...] = ()
    """Every check that failed, not only the first. A photograph taken into the
    sun is usually both over-exposed and glare-blown, and telling the officer
    one of the two sends them back for a second attempt that fails the same
    way."""

    reason: str | None = None
    """One sentence, for the officer. None when `usable`."""

    elapsed_ms: float = 0.0
    """Section 4 budgets B1 at under 15 ms. Measured, not assumed — a gate that
    costs more than the work it saves is not a gate."""

    @property
    def glare_score(self) -> float:
        """`glare_ratio` in the same direction as every other score."""
        return 1.0 - self.glare_ratio

    def advice(self) -> tuple[str, ...]:
        """What to do about it, in the order the faults were detected."""
        return tuple(ADVICE[fault] for fault in self.faults)


# ---------------------------------------------------------------------------
# Framing — the post-read half of the same question
# ---------------------------------------------------------------------------

FramingFault = Literal["no_declaration_panel", "wrong_panel"]
"""Why a frame carries no declaration to judge, when the frame itself is fine.

`CaptureQuality` above answers *how* the photograph was taken. This answers
*what was photographed*, and the two cannot be merged, because they are
detectable at opposite ends of the pipeline. Blur has to be caught in the
pixels before anything reads them — B1's docstring explains why the recogniser's
own confidence cannot see it. Framing is the mirror image: **nothing in the raw
pixels distinguishes a sharp photograph of a declaration panel from a sharp
photograph of the brand face.** You only know the panel is absent once you have
looked for it and not found it.

Measured on the 122-frame corpus on 2026-09-10: 41 frames are front-of-pack
shots with no statutory block anywhere in them, and of the 80 that do show a
back panel, 31 name none of Rule 6(1)'s six — ten of those while reading eight
or more confident lines of nutrition table and marketing copy, one of them 62
lines. Every one of those frames passes B1, because every one of them is a good
photograph. It is a good photograph of the wrong thing.
"""

FRAMING_ADVICE: dict[FramingFault, str] = {
    "no_declaration_panel": (
        "No declaration panel in this photograph. Turn the pack to the side "
        "printed with MRP and net weight, and photograph that side."
    ),
    "wrong_panel": (
        "Text was read, but none of it is a required declaration — this is "
        "usually the nutrition table or the back-of-pack copy. Move to the "
        "block printed with MRP, net weight and the manufacturer's address."
    ),
}
"""Two faults because they need two different sentences.

"Turn the pack over" is wrong advice for an officer already looking at the back
of the pack, and it is the advice that sends them back for a second photograph
that fails the same way — the failure mode `ADVICE` above was written to avoid.
"""


class Framing(BaseModel):
    """Did this frame contain anything the rules could be applied to?

    **A measurement, never a verdict, and never a suppressor.** It changes no
    status, hides no evidence and is not read anywhere in `rules/`. Withdrawing
    the inference from silence is already handled — and handled better, against
    the live rulepack — by `rules.checks._common.reading_supports_an_absence`.
    This exists for the one thing that guard cannot do: tell the officer holding
    the phone *why* the screen came back thin, and what to point the camera at.

    Nothing here fires when a declaration *was* found. A frame naming two of
    the six may be a clipped panel or may be a genuinely under-declared package,
    and no signal available to us separates those. Reporting the first as a
    framing fault would give every under-declared pack an excuse, so the fault
    is emitted only when the count is zero.
    """

    model_config = ConfigDict(frozen=True)

    shows_declarations: bool
    """True when at least one required declaration was located."""

    mandatory_found: int = Field(ge=0)
    mandatory_expected: int = Field(ge=0)

    text_regions: int = Field(ge=0)
    """How many lines the recogniser returned. Only used to choose between the
    two faults; see `vision/quality/framing.py` for the measured split."""

    fault: FramingFault | None = None
    reason: str | None = None
    """One sentence, for the officer. None when `shows_declarations`."""

    def advice(self) -> tuple[str, ...]:
        return (FRAMING_ADVICE[self.fault],) if self.fault else ()


__all__ = [
    "ADVICE",
    "FRAMING_ADVICE",
    "CaptureQuality",
    "Framing",
    "FramingFault",
    "QualityFault",
]
