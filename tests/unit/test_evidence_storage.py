"""Section 6's retention policy, and the storage claim on the slide.

    | Store everything at full resolution | ~30 GB per 10,000 scans |
    | Ours                                | **~2.1 GB**             |

That 14x is an argument made to a government jury about running cost, so it is
worth a test rather than a spreadsheet nobody can find later.

No MinIO runs here. `ObjectStore` is a Protocol precisely so the *policy* —
which is where the saving comes from, and where a mistake silently costs
evidence — can be tested as arithmetic.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta

import pytest

from contracts import Verdict
from evidence.storage import (
    DOWNSCALE_AFTER_DAYS,
    EVIDENCE_BUCKET,
    RETENTION_DAYS,
    StoredObject,
    crop_key,
    due_for_downscale,
    ensure_buckets,
    expires_on,
    object_key,
    plan_for,
    put_evidence,
    sha256_of,
    verify_object,
)

CAPTURED = datetime(2026, 9, 7, 11, 30, tzinfo=UTC)


def _verdict(status: str, rule_id: str = "LMPC.MRP.NUMERAL_HEIGHT") -> Verdict:
    return Verdict(
        rule_id=rule_id,
        rule_ref="Rule 7(2), Table I",
        status=status,
        severity="high",
        field="mrp",
        found="1.77 mm",
        expected=">= 2.0 mm",
        message="MRP numerals below the minimum height for this net quantity.",
    )


class FakeStore:
    """An in-memory stand-in that records what it was asked to do."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.buckets: set[str] = set()
        self.puts = 0

    def bucket_exists(self, bucket_name: str) -> bool:
        return bucket_name in self.buckets

    def make_bucket(self, bucket_name: str, **kwargs) -> None:
        self.buckets.add(bucket_name)

    def put_object(self, bucket_name, object_name, data, length, **kwargs) -> None:
        self.puts += 1
        self.objects[(bucket_name, object_name)] = data.read()

    def get_object(self, bucket_name, object_name):
        import io

        return io.BytesIO(self.objects[(bucket_name, object_name)])

    def remove_object(self, bucket_name, object_name, **kwargs) -> None:
        self.objects.pop((bucket_name, object_name), None)


# ---------------------------------------------------------------------------
# The policy — where the 14x actually comes from
# ---------------------------------------------------------------------------


def test_a_repeat_sku_uploads_nothing():
    """The cache-first design paying for itself a second time.

    Section 6: "On a shelf of 40 packets with 12 unique SKUs, 28 scans upload
    nothing." A violation is printed at design time, so a second photograph of
    the same printed label adds no evidence.
    """
    plan = plan_for([_verdict("FAIL")], is_repeat_sku=True)
    assert not plan.uploads_anything
    assert "repeat SKU" in plan.reason


def test_a_fail_keeps_a_full_resolution_original():
    plan = plan_for([_verdict("PASS"), _verdict("FAIL")], is_repeat_sku=False)
    assert plan.upload_original
    assert plan.tier == "evidence_original"
    assert "allegation, not evidence" in plan.reason


def test_a_review_keeps_an_original_too():
    """The one most likely to be got wrong.

    A REVIEW is a near-threshold measurement we deliberately refused to convict
    on — exactly the case a human will re-examine, and exactly the case where
    the photograph must still exist when they do. Keeping originals only for
    FAIL would discard the evidence for every finding we were careful about.
    """
    plan = plan_for([_verdict("PASS"), _verdict("REVIEW")], is_repeat_sku=False)
    assert plan.tier == "evidence_original"


def test_a_fully_compliant_scan_is_downscaled_not_kept_forever():
    plan = plan_for([_verdict("PASS"), _verdict("NOT_APPLICABLE")], is_repeat_sku=False)
    assert plan.upload_original
    assert plan.tier == "compliant_downscaled"


def test_no_data_alone_does_not_trigger_evidence_retention():
    """`NO_DATA` is an absence of evidence, not an adverse finding.

    Treating it as one would keep seven years of full-resolution imagery for
    every scan where the scale was missing — which at tier C is a lot of them.
    """
    plan = plan_for([_verdict("PASS"), _verdict("NO_DATA")], is_repeat_sku=False)
    assert plan.tier == "compliant_downscaled"


