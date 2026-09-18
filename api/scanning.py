"""The image scan, from bytes to a stored record. AKSHAR.md sections 4, 6, 8c, 18.

**This module exists so that there is exactly one of it.** Section 12 is blunt
about the bulk path: *"Bulk runs the identical B1-B10 sequence server-side. If it
diverges, two products exist and only one is tested."* The interactive route and
the bulk worker both call `run_scan`, so the divergence is not merely
discouraged — there is no second implementation to diverge into.

**Nothing here decides compliance.** It orchestrates: decode, extract, hand a
`DeclarationSet` to `rules.engine.evaluate`, store what came back. The wall from
section 3 runs straight through the middle of this file and the verdicts arrive
from the far side of it.

**The order of operations is the interesting part**, because section 8c requires
the verdict to come back before the evidence is uploaded, and section 6 requires
the scan row to carry the evidence digest — which is stored inside a hash chain
that forbids editing the row afterwards. Those two pull in opposite directions,
and the resolution is that *redaction and hashing are synchronous while the
network transfer is not*:

    decode -> extract -> evaluate -> redact -> encode -> hash + key
        -> write the row (chain closed, digest inside it)
        -> spool the bytes, enqueue the upload, return the verdict
                                       ... worker PUTs to MinIO afterwards

Blurring a face costs about 20 ms and gives us bytes we can hash. Uploading them
costs a network round trip we do not owe the officer. Only the second is
deferred, and the record is complete either way.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID, uuid4

from api.config import Settings
from api.repository import ScanStore, SkuRecord, SkuStore, SyncOutcome
from contracts import (
    CaptureQuality,
    DeclarationSet,
    Framing,
    PackageContext,
    SourceChannel,
    Verdict,
)
from evidence import redact, storage
from rules.engine import evaluate
from rules.loader import load_rulepack
from vision.scale import operator as operator_scale

if TYPE_CHECKING:  # pragma: no cover - `vision/` is imported lazily, inside
    from vision.scale import tier_b  # the functions that use it

MAX_UPLOAD_BYTES = 16 * 1024 * 1024
"""Refuse anything larger, before decoding it. Sixteen megabytes is generous for
a phone JPEG and far below what it takes to make OpenCV allocate dangerously —
the check exists because `imdecode` on a hostile file is the one place in this
path where a request can cost more than it should."""


class Enqueuer(Protocol):
    """How this module reaches the queue. A callable, not a Dramatiq import.

    Same reasoning as every other boundary here: `run_scan` is fully testable
    with a list that records what would have been enqueued, and the API can run
    with no broker at all — in which case the caller passes `None` and the
    evidence upload happens inline. A tool that stops recording inspections
    because Redis is down is not an enforcement tool.
    """

    def __call__(self, task: str, *, queue: str, **kwargs: Any) -> None: ...


CHAIN_SAFE_DP = 6
"""Decimal places kept on any float that enters the scan row.

**This is an evidence-chain constraint, not a formatting preference.**
`scans.coverage` is a Postgres NUMERIC. A Python float carrying 17 significant
digits does not survive the round trip through it — 0.9722222222222222 is read
back as 0.972222222222222 — and `evidence.chain` re-hashes the row it reads
back. The digests then differ and `verify_chain` reports CONTENT_ALTERED on a
record nobody edited, which is the one alarm in this system that must never cry
wolf: an auditor who has seen it fire spuriously will not believe it when it is
real.

Latent since the column existed, and found on 2026-09-10 the first time a
multi-frame scan was written to Postgres — a coverage that is the MEAN over
several frames needs the full seventeen digits almost every time, where a single
frame's ratio often does not. Six decimal places is four more than anything
displays and round-trips exactly.
"""


MAX_FRAMES = 5
"""How many photographs of one pack a single scan may carry.

