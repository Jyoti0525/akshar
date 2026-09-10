"""Evidence object storage — AKSHAR.md section 6.

    "Images never go in the database. A Postgres row holding a 3 MB blob wrecks
     query performance, backup times and replication."

    "A Legal Metrology violation can lead to compounding or prosecution, and **a
     finding with no photograph is an allegation, not evidence.**"

Two statements that look contradictory and are not. The image is kept; it is
kept *beside* the database, and the row holds a key and a SHA-256.

**The retention policy is the interesting part, and it is why this is cheap.**
Section 6's table is not a storage convention — it is the answer to "isn't this
expensive to run", which a government jury genuinely asks:

    Store everything at full resolution   ~30 GB per 10,000 scans
    Ours                                  ~2.1 GB

Roughly 14x less, with every legally required photograph still present. Three
decisions get us there, and each is a method below:

1.  **Only FAIL and REVIEW scans keep a full-resolution original.** A compliant
    pack does not need seven years of evidence-grade imagery; it needs enough to
    show what was checked.
2.  **A repeat SKU stores nothing at all.** On a shelf of 40 packets with 12
    unique SKUs, 28 scans upload nothing — the cache-first design paying for
    itself a second time.
3.  **Compliant scans are downscaled after 90 days**, then reduced to a hash.

**Write-once, versioned, with governance retention.** The bucket is created with
versioning and an object-lock retention rule, so an object cannot be silently
replaced or deleted — an overwrite becomes a new version and the original stays
recoverable. Deletion of evidence therefore leaves a trace, which is the point:
the hash chain proves a *record* was not edited, and versioning proves the
*photograph* behind it was not swapped. `docker-compose.yml` sets the same
retention on `akshar-evidence` so a local stack behaves like production.

**No connection is opened at import.** `vision/` and `rules/` must never see a
database, and `tests/test_boundaries.py` enforces it. This module is transport
and lives outside that wall — but it still takes its client from the caller so
the retention arithmetic is unit-testable with no MinIO running.
"""

from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal, Protocol

from contracts import Verdict

Tier = Literal[
    "evidence_original", "derived_crop", "compliant_downscaled", "hash_only", "report"
]

EVIDENCE_BUCKET = os.environ.get("AKSHAR_EVIDENCE_BUCKET", "akshar-evidence")
DERIVED_BUCKET = os.environ.get("AKSHAR_DERIVED_BUCKET", "akshar-derived")

# Section 6's table, as data rather than as prose in a method.
RETENTION_DAYS: dict[Tier, int | None] = {
    "evidence_original": 365 * 7,   # 7 years — a prosecution can take that long
    "derived_crop": 365 * 2,        # 2 years — the 4-8 declaration ROIs, ~40 KB
    "compliant_downscaled": 365,    # 1 year, then hash only
    "hash_only": None,              # forever, and it is 64 characters

    # A rendered report is a CACHE, not evidence, and this is the one entry in
    # this table where that is true. Everything a report contains — the
    # declarations, the verdicts, the model digests, the rulepack version — is
    # already stored in columns precisely so the document can be rebuilt from
    # them (section 14). Deleting one loses a file, not a finding. Two years is
    # therefore a convenience for the common case of somebody re-opening a case
    # file, not a legal retention period, and it must never be the only place a
    # finding exists.
    "report": 365 * 2,
}

DOWNSCALE_AFTER_DAYS = 90
"""A compliant scan keeps its full-resolution image for 90 days, then drops to
1024 px. Long enough for a dispute to surface, short enough that the bulk of
storage is images somebody actually needs."""

DOWNSCALE_LONG_SIDE = 1024

_KEEP_ORIGINAL_FOR: frozenset[str] = frozenset({"FAIL", "REVIEW"})
"""Only these two statuses justify an evidence-grade original.

`REVIEW` is included deliberately, and it is easy to get wrong. A REVIEW is a
measurement near a threshold that we have refused to convict on — precisely the
case a human will re-examine, and precisely the case where the photograph must
still exist when they do. Keeping originals only for FAIL would throw away the
evidence for every finding we were careful about.
"""


