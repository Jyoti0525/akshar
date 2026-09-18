"""The API layer — AKSHAR.md sections 5, 12, 18.

No Postgres, no Redis, no MinIO. The stores are Protocol-typed dependencies, so
the whole surface is exercised against in-memory implementations that keep the
*same guarantees* the SQL ones must — chiefly idempotent sync and a gapless,
server-assigned chain sequence.

The tests are grouped by what would go wrong: an auth boundary that leaks, a
sync that duplicates, an audit trail that misses a read, a handler that decides
compliance for itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.config import Settings
from api.deps import (
    get_audit_log,
    get_review_store,
    get_scan_store,
    get_sku_store,
    get_user_store,
)
from api.main import app
from api.repository import (
    InMemoryAuditLog,
    InMemoryReviewStore,
    InMemoryScanStore,
    InMemorySkuStore,
    InMemoryUserStore,
    SkuRecord,
    UserRecord,
)
from api.security import create_token, hash_password

SETTINGS = Settings(jwt_secret="test-secret-not-the-default", environment="development")

OFFICER = UserRecord(
    id=uuid4(),
    email="officer@akshar.test",
    full_name="R Mohanty",
    password_hash=hash_password("correct horse"),
    role="officer",
    district="Khordha",
)
SUPERVISOR = UserRecord(
    id=uuid4(),
    email="super@akshar.test",
    full_name="S Patnaik",
    password_hash=hash_password("also correct"),
    role="supervisor",
    district="Khordha",
)
RETIRED = UserRecord(
    id=uuid4(),
    email="gone@akshar.test",
    full_name="Ex Officer",
    password_hash=hash_password("whatever"),
    role="officer",
    is_active=False,
)


@pytest.fixture
def stores():
    scans, users, skus, audit, reviews = (
        InMemoryScanStore(),
        InMemoryUserStore(),
        InMemorySkuStore(),
        InMemoryAuditLog(),
        InMemoryReviewStore(),
    )
    for user in (OFFICER, SUPERVISOR, RETIRED):
        users.add(user)
    skus.add(
        SkuRecord(
            id=uuid4(),
            brand="Parle",
            brand_group="Parle Products",
            variant="G",
            pack_size="100 g",
            category="biscuits",
            barcode="8901030865275",
            phash="ffffffffffffffff",
            scan_count=412,
        )
    )
    skus.add(
        SkuRecord(
            id=uuid4(),
            brand="Britannia",
            variant="Marie",
            pack_size="250 g",
            category="biscuits",
            barcode="4006381333931",
            phash="0000000000000000",
            scan_count=17,
        )
    )
    return scans, users, skus, audit, reviews


@pytest.fixture
def client(stores):
    scans, users, skus, audit, reviews = stores
    from api.config import get_settings

    app.dependency_overrides[get_scan_store] = lambda: scans
    app.dependency_overrides[get_user_store] = lambda: users
    app.dependency_overrides[get_sku_store] = lambda: skus
    app.dependency_overrides[get_audit_log] = lambda: audit
    app.dependency_overrides[get_review_store] = lambda: reviews
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _auth(user: UserRecord = OFFICER) -> dict[str, str]:
    token = create_token(subject=user.id, role=user.role, settings=SETTINGS)  # type: ignore[arg-type]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_login_returns_a_token_pair(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "officer@akshar.test", "password": "correct horse"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "officer"
    assert body["access_token"] and body["refresh_token"]
    assert body["access_token"] != body["refresh_token"]


def test_an_unknown_email_and_a_wrong_password_are_indistinguishable(client):
    """Otherwise the login form is an account-enumeration oracle."""
    unknown = client.post(
        "/api/v1/auth/login", json={"email": "nobody@akshar.test", "password": "x"}
    )
    wrong = client.post(
        "/api/v1/auth/login", json={"email": "officer@akshar.test", "password": "x"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_a_deactivated_account_cannot_log_in(client):
    response = client.post(
        "/api/v1/auth/login", json={"email": "gone@akshar.test", "password": "whatever"}
    )
    assert response.status_code == 401


def test_a_deactivated_account_cannot_use_an_old_token(client):
    """A token issued before deactivation must stop working immediately.

    The user is re-read from the store on every request rather than trusted from
    the claim, because a signed token cannot know it has been revoked.
    """
    response = client.get("/api/v1/auth/me", headers=_auth(RETIRED))
    assert response.status_code == 401


def test_a_refresh_token_is_not_a_bearer_credential(client):
    """The `typ` claim, and why it is checked on every decode.

    A refresh token lives 14 days. If it were accepted as an access token, one
    leaked from a browser would be a fortnight of access to enforcement
    evidence.
    """
    refresh = create_token(
        subject=OFFICER.id, role="officer", token_type="refresh", settings=SETTINGS
    )
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh}"})
    assert response.status_code == 401
    assert "access" in response.json()["detail"]


def test_an_access_token_cannot_be_refreshed_with(client):
    access = create_token(subject=OFFICER.id, role="officer", settings=SETTINGS)
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert response.status_code == 401


def test_a_token_signed_with_another_key_is_rejected(client):
    forged = create_token(
        subject=OFFICER.id,
        role="admin",
        settings=Settings(jwt_secret="a-different-secret"),
    )
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_an_expired_token_is_rejected(client):
    expired = Settings(jwt_secret=SETTINGS.jwt_secret, access_token_minutes=-1)
    token = create_token(subject=OFFICER.id, role="officer", settings=expired)
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_a_missing_header_says_what_to_send(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert "Bearer" in response.json()["detail"]


def test_roles_nest_so_a_supervisor_reaches_a_supervisor_route(client):
    assert client.get("/api/v1/chain/status", headers=_auth(SUPERVISOR)).status_code == 200


def test_an_officer_cannot_reach_a_supervisor_route(client):
    response = client.get("/api/v1/chain/status", headers=_auth(OFFICER))
    assert response.status_code == 403
    assert "supervisor" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Sync — the guarantee section 5 makes by name
# ---------------------------------------------------------------------------


def _sync_item(scan_id=None, **overrides):
    item = {
        "id": str(scan_id or uuid4()),
        "source": "photo",
        "degradation_tier": "L1",
        "declaration_set": {"declarations": [], "coverage": 0.0},
        "coverage": 0.9,
        "latency_ms": 561,
        "cache_hit": False,
        "image_key": "2026/09/07/a.jpg",
        "image_sha256": "a" * 64,
        "captured_at": datetime.now(UTC).isoformat(),
        "model_versions": {"detector": "rtmdet-ins-tiny@int8"},
        "rulepack_version": "lmpc_2011@2026.03",
    }
    item.update(overrides)
    return item


def test_replaying_the_outbox_never_duplicates_a_record(client):
    """Section 5, stated as a guarantee rather than an aspiration.

    An officer's phone regains signal halfway through an upload and retries the
    whole batch. Everything already delivered comes back `created=False`.
    """
    batch = [_sync_item() for _ in range(3)]

    first = client.post("/api/v1/scans/sync", json={"scans": batch}, headers=_auth())
    assert first.status_code == 200
    assert first.json()["created"] == 3
    assert first.json()["duplicates"] == 0

    second = client.post("/api/v1/scans/sync", json={"scans": batch}, headers=_auth())
    assert second.json()["created"] == 0
    assert second.json()["duplicates"] == 3


def test_a_retry_does_not_append_a_second_chain_entry(client, stores):
    """The subtle half, and the one a naive idempotency check would miss.

    Returning "already have it" while still appending a chain row would break
    the sequence's gaplessness for a client whose only mistake was losing
    signal — and `verify_chain` would then report a `SEQUENCE_GAP` that nobody
    caused.
    """
    scans, *_ = stores
    batch = [_sync_item() for _ in range(2)]

    client.post("/api/v1/scans/sync", json={"scans": batch}, headers=_auth())
    client.post("/api/v1/scans/sync", json={"scans": batch}, headers=_auth())

    records = scans.all_records()
    assert len(records) == 2
    assert [record.chain_seq for record in records] == [0, 1]


def test_the_chain_stays_verifiable_across_a_partial_replay(client):
    """A realistic outbox: some delivered, signal lost, batch resent with more."""
    first_two = [_sync_item() for _ in range(2)]
    client.post("/api/v1/scans/sync", json={"scans": first_two}, headers=_auth())

    resent = [*first_two, _sync_item(), _sync_item()]
    response = client.post("/api/v1/scans/sync", json={"scans": resent}, headers=_auth())
    assert response.json() == {
        **response.json(),
        "accepted": 4,
        "created": 2,
        "duplicates": 2,
    }

    status = client.get("/api/v1/chain/status", headers=_auth(SUPERVISOR)).json()
    assert status["ok"], status["failures"]
    assert status["checked"] == 4

    # An unanchored chain never reports success. `ok` above says the chain is
    # internally consistent, which a wholesale rewrite also says; a green tick
    # beside an empty anchor log would tell a supervisor they hold corroboration
    # they do not hold. See `evidence/anchor.py`.
    assert status["anchor_status"] == "unanchored"
    assert status["anchors"] == 0


def test_the_anchor_status_turns_green_only_once_something_is_anchored(
    client, stores, tmp_path, monkeypatch
):
    """`GET /chain/status` reports the anchor log, not just the chain.

    Two states that a boolean would have merged: nothing published yet, and
    everything published still agreeing.
    """
    import evidence.anchor as anchor_module
    from api.routers import ops

    log = tmp_path / "anchors.jsonl"
    monkeypatch.setattr(ops, "anchor_path", lambda: log)

    scans, *_ = stores
    client.post(
        "/api/v1/scans/listing", json={"text": "MRP Rs 45. Net 100 g."}, headers=_auth(OFFICER)
    )

    before = client.get("/api/v1/chain/status", headers=_auth(SUPERVISOR)).json()
    assert before["anchor_status"] == "unanchored"

    assert anchor_module.append_anchor(log, scans.all_records()) is not None

    after = client.get("/api/v1/chain/status", headers=_auth(SUPERVISOR)).json()
    assert after["anchor_status"] == "ok"
    assert after["anchors"] == 1
    assert after["anchors_checked"] == 1
    assert after["anchor_failures"] == []


def test_an_unreadable_anchor_log_is_reported_rather_than_swallowed(client, tmp_path, monkeypatch):
    """ "We cannot tell" and "the chain disagrees" are different answers.

    A corrupt or truncated anchor file is indistinguishable, from the endpoint,
    from one somebody removed on purpose — so it is surfaced under its own
    status rather than folded into `failed` or quietly ignored.
    """
    from api.routers import ops

    log = tmp_path / "anchors.jsonl"
    log.write_text("this is not an anchor\n", encoding="utf-8")
    monkeypatch.setattr(ops, "anchor_path", lambda: log)

    status = client.get("/api/v1/chain/status", headers=_auth(SUPERVISOR)).json()
    assert status["anchor_status"] == "unreadable"
    assert status["anchor_failures"]
    # The chain itself is a separate question and is still answered.
    assert status["ok"] is True


def test_chain_seq_is_assigned_server_side_not_by_the_client(client, stores):
    """Section 5: "offline clients cannot possibly agree on ordering."

    A client sending its own sequence must not be able to influence the chain.
    """
    scans, *_ = stores
    client.post(
        "/api/v1/scans/sync",
        json={"scans": [_sync_item(), _sync_item()]},
        headers=_auth(),
    )
    assert [record.chain_seq for record in scans.all_records()] == [0, 1]


def test_geolocation_is_reduced_before_it_is_ever_stored(client, stores):
    """Section 18: enough to identify a market, not a doorway.

    Truncated on the way in rather than at display time — a coarse value that
    was never stored precisely cannot be recovered from a backup.
    """
    scans, *_ = stores
    scan_id = uuid4()
    client.post(
        "/api/v1/scans/sync",
        json={"scans": [_sync_item(scan_id, geo={"lat": 20.2961234, "lon": 85.8245678})]},
        headers=_auth(),
    )
    stored = scans.get(scan_id)
    assert stored["geo"] == {"lat": 20.296, "lon": 85.825}


def test_sync_requires_authentication(client):
    assert client.post("/api/v1/scans/sync", json={"scans": []}).status_code == 401


# ---------------------------------------------------------------------------
# The listing channel — three inputs, one engine
# ---------------------------------------------------------------------------


def test_a_listing_with_no_image_still_produces_verdicts(client):
    """Section 3's third channel, end to end over HTTP.

    Every geometric rule must abstain rather than fail: there are no pixels, and
    "absence of evidence is not evidence of a violation".
    """
    listing = (
        "Parle-G Original Gluco Biscuits 250 g. "
        "MRP Rs. 45.00 (inclusive of all taxes). "
        "Net wt. 250 g. Manufactured by: Parle Products Pvt Ltd, Mumbai 400056. "
        "Consumer care: care@parle.test, 1800 123 4567. Mfg 03/2026."
    )
    response = client.post(
        "/api/v1/scans/listing",
        json={"text": listing, "category": "biscuits"},
        headers=_auth(),
    )
    assert response.status_code == 200
    body = response.json()

    assert body["source"] == "listing_text"
    assert body["verdicts"], "the engine produced nothing"

    geometric = [
        verdict
        for verdict in body["verdicts"]
        if verdict["rule_id"]
        in {
            "LMPC.MRP.NUMERAL_HEIGHT",
            "LMPC.NETQTY.NUMERAL_HEIGHT",
            "LMPC.LETTER.MIN_HEIGHT",
        }
    ]
    assert geometric, "the height rules did not run at all"
    for verdict in geometric:
        assert verdict["status"] in {"NO_DATA", "NOT_APPLICABLE"}, (
            f"{verdict['rule_id']} returned {verdict['status']} with no pixels; "
            f"absence of evidence is not evidence of a violation"
        )


def test_a_listing_scan_is_chained_like_any_other(client):
    response = client.post("/api/v1/scans/listing", json={"text": "MRP Rs. 45.00"}, headers=_auth())
    body = response.json()
    assert body["record_sha256"] and body["chain_seq"] == 0


def test_the_report_is_not_awaited(client):
    """Section 8c: a PDF takes 300-800 ms and must never sit in front of an officer."""
    response = client.post("/api/v1/scans/listing", json={"text": "MRP Rs. 45.00"}, headers=_auth())
    assert response.json()["report_status"] == "queued"


def test_the_scan_screen_gets_the_three_figures_it_must_show(client):
    """Section 11: latency, scale tier and coverage are always visible."""
    body = client.post(
        "/api/v1/scans/listing", json={"text": "MRP Rs. 45.00"}, headers=_auth()
    ).json()
    assert "latency_ms" in body
    assert "coverage" in body
    assert body["degradation_tier"].startswith("L")


# ---------------------------------------------------------------------------
# SKU cache — exit zero as HTTP
# ---------------------------------------------------------------------------


def test_barcode_lookup_hits(client):
    response = client.get(
        "/api/v1/skus/lookup", params={"barcode": "8901030865275"}, headers=_auth()
    )
    body = response.json()
    assert body["hit"] and body["matched_on"] == "barcode"
    assert body["sku"]["brand"] == "Parle"


def test_phash_lookup_tolerates_lighting_variation(client):
    """Hamming <= 8, not exact match.

    Two photographs of the same pack under different shop lighting differ by a
    few bits, and the entire cache argument rests on recognising that as one
    SKU.
    """
    near = "fffffffffffffff0"  # 4 bits from the stored hash
    body = client.get("/api/v1/skus/lookup", params={"phash": near}, headers=_auth()).json()
    assert body["hit"] and body["matched_on"] == "phash"


def test_a_distant_phash_is_a_miss(client):
    body = client.get(
        "/api/v1/skus/lookup", params={"phash": "0f0f0f0f0f0f0f0f"}, headers=_auth()
    ).json()
    assert not body["hit"]


def test_cache_warming_is_ordered_by_scan_count(client):
    """The long tail is why a few megabytes covers most of a shelf."""
    body = client.get("/api/v1/skus/cache", params={"n": 10}, headers=_auth()).json()
    counts = [sku["scan_count"] for sku in body["skus"]]
    assert counts == sorted(counts, reverse=True)


# ---------------------------------------------------------------------------
# Audit — who looked, not merely who could
# ---------------------------------------------------------------------------


def test_reading_a_scan_is_logged(client, stores):
    """Section 18: "who looked at a pending case is exactly the question that
    eventually gets asked"."""
    _scans, _users, _skus, audit, _reviews = stores
    scan_id = uuid4()
    client.post("/api/v1/scans/sync", json={"scans": [_sync_item(scan_id)]}, headers=_auth())

    client.get(f"/api/v1/scans/{scan_id}", headers=_auth())

    views = [entry for entry in audit.entries() if entry["action"] == "view"]
    assert len(views) == 1
    assert views[0]["entity_id"] == str(scan_id)
    assert views[0]["user_id"] == OFFICER.id