Not a performance limit — five frames is under three seconds — but a semantic
one. A scan is an inspection of one package, and a request carrying twelve
photographs is either a mistake or a bulk import wearing the wrong endpoint.
Three is what walking round a carton takes; five leaves room for a retake.
"""


@dataclass(frozen=True, slots=True)
class ScanRequest:
    """One package and the facts about it that no image contains.

    `category` and the geolocation come from the officer or the bulk manifest,
    never from pixels. Section 3: guessing the package context from the image
    would put a compliance decision inside the extractor.
    """

    payload: bytes
    officer_id: UUID
    scan_id: UUID = field(default_factory=uuid4)
    source: SourceChannel = "photo"
    district: str | None = None
    category: str | None = None
    geo: dict[str, float] | None = None
    captured_at: datetime | None = None
    context: PackageContext | None = None

    pack_height_mm: float | None = None
    """Height of the photographed face, measured with a ruler by the officer.

    **Required on the `photo` channel**, and that is a deliberate refusal to
    degrade quietly. Without a scale the three `min_height_mm` rules return
    NO_DATA — the honest answer, but one that reads on a report as though the
    check was performed. Asking for one number at capture time is a smaller
    cost than an inspection that silently examined 28 rules out of 31.

    It cannot be required on the other two channels and is not: a bulk image is
    a studio render from an e-commerce listing and `listing_text` has no pack at
    all, so there is nothing for anybody to hold a ruler against. Those keep the
    marker/repository/no-scale ladder they already had.
    """

    extra_frames: tuple[bytes, ...] = ()
    """The second and later photographs of the SAME package.

    Empty for every scan that existed before multi-frame capture, which is why
    `payload` stays exactly where it was rather than becoming a list: a caller
    that knows nothing about frames constructs the request it always did.

    These are photographs of *one pack from several angles*, not of several
    packs. They produce one scan row, one hash-chain entry, one evidence union
    and one set of verdicts. Several packs is `/scans/bulk`.
    """

    @property
    def frames(self) -> tuple[bytes, ...]:
        return (self.payload, *self.extra_frames)


@dataclass(frozen=True, slots=True)
class EvidenceDecision:
    """What happened to the photograph, in words a report can print.

    Reported rather than inferred because three quite different things all end
    with no object in the bucket — a repeat SKU that needed no second copy, a
    privacy stop, and a queue that took the bytes but has not written them yet —
    and an auditor asking "where is the photograph" deserves the actual answer.
    """

    stored: bool
    reason: str
    key: str | None = None
    sha256: str | None = None
    tier: storage.Tier | None = None
    deferred: bool = False
    redaction: str = ""
    faces_blurred: int = 0
    faces_on_package: int = 0

    annotation_key: str | None = None
    """Where the annotated label was written, or None if there is not one.

    A separate key from `key` because it is a separate object in a separate
    bucket under a separate retention rule: the photograph is evidence for seven
    years, the drawing over it is derived and keeps for two.
    """

    annotation_reason: str = ""


@dataclass(frozen=True, slots=True)
class FrameOutcome:
    """What one photograph of the pack contributed, and where it was stored.

    Every frame gets one of these, including the ones that failed: a scan of
    three photographs where the second was rejected is a different record from a
    scan of two, and an auditor six months later is entitled to see the frame
    that was thrown away as well as the ones that were kept.
    """

    frame: int
    exit_path: str
    read: bool
    """Did this photograph produce declarations that went into the union?"""

    message: str
    quality: CaptureQuality | None = None
    framing: Framing | None = None
    image_key: str | None = None
    image_sha256: str | None = None
    stored: bool = False
    reason: str = ""

    def as_row(self) -> dict[str, Any]:
        """The form that goes into the scan row, and therefore into the chain.

        `image_sha256` is the reason this is in the row at all. Section 6 puts
        the photograph's digest inside the hash chain so that later alteration
        is detectable; a multi-frame scan has several photographs and every one
        of them is evidence, so every one of their digests has to be in there.
        """
        return {
            "frame": self.frame,
            "exit_path": self.exit_path,
            "read": self.read,
            "image_key": self.image_key,
            "image_sha256": self.image_sha256,
            "stored": self.stored,
        }


@dataclass(frozen=True, slots=True)
class ScanResult:
    scan_id: UUID
    exit_path: str
    source: SourceChannel
    degradation_tier: str
    coverage: float
    latency_ms: int
    cache_hit: bool
    declarations: DeclarationSet | None
    verdicts: list[Verdict]
    message: str
    model_versions: dict[str, str]
    rulepack_version: str
    stored: SyncOutcome
    evidence: EvidenceDecision
    sku: SkuRecord | None = None
    capture_quality: CaptureQuality | None = None
    """B1's measurement of the frame. None on the listing_text channel."""

    framing: Framing | None = None
    """Whether the declaration panel was in shot. None on every path that
    never assembled declarations — the cache hit, the early exits, and the
    listing_text channel, which has no aim to get wrong."""

    frames: tuple[FrameOutcome, ...] = ()
    """One entry per photograph, in the order they were taken.

    Empty on a single-frame scan, where `capture_quality`, `framing` and
    `evidence` already say everything there is to say about the one photograph.
    Populated when the officer walked round the pack — and it includes the
    frames that contributed nothing, because "your second shot was too blurred
    to measure" is the sentence that gets a usable photograph taken.
    """


