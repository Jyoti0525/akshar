"""Request and response bodies. AKSHAR.md section 12.

**These are not `contracts/`.** `contracts/` is the frozen vocabulary shared by
extraction, decision and the web app; this module is the *wire format* of one
HTTP API, and the two change for different reasons. A pagination cursor belongs
here and nowhere near a `DeclarationSet`; conversely `Declaration` is reused
verbatim rather than restated, because a second definition of a declaration is
exactly how a field silently stops meaning the same thing on both sides.

The frontend's TypeScript is generated from the OpenAPI schema these produce
(`openapi-typescript`, section 15b), so anything added here reaches the web app
without anyone hand-copying a type.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from contracts import (
    CaptureQuality,
    DeclarationSet,
    DegradationTier,
    Framing,
    SourceChannel,
    Verdict,
)

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Access token lifetime, seconds.")
    role: Literal["officer", "supervisor", "admin"]


class RefreshRequest(BaseModel):
    refresh_token: str


class CurrentUser(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: Literal["officer", "supervisor", "admin"]
    district: str | None = None


# ---------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------


class GeoPoint(BaseModel):
    """Truncated before storage — section 18, and `Settings.geo_precision_dp`.

    Accepted at full precision because a browser reports what it reports;
    reduced on the way in, so the coarse value is the only one ever written.
    """

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class ListingScanRequest(BaseModel):
    """The third input channel. No pixels at all.

    Section 3: "the PS names three inputs and one is pure text from an
    e-commerce listing. If OCR is wired straight into the rules, that third
    channel becomes a rewrite instead of an afternoon's work."
    """

    text: str = Field(min_length=1, max_length=20_000)
    category: str | None = None
    district: str | None = None


class ScanResponse(BaseModel):
    """What an officer sees, and in the order the scan screen renders it.

    `latency_ms`, `degradation_tier` and `coverage` are not diagnostics here —
    section 11 requires all three on screen for every scan. "An officer must
    know how much the system understood before trusting a verdict."
    """

    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    exit_path: Literal["unusable", "cache_hit", "no_package", "full", "listing_text"]
    source: SourceChannel
    degradation_tier: DegradationTier
    coverage: float
    latency_ms: int
    cache_hit: bool
    declarations: DeclarationSet | None = None
    verdicts: list[Verdict] = Field(default_factory=list)
    message: str = ""
    model_versions: dict[str, str] = Field(default_factory=dict)
    rulepack_version: str = ""
    record_sha256: str | None = None
    chain_seq: int | None = None
    report_status: Literal["queued", "ready", "not_requested"] = "queued"
    """Section 8c: a PDF takes 300-800 ms and must not sit in front of an
    officer standing in a shop. The verdict renders; the link appears later."""

    evidence: EvidenceInfo | None = None
    """Absent on the listing_text channel, which has no pixels to store."""

    capture_quality: CaptureQuality | None = None
    """B1's measurement of the photograph itself, and what to do about it.

    **In the response but not in the scan row.** It is a fact about our
    photograph, not about the package — nothing in the report cites it and no
    rule reads it — and section 6 hashes every column of the row into the
    evidence chain, so adding one there is a schema migration and a chain-format
    change for a number the officer needs for the next four seconds and never
    again.

    What is preserved is the consequence: a rejected frame becomes an L4 record
    with the photograph, its time and its place, exactly as section 5 requires.

    Absent on the listing_text channel, which has no pixels to measure."""

    framing: Framing | None = None
    """Whether the declaration panel was in the photograph at all.

    The other half of the same question, and the half the corpus says decides
    most scans: 41 of 122 frames are sharp, well-lit photographs of the brand
    face. `capture_quality` passes every one of them, because as photographs
    they are fine.

    Kept out of the scan row for the same reason as `capture_quality`, and for
    one more: it is emphatically **not** a finding about the package. It says we
    were looking at the wrong side, and a fact about our own aim has no business
    in an evidence chain that an officer may one day have to defend."""

    frames: list[FrameInfo] = Field(default_factory=list)
    """One entry per photograph, when the officer took more than one.

    Empty for a single-frame scan: `capture_quality`, `framing` and `evidence`
    already describe that one photograph completely, and a one-element list
    beside them would only invite a second way of reading the same fact.

    The frames that contributed nothing are in here too. "Your second shot was
    too blurred to measure" is the sentence that gets a usable photograph taken,
    and it cannot be said by a screen that only lists what worked."""


class FrameInfo(BaseModel):
    """One photograph of the pack, and what it contributed.

    Deliberately thin. Everything an officer needs while standing in the shop —
    was this shot usable, did it show a declaration panel, is it stored — and
    nothing about geometry or scale, which belong to the union rather than to
    any one frame.
    """

    model_config = ConfigDict(populate_by_name=True)

    frame: int
    exit_path: str
    read: bool
    """Did this photograph put declarations into the union that was judged?"""

    message: str = ""
    capture_quality: CaptureQuality | None = None
    framing: Framing | None = None
    image_key: str | None = None
    image_sha256: str | None = None
    """The digest of the exact stored bytes.

    Unlike `capture_quality`, this **is** in the scan row and therefore inside
    the hash chain — section 6 requires it, because this frame is evidence. See
    `db/schema.sql`, `scans.frames`."""

    stored: bool = False


class EvidenceInfo(BaseModel):
    """What happened to the photograph. Sections 6 and 18.

    On screen this is one line — "photograph stored" or "no photograph: repeat
    SKU". It is in the response rather than left to a log because three quite
    different things all end with no object in the bucket, and an officer who
    later has to explain a finding needs to know which one applied at the time
    rather than reconstructing it from a retention policy.
    """

    stored: bool
    reason: str
    key: str | None = None
    sha256: str | None = None
    tier: str | None = None
    deferred: bool = False
    """True when the bytes went to a worker rather than to MinIO inline —
    section 8c's "evidence upload comes off the critical path". The record is
    complete either way; the object lands a moment later."""

    faces_blurred: int = 0
    faces_on_package: int = 0
    """Faces printed on the packaging, left intact deliberately. Blurring the
    Amul girl off a carton would remove label content, which is the evidence."""


class BulkAccepted(BaseModel):
    """202 for a bulk upload. Section 8c: nobody is waiting on this."""

    job_id: UUID
    accepted: int
    rejected: list[str] = Field(default_factory=list)
    """Files refused before queueing — too large, or empty. Named, not counted:
    "3 files rejected" sends somebody hunting through a folder of 300."""

    poll: str


class BulkJobStatus(BaseModel):
    job_id: UUID
    status: Literal["running", "complete", "failed"]
    total: int
    completed: int
    failed: int
    pending: int
    scan_ids: list[UUID] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    created_at: datetime
    finished_at: datetime | None = None


class SyncItem(BaseModel):
    """One queued scan from an offline outbox."""

    id: UUID = Field(description="Client-generated UUIDv7 — time-ordered, replay-safe.")
    source: SourceChannel
    degradation_tier: DegradationTier
    declaration_set: dict[str, Any]
    coverage: float | None = None
    latency_ms: int | None = None
    cache_hit: bool = False
    image_key: str | None = None
    image_sha256: str | None = None
    geo: GeoPoint | None = None
    captured_at: datetime
    model_versions: dict[str, str] = Field(default_factory=dict)
    rulepack_version: str
    district: str | None = None


class SyncRequest(BaseModel):
    scans: list[SyncItem] = Field(max_length=500)


class SyncResult(BaseModel):
    id: UUID
    created: bool
    """False means "already had it" — the healthy outcome of a retry, not an
    error. Section 5: replaying the outbox never duplicates a record."""

    chain_seq: int
    record_sha256: str


class SyncResponse(BaseModel):
    accepted: int
    created: int
    duplicates: int
    results: list[SyncResult]


class CorrectionRequest(BaseModel):
    """An officer override. Append-only; never an edit.

    Section 5: "Corrections are append-only rows, never edits. Nothing is ever
    updated in place, so nothing can conflict." Section 14: every one of these
    is also a labelled training example, produced by someone already doing the
    job.
    """

    box_index: int | None = None
    from_field: str | None = None
    to_field: str


class ReviewResolutionRequest(BaseModel):
    """A human's decision on a verdict the rulepack declined to decide.

    Section 8b: *"every REVIEW verdict lands there, one-click resolve,
    resolution stored as a labelled example for retraining."*

    `rule_id` is required and there is no "resolve the whole scan" shortcut. A
    scan reaches the queue because one or more specific rules came back REVIEW,
    and each is a separate question — a marginal MRP height and an unreadable
    net quantity are not settled by one click, and pretending otherwise would
    file a decision nobody made against the second one.
    """

    rule_id: str = Field(min_length=1, max_length=120)
    decision: Literal["complies", "does_not_comply", "recapture"]
    note: str = Field(default="", max_length=2000)


class ReviewResolutionResponse(BaseModel):
    scan_id: UUID
    rule_id: str
    decision: str
    officer_id: UUID
    resolved_at: datetime
    outstanding: list[str]
    """Rules on this scan still awaiting a human. Empty means the scan leaves
    the queue on the next dashboard load, which is the one thing the officer
    wants to know and the one thing a bare 201 would not tell them."""


# ---------------------------------------------------------------------------
# SKU repository
# ---------------------------------------------------------------------------


class SkuSummary(BaseModel):
    id: UUID
    brand: str
    brand_group: str | None = None
    variant: str | None = None
    pack_size: str
    category: str
    barcode: str | None = None
    phash: str | None = None
    scan_count: int = 0
    label_w_mm: float | None = None
    label_h_mm: float | None = None


class SkuLookupResponse(BaseModel):
    hit: bool
    matched_on: Literal["barcode", "phash", "none"] = "none"
    sku: SkuSummary | None = None


class SkuCacheResponse(BaseModel):
    district: str | None
    count: int
    skus: list[SkuSummary]


# ---------------------------------------------------------------------------
# Ops
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    rulepack_version: str
    rules_loaded: int
    models_present: int
    models_expected: int
    storage: Literal["memory", "sql"] = "memory"
    """Which store family this process resolved to. Reported because the
    in-memory fallback is legitimate (a clean clone, the offline demo) and
    indistinguishable from a working deployment until the process restarts."""

    detail: list[str] = Field(default_factory=list)


class ChainStatusResponse(BaseModel):
    """Section 6 and section 18 — exposed so tamper-evidence is checkable.

    A chain nobody ever verifies is a column, not a control.
    """

    checked: int
    ok: bool
    head_sha256: str | None
    failures: list[str] = Field(default_factory=list)


__all__ = [
    "BulkAccepted",
    "BulkJobStatus",
    "ChainStatusResponse",
    "CorrectionRequest",
    "CurrentUser",
    "EvidenceInfo",
    "FrameInfo",
    "GeoPoint",
    "HealthResponse",
    "ListingScanRequest",
    "LoginRequest",
    "RefreshRequest",
    "ScanResponse",
    "SkuCacheResponse",
    "SkuLookupResponse",
    "SkuSummary",
    "SyncItem",
    "SyncRequest",
    "SyncResponse",
    "SyncResult",
    "TokenPair",
]
