"""M7 — canonical JSON, the hash chain, and detecting tampering.

    "Done when: `verify_chain()` detects any tampered historical record."
                                                          -- section 17, M7

This is the one acceptance criterion in the whole plan that can be met in full
with no corpus, no weights and no photographs — so it is met in full here.

The tests are organised as the threat is: first that hashing is *reproducible*
(a chain that fires on records nobody touched is worse than no chain, because a
false alarm teaches people to ignore the alarm), then that each of the four
distinct tampering modes is actually caught and correctly named.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from itertools import pairwise
from uuid import UUID

import pytest

from evidence.chain import (
    GENESIS_PREV,
    CanonicalisationError,
    append,
    canonical_json,
    from_row,
    record_hash,
)
from evidence.verify import head_digest, verify_chain

CAPTURED = datetime(2026, 9, 7, 11, 30, 0, tzinfo=UTC)


def _scan(index: int) -> dict:
    """A scan record shaped like the `scans` table in section 10."""
    return {
        "id": UUID(int=index),
        "sku_id": UUID(int=1000 + index),
        "officer_id": UUID(int=77),
        "district": "Khordha",
        "source": "photo",
        "degradation_tier": "L0",
        "image_key": f"evidence/2026/09/{index}.jpg",
        "image_sha256": f"{index:064x}",
        "declaration_set": {
            "declarations": [
                {
                    "field": "mrp",
                    "text": "MRP Rs. 45.00 (inclusive of all taxes)",
                    "height_mm": 1.77,
                    "height_mm_tolerance": 0.08,
                    "script": "latin",
                },
                {
                    "field": "net_quantity",
                    "text": "शुद्ध मात्रा 250 g",
                    "height_mm": 2.10,
                    "script": "devanagari",
                },
            ],
            "coverage": 0.94,
        },
        "coverage": Decimal("0.94"),
        "latency_ms": 561,
        "cache_hit": False,
        "captured_at": CAPTURED + timedelta(minutes=index),
        "model_versions": {"detector": "rtmdet-ins-tiny@int8", "ocr": "ppocrv5"},
        "rulepack_version": "lmpc_2011@2026.03",
    }


def _build(n: int) -> list:
    records = []
    previous = None
    for index in range(n):
        previous = append(_scan(index), previous=previous)
        records.append(previous)
    return records


# ---------------------------------------------------------------------------
# Canonicalisation — the chain is decorative without it
# ---------------------------------------------------------------------------


def test_key_order_does_not_change_the_digest():
    """Two servers building the same record from different code paths must agree."""
    a = {"alpha": 1, "beta": 2, "gamma": {"x": 1, "y": 2}}
    b = {"gamma": {"y": 2, "x": 1}, "beta": 2, "alpha": 1}
    assert canonical_json(a) == canonical_json(b)


def test_devanagari_is_hashed_as_text_not_escapes():
    """A Hindi declaration must hash as the text it is.

    `ensure_ascii=True` would hash `\\u0936\\u0941...`, which is stable but
    means the bytes we sign bear no resemblance to the evidence. UTF-8 pins the
    byte order, so this is deterministic without being unreadable.
    """
    blob = canonical_json({"text": "शुद्ध मात्रा 250 g"})
    assert "शुद्ध".encode() in blob
    assert b"\\u09" not in blob


def test_whitespace_and_formatting_cannot_shift_the_digest():
    payload = {"a": [1, 2, {"b": "c"}]}
    assert canonical_json(payload) == b'{"a":[1,2,{"b":"c"}]}'


def test_naive_and_aware_datetimes_agree_when_they_mean_the_same_moment():
    """Drivers differ on whether a TIMESTAMP comes back tz-aware."""
    aware = canonical_json({"t": datetime(2026, 9, 7, 11, 30, tzinfo=UTC)})
    naive = canonical_json({"t": datetime(2026, 9, 7, 11, 30)})
    assert aware == naive


def test_the_same_instant_in_another_zone_hashes_the_same():
    ist = timezone(timedelta(hours=5, minutes=30))
    a = canonical_json({"t": datetime(2026, 9, 7, 17, 0, tzinfo=ist)})
    b = canonical_json({"t": datetime(2026, 9, 7, 11, 30, tzinfo=UTC)})
    assert a == b


def test_decimal_is_not_routed_through_a_float():
    """NUMERIC columns are exactly why Decimal exists.

    Through binary floating point the digest would depend on rounding, and
    `coverage` and the label dimensions are NUMERIC.
    """
    assert canonical_json({"c": Decimal("0.94")}) == b'{"c":"0.94"}'


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_are_refused(bad):
    """A division by a zero-pixel height produces `inf`.

    `json.dumps` would write a bare `NaN` token, which is not valid JSON — some
    parsers reject it, some coerce it, and `NaN != NaN` makes any later equality
    check on the record quietly untrue. Better to refuse the record than to
    write a legal fact nobody can re-read.
    """
    with pytest.raises(CanonicalisationError, match="non-finite"):
        canonical_json({"height_mm": bad})


def test_a_nested_non_finite_is_found():
    with pytest.raises(CanonicalisationError, match=r"declarations\[1\]"):
        canonical_json({"declarations": [{"h": 1.0}, {"h": float("inf")}]})


def test_sets_are_refused_rather_than_ordered_arbitrarily():
    with pytest.raises(CanonicalisationError, match="no defined order"):
        canonical_json({"fields": {"mrp", "net_quantity"}})


# ---------------------------------------------------------------------------
# The chain itself
# ---------------------------------------------------------------------------


def test_a_fresh_chain_verifies():
    report = verify_chain(_build(5))
    assert report.ok, report.summary()
    assert report.checked == 5
    assert "intact" in report.summary()


def test_genesis_carries_the_genesis_link():
    first = _build(1)[0]
    assert first.chain_seq == 0
    assert first.prev_sha256 == GENESIS_PREV


def test_each_record_points_at_the_one_before_it():
    records = _build(4)
    for earlier, later in pairwise(records):
        assert later.prev_sha256 == earlier.record_sha256
        assert later.chain_seq == earlier.chain_seq + 1


def test_hashing_a_record_twice_gives_the_same_digest():
    payload = _scan(3)
    once = record_hash(payload, chain_seq=3, prev_sha256=GENESIS_PREV)
    twice = record_hash(copy.deepcopy(payload), chain_seq=3, prev_sha256=GENESIS_PREV)
    assert once == twice


def test_position_is_part_of_the_identity():
    """The same content at a different position must hash differently."""
    payload = _scan(1)
    a = record_hash(payload, chain_seq=1, prev_sha256=GENESIS_PREV)
    b = record_hash(payload, chain_seq=2, prev_sha256=GENESIS_PREV)
    assert a != b


def test_the_link_is_inside_the_hash():
    """Not merely stored beside it.

    If `prev_sha256` were only a column, two records could be transposed and
    each would still hash correctly on its own — the chain would record an
    order it could not defend.
    """
    payload = _scan(1)
    a = record_hash(payload, chain_seq=1, prev_sha256="a" * 64)
    b = record_hash(payload, chain_seq=1, prev_sha256="b" * 64)
    assert a != b


def test_a_row_round_trips_without_re_deriving_its_hash():
    """`from_row` must preserve the stored digest, not recompute it.

    Recomputing would make every row verify by construction and the whole check
    would be theatre.
    """
    original = _build(1)[0]
    rebuilt = from_row(original.as_row())
    assert rebuilt.record_sha256 == original.record_sha256
    assert verify_chain([rebuilt]).ok


# ---------------------------------------------------------------------------
# M7's criterion: tampering is DETECTED. Four modes, four names.
# ---------------------------------------------------------------------------


def test_editing_a_measurement_is_detected():
    """The headline case: someone lowers a height to make a FAIL into a PASS."""
    rows = [record.as_row() for record in _build(5)]
    rows[2]["declaration_set"]["declarations"][0]["height_mm"] = 2.40

    report = verify_chain(rows)
    assert not report.ok
    failure = report.first_failure
    assert failure is not None
    assert failure.kind == "CONTENT_ALTERED"
    assert failure.chain_seq == 2
    assert failure.scan_id == str(UUID(int=2))


def test_swapping_the_evidence_photo_is_detected():
    """Section 6: the image hash lives inside the chain.

    No image byte is in the database, and replacing the stored photograph is
    still detectable — because `image_sha256` is hashed with the record.
    """
    rows = [record.as_row() for record in _build(3)]
    rows[1]["image_sha256"] = "f" * 64

    report = verify_chain(rows)
    assert not report.ok
    assert report.first_failure.kind == "CONTENT_ALTERED"


def test_altering_the_rulepack_version_is_detected():
    """Reproducibility is evidence too.

    Rewriting which rulepack produced a verdict would let a finding be
    re-attributed to a rule version that never judged it.
    """
    rows = [record.as_row() for record in _build(3)]
    rows[0]["rulepack_version"] = "lmpc_2011@2099.99"
    assert not verify_chain(rows).ok


def test_deleting_a_record_from_the_middle_is_detected():
    """A pure digest check would report the survivors as fine."""
    rows = [record.as_row() for record in _build(5)]
    del rows[2]

    report = verify_chain(rows)
    assert not report.ok
    kinds = {failure.kind for failure in report.failures}
    assert "SEQUENCE_GAP" in kinds
    assert "BROKEN_LINK" in kinds


def test_deleting_the_first_record_is_detected():
    """Deletions at the front are the easiest to miss."""
    rows = [record.as_row() for record in _build(4)]
    del rows[0]

    report = verify_chain(rows)
    assert not report.ok
    assert report.first_failure.kind == "SEQUENCE_GAP"
    assert "missing from the front" in report.first_failure.detail


def test_transposing_two_records_is_detected():
    """Both records hash correctly in isolation. Only the links disagree."""
    rows = [record.as_row() for record in _build(5)]
    rows[1]["chain_seq"], rows[2]["chain_seq"] = rows[2]["chain_seq"], rows[1]["chain_seq"]

    report = verify_chain(rows)
    assert not report.ok
    assert any(failure.kind == "BROKEN_LINK" for failure in report.failures)


def test_a_forged_genesis_is_detected():
    rows = [record.as_row() for record in _build(3)]
    rows[0]["prev_sha256"] = "9" * 64

    report = verify_chain(rows)
    assert not report.ok
    kinds = {failure.kind for failure in report.failures}
    assert "BAD_GENESIS" in kinds or "CONTENT_ALTERED" in kinds


def test_a_duplicate_sequence_number_is_detected():
    """Two appends that raced and both read the same tail."""
    rows = [record.as_row() for record in _build(4)]
    rows[2]["chain_seq"] = rows[1]["chain_seq"]

    report = verify_chain(rows)
    assert not report.ok
    assert any(failure.kind == "SEQUENCE_GAP" for failure in report.failures)


def test_a_column_added_after_hashing_is_detected():
    """The bug this test was written for, and it was a real one.

    `InMemoryScanStore.save` stamped `synced_at` onto the row *after* `append()`
    had hashed it, so every stored record carried a field its digest had never
    seen and `verify_chain` reported CONTENT_ALTERED on records nobody had
    touched.

    That is the failure mode `evidence/chain.py` names as worse than having no
    chain at all — "a false alarm teaches people to ignore the alarm" — and
    here it would have taught a department to ignore an evidence-tampering
    warning. The fix is an invariant rather than an exclusion list:
    **everything in a stored row is inside its hash.**
    """
    rows = [record.as_row() for record in _build(2)]
    rows[0]["synced_at"] = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)

    report = verify_chain(rows)
    assert not report.ok
    assert report.first_failure.kind == "CONTENT_ALTERED"


def test_verification_reports_every_problem_not_just_the_first():
    """A department needs to know the extent, not merely that something is wrong."""
    rows = [record.as_row() for record in _build(6)]
    rows[1]["district"] = "Cuttack"
    rows[4]["latency_ms"] = 1
    report = verify_chain(rows)
    altered = [f for f in report.failures if f.kind == "CONTENT_ALTERED"]
    assert {failure.chain_seq for failure in altered} == {1, 4}


def test_records_out_of_order_still_verify():
    """A query with no ORDER BY must not look like tampering."""
    records = _build(5)
    shuffled = [records[3], records[0], records[4], records[1], records[2]]
    assert verify_chain(shuffled).ok


def test_a_middle_slice_verifies_when_told_it_is_one():
    """Paging through a long chain must not report a false deletion."""
    records = _build(8)
    window = records[3:6]
    assert not verify_chain(window).ok, "a fragment must not silently pass by default"
    assert verify_chain(window, expect_genesis=False).ok


def test_an_empty_chain_is_not_a_failure():
    report = verify_chain([])
    assert report.ok
    assert report.checked == 0


# ---------------------------------------------------------------------------
# The honest limit — worth a test so nobody overclaims it
# ---------------------------------------------------------------------------


def test_a_wholesale_rewrite_verifies_which_is_why_the_head_is_published():
    """Tamper-EVIDENT, not tamper-proof, and we say so.

    An actor with full write access can rewrite a record and re-chain every
    record after it. The result verifies cleanly, and no local check can say
    otherwise. What catches it is that the head digest was published elsewhere
    before the rewrite — so this test asserts the limit AND the mitigation.
    """
    honest = _build(5)
    published = head_digest(honest)

    tampered = []
    previous = None
    for index in range(5):
        payload = _scan(index)
        if index == 2:
            payload["declaration_set"]["declarations"][0]["height_mm"] = 2.40
        previous = append(payload, previous=previous)
        tampered.append(previous)

    # The rewritten chain is internally consistent. This is the limit.
    assert verify_chain(tampered).ok

    # But it cannot match a digest that was published before the rewrite.
    assert head_digest(tampered) != published


# ---------------------------------------------------------------------------
# Float precision — the chain's quietest failure mode
# ---------------------------------------------------------------------------


def test_a_coverage_figure_survives_the_numeric_column_it_is_stored_in():
    """`scans.coverage` is a Postgres NUMERIC, and the chain re-hashes what it
    reads back out of it.

    A Python float carrying seventeen significant digits does not survive that
    round trip — 0.9722222222222222 comes back 0.972222222222222 — and the
    recomputed digest then differs from the stored one. `verify_chain` reports
    CONTENT_ALTERED on a record nobody edited, which is the one alarm here that
    must never cry wolf.

    Found on 2026-09-10, latent since the column existed: a single frame's
    coverage is one ratio and often round-trips, but a multi-frame union's is
    the MEAN over several and needs the full seventeen digits almost every time.

    This asserts the invariant without a database, by applying the same
    narrowing Postgres does on the way in (float8 -> numeric keeps the shortest
    representation at fifteen significant digits).
    """
    from api.scanning import CHAIN_SAFE_DP

    def through_numeric(value: float) -> float:
        return float(f"{value:.15g}")

    assert through_numeric(0.9722222222222222) != 0.9722222222222222  # the bug
    for raw in (
        0.9722222222222222,  # 35/36, the mean that found this
        1 / 3,
        2 / 3,
        0.10000000000000009,
        1.0,
        0.0,
    ):
        rounded = round(raw, CHAIN_SAFE_DP)
        assert through_numeric(rounded) == rounded, raw