# ---------------------------------------------------------------------------
# Exit zero — the cache, with the one condition that makes it lawful
# ---------------------------------------------------------------------------


def _cache_lookup(scans: ScanStore, skus: SkuStore, *, rulepack_version: str):
    """Build the callable `vision.pipeline.scan` uses for its cheapest exit.

    Section 4: *"Exit zero — the cache [...] roughly 60 ms against 561."*

    **The rulepack version is part of the cache key, and that is not an
    optimisation.** A cached verdict was computed under whichever gazette the
    pack encoded at the time. Replay it after an amendment and the system quotes
    a superseded rule at a manufacturer — the one failure mode in this whole
    design that produces a confident, well-formatted, legally wrong notice. A
    rulepack bump therefore misses every cached scan, which costs one slow scan
    per SKU and is exactly the right price.
    """

    def lookup(identity) -> str | None:
        sku = _resolve_sku(skus, identity)
        if sku is None:
            return None
        previous = scans.latest_for_sku(sku.id)
        if previous is None:
            return None
        row = scans.get(previous)
        if row is None or row.get("rulepack_version") != rulepack_version:
            return None
        return str(previous)

    return lookup


def _resolve_sku(skus: SkuStore, identity) -> SkuRecord | None:
    """Barcode first, then pHash. Section 4's order, and it matters.

    A barcode is an exact key; a perceptual hash is a similarity claim. Trying
    the hash first would occasionally match a different flavour of the same
    product line — same artwork, same layout, different net quantity — and
    section 10 spells out what that costs: 30 g and 100 g of one product have
    *different height thresholds*, so a mismatch there hides a violation with no
    error to announce it.
    """
    barcode = getattr(identity, "barcode", None)
    if barcode:
        found = skus.by_barcode(barcode)
        if found is not None:
            return found
    phash = getattr(identity, "phash", None)
    if phash is not None:
        return skus.by_phash(f"{phash:016x}")
    return None


# ---------------------------------------------------------------------------
# Scale tier B — the tier that works without the marker card
# ---------------------------------------------------------------------------
#
# Section 17, M2: "B falls out free once the repository fills, and it's the
# elegant one: the more the system has seen, the less it needs the marker."
#
# It does not fall out free. It falls out once both of these exist, and until
# 2026-09-19 neither did: `vision/scale/tier_b.py` was implemented, tested, and
# reachable from nothing. Every marker measurement an officer took was
# discarded, so the repository stayed empty, so the tier never fired, so every
# photograph needed the card — which is the procedure section 17 says officers
# will forget.


def _sku_dimensions(sku: SkuRecord | None) -> tier_b.SkuDimensions | None:
    from vision.scale import tier_b

    if sku is None or not sku.label_w_mm:
        return None
    return tier_b.SkuDimensions(
        sku_id=str(sku.id),
        label_width_mm=float(sku.label_w_mm),
        label_height_mm=float(sku.label_h_mm) if sku.label_h_mm else None,
        observations=sku.label_mm_observations,
        stddev_mm=sku.label_w_mm_stddev,
    )


def _dimension_lookup(skus: SkuStore):
    """Build the callable `vision.pipeline.scan` reads scale tier B through.

    The key is `vision.types.Identity.cache_key()` — `barcode:...` or
    `phash:...` — and it is resolved back through `_resolve_sku`, deliberately,
    so that the tier and the verdict cache agree about which SKU a photograph
    is of. Two resolution orders would mean a pack could be measured against
    one SKU's stored label and judged against another's cached verdicts.
    """

    def lookup(cache_key: str):
        kind, _, value = cache_key.partition(":")
        if kind == "barcode" and value:
            identity = SimpleNamespace(barcode=value, phash=None)
        elif kind == "phash" and value:
            try:
                identity = SimpleNamespace(barcode=None, phash=int(value, 16))
            except ValueError:  # pragma: no cover - the key is ours to format
                return None
        else:  # pragma: no cover - `cache_key()` emits nothing else
            return None
        return _sku_dimensions(_resolve_sku(skus, identity))

    return lookup