def test_a_failed_login_is_logged(client, stores):
    *_, audit, _reviews = stores
    client.post("/api/v1/auth/login", json={"email": "officer@akshar.test", "password": "no"})
    assert any(entry["action"] == "login_failed" for entry in audit.entries())


def test_a_correction_is_appended_and_the_scan_is_untouched(client, stores):
    """Section 5: "Corrections are append-only rows, never edits."

    That is also the answer to "what is your merge strategy" — there is nothing
    to merge.
    """
    scans, _users, _skus, audit, _reviews = stores
    scan_id = uuid4()
    client.post("/api/v1/scans/sync", json={"scans": [_sync_item(scan_id)]}, headers=_auth())
    before = dict(scans.get(scan_id))

    response = client.post(
        f"/api/v1/scans/{scan_id}/corrections",
        json={"box_index": 2, "from_field": "mfg_date", "to_field": "manufacturer"},
        headers=_auth(),
    )
    assert response.status_code == 201
    assert scans.get(scan_id) == before, "the scan record was modified"
    assert any(entry["action"] == "correct" for entry in audit.entries())


def test_a_correction_on_an_unknown_scan_is_404(client):
    response = client.post(
        f"/api/v1/scans/{uuid4()}/corrections",
        json={"to_field": "manufacturer"},
        headers=_auth(),
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Reports — the three formats the route actually returns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "magic", "content_type"),
    [
        ("html", b"<!DOC", "text/html"),
        ("docx", b"PK", "officedocument"),
        ("pdf", b"%PDF-", "application/pdf"),
    ],
)
def test_every_report_format_returns_that_format(client, fmt, magic, content_type):
    """The scan page offers these as `<a download="scan-<id>.pdf">`.

    A browser following a `download` link saves whatever comes back under that
    name, whatever the status code or content type. So a route that answers
    `202 {"status": "rendering"}` — which the PDF branch did whenever no worker
    had rendered one, and the demonstration stack has no worker — put thirty
    bytes of JSON on the officer's disk called `scan-<id>.pdf`, and no viewer
    would open it. The 503 from a host without WeasyPrint's native libraries did
    the same.

    Asserting the magic bytes rather than the status is deliberate: 200 with a
    JSON body would pass a status check and still be the bug.
    """
    scan_id = uuid4()
    client.post("/api/v1/scans/sync", json={"scans": [_sync_item(scan_id)]}, headers=_auth())

    response = client.get(f"/api/v1/scans/{scan_id}/report?format={fmt}", headers=_auth())

    assert response.status_code == 200, response.text[:200]
    assert content_type in response.headers["content-type"]
    assert response.content[:5].startswith(magic[:5]), (
        f"{fmt} route returned {response.content[:40]!r}"
    )
    assert len(response.content) > 500


