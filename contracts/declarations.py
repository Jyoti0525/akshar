"""Frozen data contracts — AKSHAR.md section 9.

These models are the ONLY vocabulary shared between extraction (`vision/`) and
decision (`rules/`). The plan freezes them on day 4 so six people can work in
parallel without blocking each other.

Three details in here are load-bearing and must not be "tidied away":

1.  ``Declaration.height_mm`` is Optional and ``DeclarationSet.source`` includes
    ``listing_text``. A text listing from an e-commerce site has no pixels at
    all, and the same rules engine must handle it by skipping the geometric
    checks and running everything else.

2.  ``Verdict.status`` includes ``REVIEW``. At 1.9 mm +/- 0.2 against a 2.0 mm
    threshold we do not assert a violation, we flag it for the officer.
    Convicting on a 0.1 mm margin would be dismantled in court.

3.  ``script`` travels with every declaration, so bilingual grouping works
    (Rule 9(4): either script may satisfy a height requirement) and reports can
    show which script was actually read.

This module MUST NOT import cv2, PaddleOCR, or the database.
`tests/test_boundaries.py` enforces that.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

FieldName = Literal[
    "mrp",
    "net_quantity",
    "mfg_date",
    "expiry_date",
    "manufacturer",
    "packer",
    "importer",
    "consumer_care",
    "country_of_origin",
    "generic_name",
    "batch",
    "marketing_text",
    # -- present on the panel, but not a declaration Rule 6(1) asks for -------
    "nutrition",
    "ingredients",
    "storage_use",
    "fssai_licence",
    "barcode",
    "unit_sale_price",
    "other",
]
"""Every field the extractor may emit.

`marketing_text` exists so a promotional price graphic ("Rs. 20 OFF") has an
honest home and is never mislabelled `mrp` (section 16, annotation rules).
`other` is what an annotator or model uses when a human cannot read the text —
never a guess.

---------------------------------------------------------------------------
THE SIX NON-STATUTORY NAMES, AND WHY THEY ARE HERE
---------------------------------------------------------------------------
`nutrition`, `ingredients`, `storage_use`, `fssai_licence`, `barcode` and
`unit_sale_price` are **not** declarations under the Packaged Commodities Rules
and **no rule targets them**. A rule reaches its subject through the rulepack's
own `field:`/`fields:` keys, so adding a name here cannot change a verdict; it
changes only what the annotated photograph calls a box.

That is worth doing on its own. Measured on `rocksalt.jpg`, 37 boxes were
labelled `other` and 17 of them are the nutrition table, the storage note and
the FSSAI licence — things with perfectly good names. An officer reading a panel
of `other` cannot tell "we saw this and it is not a declaration" from "we could
not read this", and those are opposite statements. The reference annotation the
project was given labels all six.

**What must not happen is the reverse.** `nutrition` carries numbers with units
and `unit_sale_price` carries a price; if either were ever admitted as the net
quantity or the retail sale price, a compliant pack would be judged on the wrong
figure. They are separated here for exactly that reason, and
`tests/unit/test_false_accusations.py` pins it.
"""

NON_STATUTORY_FIELDS: frozenset[str] = frozenset(
    {
        "nutrition",
        "ingredients",
        "storage_use",
        "fssai_licence",
        "barcode",
        "unit_sale_price",
        "marketing_text",
        "other",
    }
)
"""Names the extractor may emit that no rule under these Rules asks for.

One definition, because two would drift. Anything scoring extraction against a
declaration ground truth must subtract this set first, or naming the nutrition
table counts as inventing a declaration: `bench/declaration_blocks.py` scored
precision 0.98 before these names existed and 0.75 the moment they did, on
identical extraction, purely because the labels record statutory declarations
and nothing else.

`marketing_text` and `other` were always in this category and were subtracted by
hand at each call site. They are here now so the next name added has one obvious
place to go.
"""

Script = Literal["latin", "devanagari", "other"]

ScaleTier = Literal["A", "B", "C"]
"""How ``mm_per_px`` was recovered (section 17, M2).

A — a printed marker of known size in frame (ArUco/ChArUco on the inspection card).
B — known physical label dimensions for a SKU already in the repository.
C — no scale at all. The two ``scale_free`` rules still run; only the three
    absolute-height rules go dark.
"""

DegradationTier = Literal["L0", "L1", "L2", "L3", "L4"]
"""Which tier produced this answer (section 5). The system must never simply
fail; it degrades and always reports how far it degraded."""

SourceChannel = Literal["photo", "bulk_image", "listing_text"]
"""The three inputs named by the problem statement. Most teams read only
"images"; the third one is why extraction and decision are separated."""

VerdictStatus = Literal["PASS", "FAIL", "NOT_APPLICABLE", "REVIEW", "NO_DATA"]
"""``NO_DATA`` is returned when a rule's ``requires`` inputs are absent.