def _teach_dimensions(outcome, sku: SkuRecord | None, enqueue: Enqueuer | None) -> None:
    """Record what this scan measured, if it is allowed to teach.

    **The primary frame only.** An officer who walks round the pack sends
    several photographs of several *different planes*, and the front panel and
    the back panel of one carton are not the same width. Folding both into one
    running mean would not merely widen the spread, it would make the mean the
    average of two different rectangles — so one scan contributes at most one
    observation, which is also what makes `label_mm_observations` readable as
    "how many scans this came from".

    `tier_b.observe` refuses everything that must not teach (tier B feeding
    itself, a padded detector-box crop, an implausible number) and `admits`
    refuses an outlier against an established SKU. Both are in `vision/`
    because both are measurement decisions, not storage ones.
    """
    from vision.scale import tier_b

    if enqueue is None or sku is None or outcome.rectified is None:
        return
    observation = tier_b.observe(
        outcome.scale,
        width_px=float(outcome.rectified.shape[1]),
        height_px=float(outcome.rectified.shape[0]),
        rectify_method=outcome.rectify_method,
    )
    if observation is None or not tier_b.admits(_sku_dimensions(sku), observation):
        return

    from workers.broker import QUEUE_BULK

    # The low queue, with `bump_scan_count`, and for the identical reason: it is
    # an UPDATE of one row, and a shelf of forty packets of the same SKU is that
    # same row forty times. A dimension that is a few seconds stale costs
    # nothing — the next photograph of this pack is not being taken this second.
    enqueue(
        "record_sku_dimensions",
        queue=QUEUE_BULK,
        sku_id=str(sku.id),
        width_mm=observation.width_mm,
        height_mm=observation.height_mm,
    )


# ---------------------------------------------------------------------------
# Evidence — redact, hash, and decide who uploads
# ---------------------------------------------------------------------------


def prepare_evidence(
    image: Any,
    *,
    scan_id: UUID,
    captured_at: datetime,
    plan: storage.StoragePlan,
    package_box: redact.Box | None,
    blur_faces: bool,
    frame: int = 0,
) -> tuple[bytes | None, EvidenceDecision]:
    """Produce the exact bytes that will be stored, and their digest.

    Returns `None` for the bytes when nothing is to be stored — which is the
    common case on a busy shelf, and the reason section 6's storage figure is
    2.1 GB rather than 30.

    **The privacy failure is closed, not open.** If face detection is required
    and unavailable, no image is stored at all. The scan record, its timestamp,
    its location and its verdicts are still written: section 5's L4 rule is that
    the officer always walks away with a record, and that rule is about the
    *record*, not about the photograph. Storing an unredacted bystander because
    a cascade file was missing would be the wrong way to honour it.
    """
    if not plan.uploads_anything:
        return None, EvidenceDecision(stored=False, reason=plan.reason)

    result = redact.redact_faces(image, package_box=package_box)
    if blur_faces and not result.safe_to_store:
        return None, EvidenceDecision(
            stored=False,
            reason=(
                "no image stored: face redaction is required by section 18 and "
                f"could not run — {result.detail}"
            ),
            redaction=result.detail,
        )

    payload = redact.encode_jpeg(result.image)
    tier = plan.tier or "evidence_original"
    return payload, EvidenceDecision(
        stored=True,
        reason=plan.reason,
        key=storage.frame_key(str(scan_id), frame, captured_at=captured_at),
        sha256=storage.sha256_of(payload),
        tier=tier,
        redaction=result.detail,
        faces_blurred=result.blurred,
        faces_on_package=result.skipped_on_package,
    )