class ObjectStore(Protocol):
    """The slice of MinIO/S3 this module uses.

    A Protocol rather than a `Minio` import so retention logic can be tested
    without a running server, and so a deployment can substitute S3 or any
    compatible store without touching this file.
    """

    def put_object(
        self, bucket_name: str, object_name: str, data: Any, length: int, **kwargs: Any
    ) -> Any: ...

    def get_object(self, bucket_name: str, object_name: str) -> Any: ...

    def remove_object(self, bucket_name: str, object_name: str, **kwargs: Any) -> Any: ...

    def bucket_exists(self, bucket_name: str) -> bool: ...

    def make_bucket(self, bucket_name: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class StoredObject:
    bucket: str
    key: str
    sha256: str
    size_bytes: int
    tier: Tier

    @property
    def retention_days(self) -> int | None:
        return RETENTION_DAYS[self.tier]


@dataclass(frozen=True, slots=True)
class StoragePlan:
    """What to upload for one scan, decided BEFORE any bytes move.

    Deciding first and uploading second is what makes "repeat SKU scans upload
    nothing" true rather than aspirational: a plan with `upload_original=False`
    and no crops costs one boolean, whereas discovering it after a 3 MB PUT
    costs the 3 MB.
    """

    upload_original: bool
    upload_crops: bool
    tier: Tier | None
    reason: str

    @property
    def uploads_anything(self) -> bool:
        return self.upload_original or self.upload_crops


def sha256_of(payload: bytes) -> str:
    """The digest that goes into the scan row and therefore into the hash chain.

    Section 6: "Every image is hashed at upload and the hash lives inside the
    chain, so later alteration is detectable." This is the only link between the
    object store and the evidence chain, and it is one column.
    """
    return hashlib.sha256(payload).hexdigest()


def object_key(scan_id: str, *, captured_at: datetime, suffix: str = "jpg") -> str:
    """Date-partitioned key: `2026/09/07/<scan_id>.jpg`.

    Partitioning by capture date rather than by SKU or district because
    retention sweeps run by age, and a prefix scan over a date range is the
    cheapest possible way to find everything that has aged out.
    """
    return f"{captured_at:%Y/%m/%d}/{scan_id}.{suffix}"


def crop_key(scan_id: str, index: int, *, captured_at: datetime) -> str:
    return f"{captured_at:%Y/%m/%d}/{scan_id}/roi-{index:02d}.jpg"


def frame_key(scan_id: str, frame: int, *, captured_at: datetime) -> str:
    """Where the SECOND and later photographs of one pack live.

    Frame 0 keeps `object_key` — `2026/09/07/<scan_id>.jpg` — so a scan taken
    the way every scan was taken before multi-frame capture existed has exactly
    the object it always had, at exactly the key `scans.image_key` already
    holds. The extra frames sit beside it under the same date partition, so the
    retention sweep finds them by the same prefix scan and ages them out with
    the record they belong to.
    """
    if frame == 0:
        return object_key(scan_id, captured_at=captured_at)
    return f"{captured_at:%Y/%m/%d}/{scan_id}/frame-{frame:02d}.jpg"


def annotation_key(scan_id: str, *, captured_at: datetime) -> str:
    """The single annotated label that the report prints. Section 13.

    Section 6 describes the derived tier as *"the 4-8 declaration ROIs"*, and one
    composited image carries all of them: every declaration box drawn on the
    rectified label it was measured in. That is one object rather than eight, and
    it is the artefact the report actually lays out — a page of disconnected
    crops would not show a reader that the MRP sits on the principal display
    panel, which is itself a finding under Rule 8(1).

    Individual crops keep `crop_key`; nothing forbids storing both, and a future
    reviewer UI that wants to zoom one declaration will want them.
    """
    return f"{captured_at:%Y/%m/%d}/{scan_id}/annotated.jpg"


REPORT_CONTENT_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "html": "text/html; charset=utf-8",
}


def report_key(scan_id: str, *, captured_at: datetime, fmt: str) -> str:
    """Where a rendered report lives. Same date partition as its photograph.

    Partitioned by capture date rather than render date so a report sits beside
    the evidence it describes, and so the retention sweep that walks a date
    prefix finds both. A report rendered twice — the officer asked again after a
    rulepack upgrade — overwrites, and that is correct: the derived bucket is not
    versioned, because the authoritative version of this document is the scan
    row it was built from.
    """
    if fmt not in REPORT_CONTENT_TYPES:
        raise ValueError(f"unsupported report format {fmt!r}")
    return f"{captured_at:%Y/%m/%d}/{scan_id}/report.{fmt}"


def put_report(
    client: ObjectStore,
    payload: bytes,
    *,
    scan_id: str,
    captured_at: datetime,
    fmt: str,
) -> StoredObject:
    """Store a rendered report in the DERIVED bucket. Never the evidence bucket.

    The evidence bucket carries a seven-year governance lock, which makes an
    object there effectively undeletable. A regenerable document does not belong
    under that lock: it would grow the one store that cannot be pruned, for
    files that can be rebuilt in 300 ms.
    """
    key = report_key(scan_id, captured_at=captured_at, fmt=fmt)
    digest = sha256_of(payload)
    client.put_object(
        DERIVED_BUCKET,
        key,
        io.BytesIO(payload),
        len(payload),
        content_type=REPORT_CONTENT_TYPES[fmt],
        metadata={"x-amz-meta-sha256": digest, "x-amz-meta-scan-id": scan_id},
    )
    return StoredObject(
        bucket=DERIVED_BUCKET, key=key, sha256=digest, size_bytes=len(payload), tier="report"
    )