Absence of evidence is not evidence of a violation. A rule that cannot be
evaluated must never return FAIL.
"""

Severity = Literal["high", "medium", "low"]

PanelId = Literal["pdp", "side", "back", "top", "bottom", "unknown"]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


class Box(BaseModel):
    """An axis-aligned box in *rectified label space*, in pixels.

    Rectified means the perspective transform of M1 has already been applied,
    so `h` is proportional to true printed height and can be converted to
    millimetres by a single scalar. Boxes in raw camera space are useless for
    measurement and must not be put here.
    """

    model_config = ConfigDict(frozen=True)

    x: float
    y: float
    w: float
    h: float
    panel_id: PanelId | None = None

    @field_validator("w", "h")
    @classmethod
    def _positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("box width and height must be positive")
        return v

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0

    @property
    def area(self) -> float:
        return self.w * self.h

    def intersects(self, other: Box) -> bool:
        return not (
            self.x2 <= other.x or other.x2 <= self.x or self.y2 <= other.y or other.y2 <= self.y
        )

    def iou(self, other: Box) -> float:
        """Intersection over union. Used by the duplicate-declaration checks."""
        if not self.intersects(other):
            return 0.0
        ix = min(self.x2, other.x2) - max(self.x, other.x)
        iy = min(self.y2, other.y2) - max(self.y, other.y)
        inter = ix * iy
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0


class LabelGeometry(BaseModel):
    """Everything the geometric rules need to know about the label as a whole."""

    model_config = ConfigDict(frozen=True)

    label_area_cm2: float | None = None
    """Principal display panel area, for Rule 7(2) Table II. Only used when
    quantity is declared by length, area or number."""

    pdp_polygon: list[tuple[float, float]] | None = None
    """The principal display panel outline in rectified space, for Rule 8(1)."""

    mm_per_px: float | None = None
    """None at scale tier C. Every ``min_height_mm`` rule returns NO_DATA."""

    mm_per_px_tolerance: float | None = None
    """Half-width of the scale confidence interval, propagated into
    ``Declaration.height_mm_tolerance`` so the REVIEW band is honest."""

    rectified: bool = False

    scale_tier: ScaleTier | None = None

    frame_id: int = Field(default=0, ge=0)
    """Which photograph this geometry describes.

    ``pdp_polygon`` is a list of coordinates and ``mm_per_px`` is a scalar for
    one image; neither survives being applied to a different photograph. On a
    union this names the frame they came from, so a check that needs them can
    tell whether the declaration in front of it is one they apply to.
    """

    @field_validator("mm_per_px")
    @classmethod
    def _scale_positive(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("mm_per_px must be positive when present")
        return v


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------


class Declaration(BaseModel):
    """One extracted declaration: what it says, where it sits, how tall it is."""

    model_config = ConfigDict(frozen=True)

    field: FieldName
    text: str
    script: Script
    box: Box

    height_px: float
    """Cap height in rectified pixels — top of a capital letter to the
    baseline, excluding descenders (section 16, annotation rules). For the two
    numeral-height rules this is the height of the NUMERALS, not of the whole
    declaration including "(inclusive of all taxes)"."""

    height_mm: float | None = None
    """None at scale tier C."""

    height_mm_tolerance: float | None = None
    """Measurement uncertainty. A result within tolerance of a threshold is
    REVIEW, not FAIL."""

    scale_tier: ScaleTier | None = None

    ocr_confidence: float = Field(ge=0.0, le=1.0)
    field_confidence: float = Field(ge=0.0, le=1.0)

    contrast_ratio: float | None = None
    """WCAG-style ratio of the glyph luminance against local background, for
    Rule 9(1)(b) and Rule 18(5)."""

    # -- additive, non-breaking: needed by checks the plan specifies ---------

    char_boxes: list[Box] = Field(default_factory=list)
    """Per-character boxes, used by ``min_width_ratio`` (Rule 7(3) proviso).
    Empty when the OCR engine did not return character-level geometry, in
    which case that check returns NO_DATA rather than guessing."""

    numeral_box: Box | None = None
    """Sub-box covering just the numerals. Used by ``clear_space`` (Rule 8(1)
    proviso), which needs to know *where* the figures are. Its height is
    deliberately not used as a measurement -- ``numeral_height_px`` is."""

    numeral_height_px: float | None = None
    """Height of the numerals alone, in rectified pixels, when it was measured.

    Rule 7(2) Table I prescribes the height of the *numerals* of the net
    quantity, and Rule 9's price declaration attaches to the figure. On a pack
    reading ``Net Wt. 500 g`` the words and the digits are routinely set at
    different sizes, so the declaration's own cap height answers the wrong
    question.

    ``None`` means the figures were not separable, and the height rules then
    return NO_DATA. That is the honest answer and it costs three rules out of
    thirty-one; a fabricated height costs someone a false violation."""

    frame_id: int = Field(default=0, ge=0)
    """Which photograph this declaration was read from.

    0 on every single-frame scan, which is every scan this project made until
    multi-frame capture existed, and the reason the default is 0 rather than
    None: nothing written before this field has to know about it.

    It is here because **a box is only comparable to another box from the same
    photograph.** ``Box`` says it lives in rectified label space; what it could
    not say until now is that each photograph has its *own* rectified label
    space. Two declarations read from two photographs of one pack may have boxes
    that overlap, abut, or enclose one another, and none of it means anything --
    the second photograph's origin is simply somewhere else.

    Three checks compare one box against another and all three consult this
    before comparing: ``clear_space`` (an intruder from another photograph is
    not printed beside anything), ``same_panel`` (grouping cannot be judged
    across photographs of different sides) and ``no_duplicate_field`` (two
    readings of one printed price are not two printed prices). ``clear_space``
    already did exactly this one level down, with ``panel_id``.
    """

    is_embossed: bool = False
    """Selects the ``embossed_mm`` column of Rule 7(2) Table I. Blown, moulded
    or embossed containers get double the height allowance."""

    text_rotation_k: int = 0
    """Quarter-turns anticlockwise between the pack and this text's reading
    direction. 0 for ordinary horizontal print; 1 or 3 for the net quantity or
    batch code set down the *side* of a pack, which is where they very often
    sit -- 37% of the regions our detector proposes are taller than wide.

    It is here because it changes which side of a box is a glyph's height, and
    two checks divide by that. A vertical `5` arrives 18 px wide and 6 px tall
    in pack coordinates, so Rule 7(3)'s width-over-height ratio reads 3.0
    instead of 0.33 and passes a character that should have failed. Silently
    passing a violation is the worst direction for this error to run in.

    This is a measurement, not a decision: vision reports which way the text
    ran, and the rulepack decides what follows. See ``glyph_size``."""

    def glyph_size(self, box: Box) -> tuple[float, float]:
        """`(width, height)` of `box` in this text's own reading direction.

        The swap is duplicated from ``vision.measure.orientation.glyph_axis``
        rather than imported, because ``rules/`` and ``contracts/`` never import
        ``vision/`` -- the whole point of the engine being able to judge an
        e-commerce listing is that it has no vision code behind it.

        Note this is not ``min``/``max``: an upright digit is legitimately
        taller than it is wide, and inferring the axis from the shape would
        measure its width instead.
        """
        if self.text_rotation_k % 4 in (1, 3):
            return box.h, box.w
        return box.w, box.h

    @property
    def height_for_rules_px(self) -> float:
        """Numeral height when we have it, else the declaration cap height.

        This reads ``numeral_height_px`` and not ``numeral_box``. The box is a
        position; its height was measured by column segmentation and on real
        crops it routinely returns the height of the crop rather than of the
        figures, which inflates the measurement two- to threefold in the
        direction that turns a non-compliant pack compliant.
        """
        if self.numeral_height_px is None:
            return self.height_px
        return self.numeral_height_px


class DeclarationSet(BaseModel):
    """The complete output of extraction, and the ONLY input to the rules engine.

    The engine receives this and nothing else — no image, no file handle, no
    database session. That wall is what lets the identical engine judge an
    e-commerce listing that never had pixels.
    """

    source: SourceChannel
    declarations: list[Declaration] = Field(default_factory=list)
    geometry: LabelGeometry = Field(default_factory=LabelGeometry)

    coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    """Fraction of detected text regions that were successfully read. Shown on
    the scan screen so an officer knows how much the system understood before
    trusting a verdict."""

    degradation_tier: DegradationTier = "L0"
    captured_at: datetime
    model_versions: dict[str, str] = Field(default_factory=dict)
    """Detector hash, OCR version, classifier version, execution provider.
    A finding you cannot reproduce is a finding you cannot defend."""

    # -- additive: see docs/spec-deltas.md ----------------------------------
    raw_text: str | None = None
    """Full concatenated text, used by the listing_text channel and by
    ``regex_absent`` checks that must scan beyond a single declaration."""

    frame_count: int = Field(default=1, ge=1)
    """How many photographs were unioned to produce this set.

    1 for every single-frame scan and for the listing_text channel. Greater than
    1 when an officer walked round the pack: several photographs, evidence
    unioned, **the rules evaluated once on the union.** Evaluating each frame
    separately and then combining the verdicts was the obvious alternative and
    it is unsound in one direction -- taking the best status per rule quietly
    acquits a pack whose second photograph shows the violation, and an
    enforcement tool must not have a bias that runs that way.
    """

    def by_field(self, field: FieldName) -> list[Declaration]:
        return [d for d in self.declarations if d.field == field]

    def by_frame(self, frame_id: int) -> list[Declaration]:
        """Everything read from one photograph. See ``Declaration.frame_id``."""
        return [d for d in self.declarations if d.frame_id == frame_id]

    def is_union(self) -> bool:
        return self.frame_count > 1

    def has_scale(self) -> bool:
        """Was a millimetre recovered anywhere in this set?

        ``geometry.mm_per_px`` describes ONE photograph -- on a union, the one
        named by ``geometry.frame_id``. A pack photographed three times may have
        had its marker card in shot for only the third, and the declarations
        read from that third photograph carry a real ``height_mm`` even though
        the set-level scalar belongs to a frame that had none.

        **The rescue clause applies only to a union**, and deliberately so. On a
        single frame ``geometry.mm_per_px`` is the whole answer: if that frame
        recovered no scale then nothing it read has a height in millimetres, and
        reaching past it to the declarations would only ever find a value some
        caller set by hand. Nothing that existed before multi-frame capture can
        take a different path through this than it did.
        """
        if self.geometry.mm_per_px is not None:
            return True
        if not self.is_union():
            return False
        return any(d.height_mm is not None for d in self.declarations)

    def first(self, field: FieldName) -> Declaration | None:
        found = self.by_field(field)
        return found[0] if found else None

    def has_pixels(self) -> bool:
        """False for the listing_text channel: every geometric rule NO_DATAs."""
        return self.source != "listing_text"


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


class Verdict(BaseModel):
    """One rule, one decision, one gazette citation.

    Every verdict carries ``rule_ref`` — that citation is also the retrieval
    key for the rule explainer (section 15 tier 1). We never search for
    Rule 7(2); we know it is Rule 7(2).
    """

    model_config = ConfigDict(frozen=True)

    rule_id: str
    """e.g. "LMPC.MRP.NUMERAL_HEIGHT"."""

    rule_ref: str
    """e.g. "Rule 7(2), Table I" — the gazette clause, verbatim."""

    status: VerdictStatus
    severity: Severity
    field: FieldName | None = None
    found: str | None = None
    expected: str
    message: str

    # -- additive: provenance for the report and the dashboard --------------
    measured: float | None = None
    threshold: float | None = None
    tolerance: float | None = None

    unit: Literal["mm", "ratio", "count", "cm2"] = "mm"
    """What ``measured`` and ``threshold`` are counted in.

    Most rules measure millimetres, which is why that is the default and why
    nothing before this carried the field. Two of them never did, and the report
    said millimetres anyway: Rule 7(3)'s proviso is a **ratio** of width to
    height, and Rule 8(1)'s proviso yields a **count** of intrusions. A user
    photographing a compliant cheese carton was shown

        Clear space around net quantity    13.00 mm   required 0.00 mm

    which is not a quantity anybody can check, and "required 0.00 mm" reads as a
    broken tool rather than as a finding. The number was right; the unit was
    invented by the renderer, which appended ``mm`` to every verdict it was
    given.

    It is a `Literal` rather than a free string so a new check cannot quietly
    introduce a fourth unit that no formatter knows how to print."""
    respondent: Literal["manufacturer", "packer", "importer", "dealer"] = "manufacturer"
    """Rule 18(5) is the RETAILER's offence, not the manufacturer's. The notice
    is addressed to a different person, so the report must say so."""

    advisory: bool = False
    """The five unit-symbol checks are formatting defects. They render in a
    separate advisory block so a `250 ML` never sits beside a missing MRP."""

    suppressed_by: str | None = None
    """Set when another rule measured the same thing and won (``suppresses:``).
    One measurement yields one verdict."""


__all__ = [
    "Box",
    "Declaration",
    "DeclarationSet",
    "DegradationTier",
    "FieldName",
    "LabelGeometry",
    "PanelId",
    "ScaleTier",
    "Script",
    "Severity",
    "SourceChannel",
    "Verdict",
    "VerdictStatus",
]