def prepare_annotation(
    outcome: Any,
    verdicts: list[Verdict],
    *,
    plan: storage.StoragePlan,
    blur_faces: bool,
) -> tuple[bytes | None, str]:
    """Draw the declaration boxes on the rectified label. Sections 13 and 6.

    Returns the JPEG and a sentence saying what happened, because "there is no
    picture in this report" has several quite different causes and a reader is
    entitled to know which one applies.

    **Gated on `plan.upload_crops`, which is section 6's own gate**, so the
    annotation follows the storage table rather than inventing a second policy:
    a repeat SKU draws nothing, and neither does a scan with no package in frame.

    **The redaction pass runs again, on this image, and it has to.** The
    rectified label is warped from the *unredacted* frame — the blur applied to
    the evidence copy is in different coordinates and does not carry across. What
    changes is the package box: when rectification actually warped to the label,
    the entire frame is the package, so a face inside it is printed artwork and
    is kept. When rectification fell through to `identity` no warp happened at
    all, the frame is still the whole photograph, and anybody standing behind the
    shelf is a bystander again.
    """
    if not plan.upload_crops:
        return None, "no annotated image: " + plan.reason
    declarations = getattr(outcome, "declarations", None)
    image = getattr(outcome, "rectified", None)
    if declarations is None or image is None:
        return None, "no annotated image: nothing was extracted to annotate"

    from evidence import annotate

    drawing = annotate.draw(
        image,
        declarations.declarations,
        statuses=annotate.statuses_from(verdicts),
    )
    if not drawing.available:
        return None, f"no annotated image: {drawing.detail}"

    warped = getattr(outcome, "rectify_method", "identity") != "identity"
    height, width = drawing.image.shape[:2]
    result = redact.redact_faces(
        drawing.image, package_box=(0, 0, width, height) if warped else None
    )
    if blur_faces and not result.safe_to_store:
        return None, (
            "no annotated image: face redaction is required by section 18 and "
            f"could not run — {result.detail}"
        )

    # 85 rather than the evidence copy's 92. This is an illustration of a
    # finding, not the artefact the finding rests on, and section 6 budgets the
    # derived tier at roughly 40 KB.
    return redact.encode_jpeg(result.image, quality=85), (
        f"{drawing.boxes} declaration(s) marked on the rectified label"
    )


def _package_box(outcome) -> redact.Box | None:
    detection = getattr(outcome, "detection", None)
    best = detection.best_package() if detection is not None else None
    if best is None:
        return None
    x, y, w, h = best.box
    return (int(x), int(y), int(w), int(h))


# ---------------------------------------------------------------------------
# The scan itself
# ---------------------------------------------------------------------------