def put_annotation(
    client: ObjectStore,
    payload: bytes,
    *,
    scan_id: str,
    captured_at: datetime,
) -> StoredObject:
    """Store the annotated label in the DERIVED bucket, on the crop tier.

    Two years, not seven, and outside the governance lock — because this image
    is *derived*. The evidence is the original photograph; this is a drawing of
    what we concluded about it, and it can be redrawn from the stored
    declaration set for as long as the original survives.
    """
    key = annotation_key(scan_id, captured_at=captured_at)
    digest = sha256_of(payload)
    client.put_object(
        DERIVED_BUCKET,
        key,
        io.BytesIO(payload),
        len(payload),
        content_type="image/jpeg",
        metadata={
            "x-amz-meta-sha256": digest,
            "x-amz-meta-tier": "derived_crop",
            "x-amz-meta-scan-id": scan_id,
        },
    )
    return StoredObject(
        bucket=DERIVED_BUCKET,
        key=key,
        sha256=digest,
        size_bytes=len(payload),
        tier="derived_crop",
    )


def get_derived(client: ObjectStore, key: str) -> bytes | None:
    """Fetch one object from the derived bucket, or None if it is not there.

    Absence is the ordinary state of affairs here, not an error: a report whose
    render job is still queued, an annotation for a scan that stored no image.
    Every caller wants to carry on without it, so a missing key returns None
    rather than propagating an `S3Error` as a 500 to an officer.
    """
    try:
        response = client.get_object(DERIVED_BUCKET, key)
    except Exception:
        # MinIO raises `S3Error` for a missing key.
        return None
    try:
        return response.read()
    finally:
        for name in ("close", "release_conn"):
            method = getattr(response, name, None)
            if method:
                method()


def get_report(client: ObjectStore, key: str) -> bytes | None:
    """Fetch a rendered report, or None if it has not been rendered yet."""
    return get_derived(client, key)


def plan_for(
    verdicts: list[Verdict],
    *,
    is_repeat_sku: bool,
    source: str = "photo",
    conclusive: bool = True,
    has_package: bool = True,
) -> StoragePlan:
    """Decide what this scan is allowed to store. Section 6's table, as a function.

    Order matters: the repeat-SKU check comes first, because it is the one that
    saves the most and it applies regardless of verdict. A repeat SKU has
    already been photographed; storing a second copy of the same printed label
    buys nothing legally and costs 3 MB.

    **`conclusive=False` is not a detail, and getting it wrong quietly destroys
    evidence.** An L4 scan — nothing legible recovered — produces *no verdicts*.
    Read only the verdict list and that is indistinguishable from a clean pass,
    so the scan is filed as `compliant_downscaled` and its full-resolution
    original is thrown away after 90 days. But section 5 is explicit that the
    photograph is the entire point of an L4 record: *"even in the worst case the
    officer walks away with a timestamped evidence record"*, and that record is
    a picture nobody could read yet. It is queued for a human, which is the same
    situation as `REVIEW` and gets the same seven-year original.

    Absence of verdicts is not evidence of compliance — the same distinction
    `NO_DATA` draws in the rules engine, arriving here as a storage decision.
    """
    if is_repeat_sku:
        return StoragePlan(
            upload_original=False,
            upload_crops=False,
            tier=None,
            reason=(
                "repeat SKU — the label was photographed when this SKU was first "
                "seen, and a violation is printed at design time, so a second copy "
                "adds no evidence"
            ),
        )

    if source == "listing_text":
        return StoragePlan(
            upload_original=False,
            upload_crops=False,
            tier=None,
            reason="listing text has no pixels to store",
        )

    if not has_package:
        # Section 4's exit one: a shelf, a floor, a hand. This is NOT the L4
        # case below — there is no package to have photographed, so there is no
        # evidence to preserve, and seven years of a picture of a countertop
        # serves nobody. The scan row is still written; it records that an
        # officer pointed a camera and the system honestly found nothing.
        return StoragePlan(
            upload_original=False,
            upload_crops=False,
            tier=None,
            reason="no package in frame — there is nothing here to evidence",
        )

    if not conclusive:
        return StoragePlan(
            upload_original=True,
            upload_crops=True,
            tier="evidence_original",
            reason=(
                "nothing legible was recovered — the photograph IS the record, "
                "and it is queued for a human to read"
            ),
        )

    statuses = {verdict.status for verdict in verdicts}
    adverse = sorted(statuses & _KEEP_ORIGINAL_FOR)

    if adverse:
        return StoragePlan(
            upload_original=True,
            upload_crops=True,
            tier="evidence_original",
            reason=(
                f"scan carries {'/'.join(adverse)} — a finding with no photograph "
                f"is an allegation, not evidence"
            ),
        )

    return StoragePlan(
        upload_original=True,
        upload_crops=True,
        tier="compliant_downscaled",
        reason=(
            f"compliant scan — full resolution for {DOWNSCALE_AFTER_DAYS} days, then "
            f"downscaled to {DOWNSCALE_LONG_SIDE} px"
        ),
    )