# ---------------------------------------------------------------------------
# Review resolution — section 8b, section 11 Q6
# ---------------------------------------------------------------------------

REVIEW_VERDICT = {
    "rule_id": "r7_2_mrp_height",
    "rule_ref": "Rule 7(2), Table I",
    "status": "REVIEW",
    "severity": "high",
    "message": "1.96 mm against a 2.00 mm minimum, inside tolerance.",
}
SECOND_REVIEW = {
    "rule_id": "r6_1_e_mrp_present",
    "rule_ref": "Rule 6(1)(e)",
    "status": "REVIEW",
    "severity": "medium",
    "message": "A price was read but no label beside it.",
}


def _scan_awaiting_review(client, scans, *verdicts):
    scan_id = uuid4()
    client.post("/api/v1/scans/sync", json={"scans": [_sync_item(scan_id)]}, headers=_auth())
    scans.save_verdicts(scan_id, verdicts or (REVIEW_VERDICT,))
    return scan_id


def test_resolving_a_review_records_it_and_leaves_the_scan_untouched(client, stores):
    """Section 5's immutability rule, applied to the write that most invites breaking it.

    The temptation is to set the verdict to PASS. That verdict is inside the
    record whose SHA-256 is in the evidence chain, so rewriting it would make
    `verify_chain` fail at that row — and it would be right to.
    """
    scans, _users, _skus, audit, reviews = stores
    scan_id = _scan_awaiting_review(client, scans)
    before = dict(scans.get(scan_id))

    response = client.post(
        f"/api/v1/scans/{scan_id}/review",
        json={"rule_id": "r7_2_mrp_height", "decision": "complies", "note": "re-measured flat"},
        headers=_auth(SUPERVISOR),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["decision"] == "complies"
    assert body["outstanding"] == [], "the only rule awaiting a human was just answered"

    assert scans.get(scan_id) == before, "the scan record was modified"
    assert [v["status"] for v in scans.verdicts_for(scan_id)] == ["REVIEW"], (
        "the verdict itself must still say REVIEW; the resolution is a separate row"
    )
    assert len(reviews.resolutions_for(scan_id)) == 1
    assert any(entry["action"] == "resolve_review" for entry in audit.entries())


def test_a_partly_resolved_scan_stays_in_the_queue_with_the_rest_of_its_rules(client, stores):
    """The failure mode this guards is losing work silently.

    Two rules asked for a human. Answering one must not clear the scan, or the
    second question disappears from the only list that was tracking it.
    """
    scans, *_ = stores
    scan_id = _scan_awaiting_review(client, scans, REVIEW_VERDICT, SECOND_REVIEW)

    first = client.post(
        f"/api/v1/scans/{scan_id}/review",
        json={"rule_id": "r7_2_mrp_height", "decision": "does_not_comply"},
        headers=_auth(SUPERVISOR),
    )
    assert first.json()["outstanding"] == ["r6_1_e_mrp_present"]

    queue = client.get("/api/v1/dashboard/review", headers=_auth(SUPERVISOR)).json()
    row = next(r for r in queue["rows"] if r["scan_id"] == str(scan_id))
    assert row["rules"] == ["r6_1_e_mrp_present"], "the settled rule must not still be listed"

    client.post(
        f"/api/v1/scans/{scan_id}/review",
        json={"rule_id": "r6_1_e_mrp_present", "decision": "recapture"},
        headers=_auth(SUPERVISOR),
    )
    queue = client.get("/api/v1/dashboard/review", headers=_auth(SUPERVISOR)).json()
    assert not any(r["scan_id"] == str(scan_id) for r in queue["rows"]), (
        "a scan with every review rule answered must leave the queue"
    )


def test_the_overview_tile_agrees_with_the_queue_beneath_it(client, stores):
    """A tile reading "1 awaiting review" above an empty list is a bug report.

    They are computed in two different places, which is exactly how they drift.
    """
    scans, *_ = stores
    scan_id = _scan_awaiting_review(client, scans)

    before = client.get("/api/v1/dashboard/overview", headers=_auth(SUPERVISOR)).json()
    assert before["tiles"]["awaiting_review"]["value"] == 1
    assert len(before["review_queue"]) == 1

    client.post(
        f"/api/v1/scans/{scan_id}/review",
        json={"rule_id": "r7_2_mrp_height", "decision": "complies"},
        headers=_auth(SUPERVISOR),
    )

    after = client.get("/api/v1/dashboard/overview", headers=_auth(SUPERVISOR)).json()
    assert after["tiles"]["awaiting_review"]["value"] == 0
    assert after["review_queue"] == []


def test_resolving_a_rule_that_never_asked_for_review_is_a_conflict(client, stores):
    """409, not 201.

    Section 14's retraining feed is only worth anything if every row in it was
    prompted by a verdict a person actually saw.
    """
    scans, *_ = stores
    scan_id = _scan_awaiting_review(client, scans)

    response = client.post(
        f"/api/v1/scans/{scan_id}/review",
        json={"rule_id": "r9_1_country_of_origin", "decision": "complies"},
        headers=_auth(SUPERVISOR),
    )
    assert response.status_code == 409
    assert "r7_2_mrp_height" in response.json()["detail"]


def test_an_officer_may_correct_a_box_but_may_not_resolve_a_review(client, stores):
    """Two writes, two authority levels, and the difference is deliberate.

    Relabelling a box is a statement about what the photograph shows. Resolving
    a REVIEW is a compliance conclusion on an enforcement record where the
    rulepack declined to reach one, and section 11 puts that queue on the
    supervisor's dashboard.
    """
    scans, *_ = stores
    scan_id = _scan_awaiting_review(client, scans)

    correction = client.post(
        f"/api/v1/scans/{scan_id}/corrections",
        json={"box_index": 0, "to_field": "mrp"},
        headers=_auth(OFFICER),
    )
    assert correction.status_code == 201

    resolution = client.post(
        f"/api/v1/scans/{scan_id}/review",
        json={"rule_id": "r7_2_mrp_height", "decision": "complies"},
        headers=_auth(OFFICER),
    )
    assert resolution.status_code == 403


def test_a_correction_is_actually_stored_and_not_merely_acknowledged(client, stores):
    """It was not. The endpoint returned a 201 receipt and dropped the row.

    Section 14 rests the whole retraining argument on these being *"a labelled
    training example produced by somebody already doing the job"*, which is only
    true if one survives the request.
    """
    scans, _users, _skus, _audit, reviews = stores
    scan_id = _scan_awaiting_review(client, scans)

    client.post(
        f"/api/v1/scans/{scan_id}/corrections",
        json={"box_index": 4, "from_field": "marketing_text", "to_field": "mrp"},
        headers=_auth(),
    )

    stored = reviews.corrections_for(scan_id)
    assert len(stored) == 1
    assert (stored[0].box_index, stored[0].from_field, stored[0].to_field) == (
        4,
        "marketing_text",
        "mrp",
    )


def test_resolving_twice_is_idempotent_for_the_queue_and_additive_for_the_record(client, stores):
    """A supervisor revisiting a call writes a second row rather than editing the first.

    Section 5 again: nothing is updated in place. The queue only asks whether at
    least one resolution exists, so the repeat changes nothing there.
    """
    scans, _users, _skus, _audit, reviews = stores
    scan_id = _scan_awaiting_review(client, scans)
    payload = {"rule_id": "r7_2_mrp_height", "decision": "complies"}

    client.post(f"/api/v1/scans/{scan_id}/review", json=payload, headers=_auth(SUPERVISOR))
    second = client.post(
        f"/api/v1/scans/{scan_id}/review",
        json={**payload, "decision": "does_not_comply"},
        headers=_auth(SUPERVISOR),
    )

    assert second.status_code == 201
    assert len(reviews.resolutions_for(scan_id)) == 2, "the first decision must survive"
    assert [r.decision for r in reviews.resolutions_for(scan_id)] == [
        "complies",
        "does_not_comply",
    ]


def test_resolving_an_unknown_scan_is_404(client):
    response = client.post(
        f"/api/v1/scans/{uuid4()}/review",
        json={"rule_id": "r7_2_mrp_height", "decision": "complies"},
        headers=_auth(SUPERVISOR),
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Ops
# ---------------------------------------------------------------------------


def test_health_is_degraded_not_broken_when_models_are_absent(client):
    """Without weights the geometry path, the engine and the listing channel all
    still work. A 503 would take down a service that is in fact serving."""
    body = client.get("/healthz").json()
    assert body["status"] in {"ok", "degraded"}
    assert body["rules_loaded"] > 0
    if body["models_present"] < body["models_expected"]:
        assert body["status"] == "degraded"
        assert any("degrade" in line for line in body["detail"])


def test_the_rulepack_is_public(client):
    """40 KB of text, small enough to email — and nothing in it is not a gazette."""
    response = client.get("/api/v1/rules")
    assert response.status_code == 200
    body = response.json()
    assert body["rules"]
    assert all(rule["rule_ref"] for rule in body["rules"]), "a rule cites nothing"


def test_the_rulepack_does_not_claim_an_unverified_currency(client):
    body = client.get("/api/v1/rules").json()
    assert body["claims_currency"] is False
    assert body["amendments_unverified"]


def test_coop_and_coep_headers_are_set_on_every_response(client):
    """Section 15b: without these, in-browser WASM is single-threaded and the
    offline path roughly doubles in latency."""
    response = client.get("/healthz")
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert response.headers["cross-origin-embedder-policy"] == "require-corp"


def test_the_response_time_header_is_present(client):
    """Section 11 requires the latency figure on screen; the API supplies it."""
    response = client.get("/healthz")
    assert float(response.headers["x-response-time-ms"]) >= 0.0


def test_metrics_are_exposed(client):
    assert client.get("/metrics").status_code == 200


def test_openapi_schema_generates(client):
    """The frontend's TypeScript is generated from this, so it must not break."""
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "AKSHAR"
    assert "/api/v1/scans/sync" in schema["paths"]