def run_scan(
    request: ScanRequest,
    *,
    scans: ScanStore,
    skus: SkuStore,
    settings: Settings,
    spool: Any | None = None,
    objects: storage.ObjectStore | None = None,
    enqueue: Enqueuer | None = None,
) -> ScanResult:
    """Extract, evaluate, store. The one implementation both channels use.

    Raises `ValueError` only for a payload that is not an image or is over the
    size limit — those are malformed requests. Everything else degrades: no
    detector, no OCR head, no marker, nothing legible. Section 5's L4.
    """
    payloads = request.frames
    if len(payloads) > MAX_FRAMES:
        raise ValueError(
            f"{len(payloads)} photographs were sent for one package; the limit "
            f"is {MAX_FRAMES}. Several packages is a bulk upload."
        )
    if request.source == "photo" and request.pack_height_mm is None:
        raise ValueError(
            "the height of the photographed face is required, in millimetres. "
            "Measure the side of the pack that faces the camera with a ruler "
            "and enter it; without it the three printed-height rules cannot be "
            "checked at all."
        )
    if request.pack_height_mm is not None:
        low, high = operator_scale.PLAUSIBLE_HEIGHT_MM
        if not (low <= request.pack_height_mm <= high):
            raise ValueError(
                f"{request.pack_height_mm:g} mm is not a plausible height for a "
                f"packaged commodity ({low:g}-{high:g} mm). A decimal point in "
                f"the wrong place here would make every printed character "
                f"measure ten times too small, and every height rule would fail "
                f"a compliant pack."
            )

    for index, chunk in enumerate(payloads):
        if len(chunk) > MAX_UPLOAD_BYTES:
            raise ValueError(
                f"image {index + 1} is {len(chunk) / 1e6:.1f} MB; the limit is "
                f"{MAX_UPLOAD_BYTES / 1e6:.0f} MB"
            )

    from vision.context import ScanContext
    from vision.pipeline import scan as extract

    started = time.perf_counter()
    pack = load_rulepack()
    captured_at = request.captured_at or datetime.now(UTC)

    # -- extract each photograph on its own ---------------------------------
    #
    # Independently, and it has to be independent: each frame is a different
    # photograph of a different plane, so each gets its own quality gate, its
    # own rectification and its own scale. What they share is the package, and
    # that is expressed by unioning what they read rather than by pretending
    # they were one image.
    #
    # **The cache is offered the single-frame case only.** A cached verdict set
    # was computed from one photograph of that SKU; replaying it in answer to
    # three would silently discard the two the officer took *because* one was
    # not enough. Section 4's 60 ms is worth having and it is not worth that.
    lookup = (
        _cache_lookup(scans, skus, rulepack_version=pack.version_string)
        if len(payloads) == 1
        else None
    )
    images = [redact.decode_image(chunk) for chunk in payloads]

    # Offered to every frame, unlike the verdict cache above. A stored label
    # dimension is a fact about the SKU rather than about one photograph, so
    # there is no reason a second frame should be denied it — and a frame whose
    # marker card fell outside the shot is exactly the frame that needs it.
    dimensions = _dimension_lookup(skus)
    scan_context = ScanContext.of(
        str(request.scan_id),
        [
            extract(
                image,
                source=request.source,
                cache_lookup=lookup,
                dimension_lookup=dimensions,
                operator_height_mm=request.pack_height_mm,
                rulepack_version=pack.version_string,
            )
            for image in images
        ],
    )

    outcome = scan_context.primary
    assert outcome is not None  # `frames` is never empty: `payloads` has one
    declarations = scan_context.declarations

    sku = _resolve_sku(skus, outcome.identity)
    context = request.context or PackageContext(
        category=request.category or (sku.category if sku else "unknown")
    )

    # -- verdicts -----------------------------------------------------------
    if outcome.exit_path == "cache_hit" and outcome.cached_scan_id:
        # Replayed, not recomputed. The rulepack version was checked in
        # `_cache_lookup`, so these verdicts were produced under the same
        # gazette the current pack encodes.
        verdicts = [
            Verdict.model_validate(row)
            for row in scans.verdicts_for(UUID(outcome.cached_scan_id))
        ]
    elif declarations is not None:
        # ONE evaluation, over the union of every frame that read something.
        # See `vision/multiframe.py` for why this is not per-frame verdicts
        # combined afterwards: there is no combining rule over verdicts that is
        # right both when a second photograph reveals a violation and when it
        # merely fails to repeat a declaration the first one showed.
        verdicts = evaluate(declarations, context, pack)
    else:
        # No package in frame, or nothing legible. There is nothing to judge and
        # we do not pretend otherwise — no verdicts is not the same as PASS.
        verdicts = []

    latency_ms = int((time.perf_counter() - started) * 1000)

    # -- evidence -----------------------------------------------------------
    is_repeat = sku is not None and scans.latest_for_sku(sku.id) is not None
    plan = storage.plan_for(
        verdicts,
        is_repeat_sku=is_repeat,
        source=request.source,
        # An L4 scan reaches here with an empty verdict list, which reads
        # identically to a clean pass. It is not one, and filing it as compliant
        # would delete the full-resolution original after 90 days — the single
        # artefact section 5 says an L4 record exists to preserve.
        conclusive=bool(verdicts) or declarations is not None,
        has_package=outcome.exit_path != "no_package",
    )

    # Every photograph is redacted, encoded and hashed — not just the one the
    # geometry came from. Section 6 puts the image digest inside the chain so
    # that later alteration is detectable, and a frame that is evidence but has
    # no digest in the record is a frame nobody can defend. The plan is the
    # same for all of them because it is a decision about the SCAN (repeat SKU,
    # verdict severity, source channel), not about any one frame.
    prepared: list[tuple[int, bytes | None, EvidenceDecision]] = []
    for index, image in enumerate(images):
        frame_payload, frame_decision = prepare_evidence(
            image,
            scan_id=request.scan_id,
            captured_at=captured_at,
            plan=plan,
            package_box=_package_box(scan_context.frames[index]),
            blur_faces=settings.blur_faces,
            frame=index,
        )
        prepared.append((index, frame_payload, frame_decision))

    primary_index = scan_context.primary_index or 0
    payload, decision = prepared[primary_index][1], prepared[primary_index][2]

    # -- the row ------------------------------------------------------------
    row: dict[str, Any] = {
        "id": request.scan_id,
        "officer_id": request.officer_id,
        "sku_id": sku.id if sku else None,
        "district": request.district,
        "category": context.category,
        "source": request.source,
        "degradation_tier": (
            declarations.degradation_tier if declarations else outcome.degradation.tier
        ),
        "declaration_set": (declarations.model_dump(mode="json") if declarations else {}),
        # See CHAIN_SAFE_DP: a float too precise for the NUMERIC column comes
        # back changed and the chain reports a record nobody edited as altered.
        "coverage": round(declarations.coverage, CHAIN_SAFE_DP) if declarations else 0.0,
        "latency_ms": latency_ms,
        "cache_hit": outcome.exit_path == "cache_hit",
        "image_key": decision.key,
        "image_sha256": decision.sha256,
        "geo": request.geo,
        "captured_at": captured_at,
        "model_versions": outcome.model_versions,
        "rulepack_version": pack.version_string,
    }

    frame_records = tuple(
        FrameOutcome(
            frame=index,
            exit_path=scan_context.frames[index].exit_path,
            read=scan_context.frames[index].declarations is not None,
            message=scan_context.frames[index].message,
            quality=scan_context.frames[index].quality,
            framing=scan_context.frames[index].framing,
            image_key=frame_decision.key,
            image_sha256=frame_decision.sha256,
            stored=frame_decision.stored,
            reason=frame_decision.reason,
        )
        for index, _, frame_decision in prepared
    )

    # **Added to the row only when there is more than one frame**, and that is
    # not tidiness. The chain hashes whatever keys the payload carries, so a
    # single-frame scan that grew a `frames: null` would hash differently from
    # the millions of single-frame scans already chained, and every one of them
    # would fail verification. A key that appears only when it has something to
    # say costs nothing and keeps every existing record verifiable.
    if len(frame_records) > 1:
        row["frames"] = [record.as_row() for record in frame_records]
    stored = scans.save(row)
    if stored.created:
        scans.save_verdicts(
            request.scan_id, [verdict.model_dump(mode="json") for verdict in verdicts]
        )

    # -- everything after this point is off the critical path ---------------
    #
    # All frames, primary last, so `decision` ends up holding the primary
    # frame's outcome — that is the one the scan row points at and the one the
    # report prints.
    handed: dict[int, EvidenceDecision] = {}
    for index, frame_payload, frame_decision in prepared:
        if frame_payload is None or frame_decision.key is None:
            handed[index] = frame_decision
            continue
        handed[index] = _hand_off_evidence(
            frame_payload,
            frame_decision,
            scan_id=request.scan_id,
            captured_at=captured_at,
            spool=spool,
            objects=objects,
            enqueue=enqueue,
            frame=index,
        )
    decision = handed[primary_index]

    annotation, annotation_note = prepare_annotation(
        outcome, verdicts, plan=plan, blur_faces=settings.blur_faces
    )
    decision = _hand_off_annotation(
        annotation,
        decision,
        note=annotation_note,
        scan_id=request.scan_id,
        captured_at=captured_at,
        spool=spool,
        objects=objects,
        enqueue=enqueue,
    )

    if enqueue is not None and sku is not None:
        from workers.broker import QUEUE_BULK

        # A counter, on the low queue. Section 8c: "`scan_count` comes off the
        # critical path." It feeds the offline cache warm list, and being a few
        # seconds stale costs nothing.
        enqueue("bump_scan_count", queue=QUEUE_BULK, sku_id=str(sku.id))

    _teach_dimensions(outcome, sku, enqueue)

    if len(frame_records) > 1:
        frame_records = tuple(
            record
            if handed[record.frame] is prepared[record.frame][2]
            else FrameOutcome(
                frame=record.frame,
                exit_path=record.exit_path,
                read=record.read,
                message=record.message,
                quality=record.quality,
                framing=record.framing,
                image_key=handed[record.frame].key,
                image_sha256=handed[record.frame].sha256,
                stored=handed[record.frame].stored,
                reason=handed[record.frame].reason,
            )
            for record in frame_records
        )

    return ScanResult(
        scan_id=request.scan_id,
        exit_path=outcome.exit_path,
        source=request.source,
        degradation_tier=str(row["degradation_tier"]),
        coverage=float(row["coverage"] or 0.0),
        latency_ms=latency_ms,
        cache_hit=bool(row["cache_hit"]),
        declarations=declarations,
        verdicts=verdicts,
        message=outcome.message,
        model_versions=outcome.model_versions,
        rulepack_version=pack.version_string,
        stored=stored,
        evidence=decision,
        sku=sku,
        capture_quality=outcome.quality,
        framing=outcome.framing,
        frames=frame_records if len(frame_records) > 1 else (),
    )