def expires_on(tier: Tier, *, captured_at: date) -> date | None:
    """When this object may be deleted. `None` means never."""
    days = RETENTION_DAYS[tier]
    return None if days is None else captured_at + timedelta(days=days)


def due_for_downscale(tier: Tier, *, captured_at: date, today: date) -> bool:
    """Has a compliant scan's full-resolution copy outlived its usefulness?

    Only `compliant_downscaled` objects are ever downscaled. An
    `evidence_original` is kept at full resolution for its whole seven years:
    downscaling the image behind a FAIL would destroy the measurement it
    supports, which is the one thing this store exists to prevent.
    """
    if tier != "compliant_downscaled":
        return False
    return today >= captured_at + timedelta(days=DOWNSCALE_AFTER_DAYS)


def ensure_buckets(client: ObjectStore) -> None:
    """Create the buckets if absent. Idempotent; safe to call on every boot.

    Versioning and object-lock retention are set by `minio-init` in
    `docker-compose.yml` rather than here, because they must be applied at
    creation time and the compose service is what a fresh clone runs. This only
    guarantees the buckets exist.
    """
    for bucket in (EVIDENCE_BUCKET, DERIVED_BUCKET):
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)


def put_evidence(
    client: ObjectStore,
    payload: bytes,
    *,
    scan_id: str,
    captured_at: datetime,
    tier: Tier = "evidence_original",
    content_type: str = "image/jpeg",
    key: str | None = None,
) -> StoredObject:
    """Upload one object and return its key and digest.

    The digest is computed over the exact bytes uploaded — not over the image
    before compression, not over a re-encode. If those two ever differ, the
    chain would attest to bytes nobody can reproduce.

    `key` overrides the derived one, and exists for `frame_key`: a multi-frame
    scan writes several evidence objects under one scan id, and they cannot all
    be `<scan_id>.jpg`. The metadata still names the scan, because the object
    belongs to the scan and not to the frame.
    """
    bucket = EVIDENCE_BUCKET if tier != "derived_crop" else DERIVED_BUCKET
    key = key or object_key(scan_id, captured_at=captured_at)
    digest = sha256_of(payload)

    client.put_object(
        bucket,
        key,
        io.BytesIO(payload),
        len(payload),
        content_type=content_type,
        metadata={
            "x-amz-meta-sha256": digest,
            "x-amz-meta-tier": tier,
            "x-amz-meta-scan-id": scan_id,
        },
    )
    return StoredObject(
        bucket=bucket, key=key, sha256=digest, size_bytes=len(payload), tier=tier
    )


def verify_object(client: ObjectStore, stored: StoredObject) -> bool:
    """Re-download and re-hash. The other half of "later alteration is detectable".

    The chain proves the *record* was not edited. This proves the *photograph*
    behind it is still the one that produced the measurement — which is the
    question a manufacturer disputing a 1.8 mm finding will actually ask.
    """
    response = client.get_object(stored.bucket, stored.key)
    try:
        payload = response.read()
    finally:
        close = getattr(response, "close", None)
        if close:
            close()
        release = getattr(response, "release_conn", None)
        if release:
            release()
    return sha256_of(payload) == stored.sha256


__all__ = [
    "DERIVED_BUCKET",
    "DOWNSCALE_AFTER_DAYS",
    "DOWNSCALE_LONG_SIDE",
    "EVIDENCE_BUCKET",
    "REPORT_CONTENT_TYPES",
    "RETENTION_DAYS",
    "ObjectStore",
    "StoragePlan",
    "StoredObject",
    "Tier",
    "annotation_key",
    "crop_key",
    "due_for_downscale",
    "ensure_buckets",
    "expires_on",
    "frame_key",
    "get_derived",
    "get_report",
    "object_key",
    "plan_for",
    "put_annotation",
    "put_evidence",
    "put_report",
    "report_key",
    "sha256_of",
    "verify_object",
]