def test_listing_text_stores_no_image():
    """The third channel has no pixels at all."""
    plan = plan_for([_verdict("FAIL")], is_repeat_sku=False, source="listing_text")
    assert not plan.uploads_anything


def test_the_shelf_arithmetic_on_the_slide():
    """40 packets, 12 unique SKUs, 28 uploading nothing."""
    unique, repeats = 12, 28
    plans = [plan_for([_verdict("PASS")], is_repeat_sku=False) for _ in range(unique)]
    plans += [plan_for([_verdict("PASS")], is_repeat_sku=True) for _ in range(repeats)]

    uploading = [plan for plan in plans if plan.uploads_anything]
    assert len(uploading) == unique
    assert len(plans) - len(uploading) == 28


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tier", "days"),
    [
        ("evidence_original", 365 * 7),
        ("derived_crop", 365 * 2),
        ("compliant_downscaled", 365),
        ("hash_only", None),
    ],
)
def test_retention_matches_the_section_6_table(tier, days):
    assert RETENTION_DAYS[tier] == days


def test_hash_and_metadata_are_kept_forever():
    assert expires_on("hash_only", captured_at=date(2026, 9, 7)) is None


def test_evidence_originals_survive_seven_years():
    """A prosecution can take that long."""
    expiry = expires_on("evidence_original", captured_at=date(2026, 9, 7))
    assert expiry is not None
    assert expiry.year == 2033


def test_a_compliant_scan_is_downscaled_after_ninety_days():
    captured = date(2026, 9, 7)
    assert not due_for_downscale(
        "compliant_downscaled", captured_at=captured, today=captured + timedelta(days=89)
    )
    assert due_for_downscale(
        "compliant_downscaled",
        captured_at=captured,
        today=captured + timedelta(days=DOWNSCALE_AFTER_DAYS),
    )


def test_an_evidence_original_is_never_downscaled():
    """Downscaling the image behind a FAIL would destroy the measurement it supports.

    This is the single most damaging thing a retention sweep could do, because
    it would happen silently and only be discovered when the evidence was
    needed.
    """
    captured = date(2020, 1, 1)
    assert not due_for_downscale(
        "evidence_original", captured_at=captured, today=date(2026, 9, 7)
    )


# ---------------------------------------------------------------------------
# Keys and hashing
# ---------------------------------------------------------------------------


def test_keys_are_date_partitioned_so_retention_sweeps_are_a_prefix_scan():
    key = object_key("abc-123", captured_at=CAPTURED)
    assert key == "2026/09/07/abc-123.jpg"
    assert crop_key("abc-123", 2, captured_at=CAPTURED) == "2026/09/07/abc-123/roi-02.jpg"


def test_the_digest_is_over_the_exact_bytes_uploaded():
    """If the stored digest and the stored bytes ever differ, the chain attests
    to something nobody can reproduce."""
    store = FakeStore()
    ensure_buckets(store)
    payload = b"\xff\xd8\xff\xe0 not really a jpeg"

    stored = put_evidence(store, payload, scan_id="abc-123", captured_at=CAPTURED)

    assert stored.bucket == EVIDENCE_BUCKET
    assert stored.sha256 == hashlib.sha256(payload).hexdigest()
    assert stored.size_bytes == len(payload)
    assert store.objects[(stored.bucket, stored.key)] == payload


def test_ensure_buckets_is_idempotent():
    store = FakeStore()
    ensure_buckets(store)
    before = set(store.buckets)
    ensure_buckets(store)
    assert store.buckets == before


def test_a_swapped_photograph_is_detected():
    """The other half of "later alteration is detectable".

    The chain proves the record was not edited. This proves the photograph
    behind it is still the one that produced the measurement.
    """
    store = FakeStore()
    ensure_buckets(store)
    stored = put_evidence(store, b"original bytes", scan_id="s1", captured_at=CAPTURED)
    assert verify_object(store, stored)

    store.objects[(stored.bucket, stored.key)] = b"substituted bytes"
    assert not verify_object(store, stored)


def test_sha256_of_is_stable():
    assert sha256_of(b"") == hashlib.sha256(b"").hexdigest()


def test_stored_object_reports_its_own_retention():
    stored = StoredObject(
        bucket=EVIDENCE_BUCKET, key="k", sha256="0" * 64, size_bytes=1, tier="derived_crop"
    )
    assert stored.retention_days == 365 * 2