def _hand_off_evidence(
    payload: bytes,
    decision: EvidenceDecision,
    *,
    scan_id: UUID,
    captured_at: datetime,
    spool: Any | None,
    objects: storage.ObjectStore | None,
    enqueue: Enqueuer | None,
    frame: int = 0,
) -> EvidenceDecision:
    """Give the bytes to a worker if we can, upload them here if we cannot.

    The fallback is not a nicety. `evidence/spool.py` explains the failure it
    guards: a scan row referencing an object that was never written is loudly
    detectable but still a missing photograph, and *"a finding with no
    photograph is an allegation, not evidence"*. A slower response is a much
    smaller problem, so a spool that refuses the bytes — Redis down, cap
    reached — falls straight through to an inline PUT.
    """
    from dataclasses import replace

    # Frame 0 spools under the bare scan id, exactly as it always has, so a
    # worker mid-flight across a deploy still finds what it was told about.
    slot = str(scan_id) if frame == 0 else f"{scan_id}:frame{frame}"

    if spool is not None and enqueue is not None and spool.put(slot, payload):
        from workers.broker import QUEUE_SCAN

        enqueue(
            "store_evidence",
            queue=QUEUE_SCAN,
            scan_id=str(scan_id),
            captured_at=captured_at.isoformat(),
            tier=decision.tier,
            sha256=decision.sha256,
            frame=frame,
        )
        return replace(decision, deferred=True)

    if objects is None:
        return replace(
            decision,
            stored=False,
            reason=(
                f"{decision.reason} — but no object store is configured and the "
                f"queue did not accept the bytes, so nothing was written"
            ),
        )

    storage.put_evidence(
        objects,
        payload,
        scan_id=str(scan_id),
        captured_at=captured_at,
        tier=decision.tier or "evidence_original",
        key=decision.key,
    )
    return decision


def _hand_off_annotation(
    payload: bytes | None,
    decision: EvidenceDecision,
    *,
    note: str,
    scan_id: UUID,
    captured_at: datetime,
    spool: Any | None,
    objects: storage.ObjectStore | None,
    enqueue: Enqueuer | None,
) -> EvidenceDecision:
    """Queue the annotated label, or write it here. Never block on it.

    On the **scan** queue rather than `bulk`, for the same reason `render_report`
    is: an officer who has just seen a FAIL may press "report" within seconds,
    and a report is rendered from whatever is in the derived bucket at that
    moment. Behind an overnight import of three hundred files, the annotation
    would not be there and the exhibit would silently be missing from the one
    document that needed it.

    A failure to store the drawing is recorded and never raised. The finding, the
    verdicts and the photograph are all already written; losing an illustration
    of them must not fail a scan.
    """
    from dataclasses import replace

    if payload is None:
        return replace(decision, annotation_reason=note)

    key = storage.annotation_key(str(scan_id), captured_at=captured_at)

    if spool is not None and enqueue is not None and spool.put(f"annot:{scan_id}", payload):
        from workers.broker import QUEUE_SCAN

        enqueue(
            "store_annotation",
            queue=QUEUE_SCAN,
            scan_id=str(scan_id),
            captured_at=captured_at.isoformat(),
        )
        return replace(decision, annotation_key=key, annotation_reason=note)

    if objects is None:
        return replace(
            decision,
            annotation_reason=(
                f"{note}, but no object store is configured and the queue did not "
                f"accept the bytes, so it was not written"
            ),
        )

    storage.put_annotation(objects, payload, scan_id=str(scan_id), captured_at=captured_at)
    return replace(decision, annotation_key=key, annotation_reason=note)


__all__ = [
    "CHAIN_SAFE_DP",
    "MAX_FRAMES",
    "MAX_UPLOAD_BYTES",
    "Enqueuer",
    "FrameOutcome",
    "EvidenceDecision",
    "ScanRequest",
    "ScanResult",
    "prepare_annotation",
    "prepare_evidence",
    "run_scan",
]
