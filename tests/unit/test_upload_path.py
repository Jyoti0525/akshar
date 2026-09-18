"""The image upload path and the two queues — AKSHAR.md sections 4, 6, 8c, 12, 18.

Almost every test here is about something that happens *after* the response, or
about something that deliberately does **not** happen at all. That is the shape
of section 8c: "nothing delays the verdict" is a claim about work being moved,
and work that has been moved is invisible to a test that only reads the response
body.

The three properties worth stating before reading:

1.  **The digest in the chained row is over the bytes the worker will upload.**
    Redaction runs before hashing, so a stored row cannot describe an image
    nobody can reproduce. `store_evidence` re-checks it and refuses on mismatch.
2.  **Absence of verdicts is not compliance.** An L4 scan keeps its
    full-resolution original; a photograph of a countertop keeps nothing.
3.  **A face printed on a carton is not a bystander.** Blurring the Amul girl
    would remove label content, which is the evidence.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from uuid import UUID, uuid4

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.config import Settings, get_settings
from api.deps import (
    get_audit_log,
    get_bulk_jobs,
    get_enqueuer,
    get_object_store,
    get_scan_store,
    get_sku_store,
    get_spool,
    get_user_store,
)
from api.main import app
from api.repository import (
    BulkJob,
    InMemoryAuditLog,
    InMemoryBulkJobStore,
    InMemoryScanStore,
    InMemorySkuStore,
    InMemoryUserStore,
    SkuRecord,
    UserRecord,
)
from api.scanning import ScanRequest, run_scan
from api.security import create_token, hash_password
from contracts import Verdict
from evidence import redact, storage
from evidence.spool import InMemorySpool, RedisSpool
from tests.unit.synthetic import blank_label, draw_text, on_canvas, photograph
from workers import tasks
from workers.broker import QUEUE_BULK, QUEUE_SCAN, drain, get_broker
from workers.middleware import BulkFairShare

SETTINGS = Settings(jwt_secret="test-secret-not-the-default", environment="development")

OFFICER = UserRecord(
    id=uuid4(),
    email="officer@akshar.test",
    full_name="R Mohanty",
    password_hash=hash_password("correct horse"),
    role="officer",
    district="Khordha",
)
OTHER_OFFICER = UserRecord(
    id=uuid4(),
    email="other@akshar.test",
    full_name="P Sahu",
    password_hash=hash_password("also correct"),
    role="officer",
    district="Cuttack",
)
SUPERVISOR = UserRecord(
    id=uuid4(),
    email="super@akshar.test",
    full_name="S Patnaik",
    password_hash=hash_password("supervisory"),
    role="supervisor",
    district="Khordha",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _packet_jpeg() -> bytes:
    """A synthetic packet photograph. Proves the arithmetic, never the accuracy.

    `tests/unit/synthetic.py` draws at known pixel heights and warps by a known
    homography. It is a fixture, not training data — the real corpus lives in
    `data/corpus/` and `docs/corpus.md` says what it can and cannot be used for.
    """
    label = blank_label()
    draw_text(label, "MRP Rs. 45.00", baseline=(60, 120), cap_px=34)
    draw_text(label, "NET WT 250 g", baseline=(60, 230), cap_px=26)
    shot, _ = photograph(on_canvas(label), tilt=0.05, yaw=0.03)
    ok, buffer = cv2.imencode(".jpg", shot)
    assert ok
    return bytes(buffer.tobytes())


class FakeObjectStore:
    """Enough of MinIO to observe what was written, and nothing else."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.buckets: set[str] = set()

    def put_object(self, bucket_name, object_name, data, length, **kwargs):
        self.objects[(bucket_name, object_name)] = data.read()

    def get_object(self, bucket_name, object_name):
        return io.BytesIO(self.objects[(bucket_name, object_name)])

    def remove_object(self, bucket_name, object_name, **kwargs):
        self.objects.pop((bucket_name, object_name), None)

    def bucket_exists(self, bucket_name):
        return bucket_name in self.buckets

    def make_bucket(self, bucket_name, **kwargs):
        self.buckets.add(bucket_name)


class Recorder:
    """A queue that records instead of enqueueing."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict]] = []

    def __call__(self, task: str, *, queue: str, **kwargs) -> None:
        self.sent.append((task, queue, kwargs))

    def tasks(self) -> list[str]:
        return [name for name, _, _ in self.sent]


@pytest.fixture
def world():
    skus = InMemorySkuStore()
    scans = InMemoryScanStore(skus=skus)
    users = InMemoryUserStore()
    for user in (OFFICER, OTHER_OFFICER, SUPERVISOR):
        users.add(user)
    return {
        "scans": scans,
        "skus": skus,
        "users": users,
        "audit": InMemoryAuditLog(),
        "jobs": InMemoryBulkJobStore(),
        "spool": InMemorySpool(),
        "objects": FakeObjectStore(),
        "queue": Recorder(),
    }


@pytest.fixture
def client(world):
    app.dependency_overrides[get_scan_store] = lambda: world["scans"]
    app.dependency_overrides[get_sku_store] = lambda: world["skus"]
    app.dependency_overrides[get_user_store] = lambda: world["users"]
    app.dependency_overrides[get_audit_log] = lambda: world["audit"]
    app.dependency_overrides[get_bulk_jobs] = lambda: world["jobs"]
    app.dependency_overrides[get_spool] = lambda: world["spool"]
    app.dependency_overrides[get_object_store] = lambda: world["objects"]
    app.dependency_overrides[get_enqueuer] = lambda: world["queue"]
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _auth(user: UserRecord = OFFICER) -> dict[str, str]:
    token = create_token(subject=user.id, role=user.role, settings=SETTINGS)  # type: ignore[arg-type]
    return {"Authorization": f"Bearer {token}"}


PACK_HEIGHT_MM = 95.0
"""Every photo-channel upload carries one, because the route requires one.

Not a fixture detail — it is the point. `pack_height_mm` is what makes the
three `min_height_mm` rules answerable, and it has no default on the route
precisely so that a client cannot omit it and receive a report that quietly
checked 28 of 31 rules.
"""


def _upload(client, payload: bytes | None = None, **form):
    form.setdefault("pack_height_mm", PACK_HEIGHT_MM)
    return client.post(
        "/api/v1/scans",
        headers=_auth(),
        files={"image": ("packet.jpg", payload if payload is not None else _packet_jpeg(), "image/jpeg")},
        data=form,
    )


# ---------------------------------------------------------------------------
# Redaction — section 18, and the one case that would destroy the evidence
# ---------------------------------------------------------------------------


def _frame_with_detail() -> np.ndarray:
    rng = np.random.default_rng(7)
    frame = rng.integers(0, 255, size=(400, 400, 3), dtype=np.uint8)
    return np.ascontiguousarray(frame)


def test_a_face_printed_on_the_package_is_left_intact(monkeypatch):
    """Indian retail is full of printed faces. Blurring one removes label content.

    The Amul girl, a baby on a formula tin, a model on a shampoo sachet — a
    frontal-face cascade cannot tell those from a person, but geometry can: a
    printed face is inside the package box and a bystander is not.
    """
    frame = _frame_with_detail()
    monkeypatch.setattr(redact, "find_faces", lambda _: [(100, 100, 80, 80)])
    monkeypatch.setattr(redact, "_load_cascade", lambda: object())

    result = redact.redact_faces(frame, package_box=(50, 50, 300, 300))

    assert result.blurred == 0
    assert result.skipped_on_package == 1
    assert result.image is frame, "the array must not even be copied when nothing changed"


def test_a_bystander_behind_the_packet_is_destroyed_not_softened(monkeypatch):
    """Blur alone is invertible in principle; the mosaic is a real discard."""
    frame = _frame_with_detail()
    box = (10, 10, 80, 80)
    monkeypatch.setattr(redact, "find_faces", lambda _: [box])
    monkeypatch.setattr(redact, "_load_cascade", lambda: object())

    before = float(frame[10:90, 10:90].var())
    result = redact.redact_faces(frame, package_box=(200, 200, 100, 100))
    after = float(result.image[10:90, 10:90].var())

    assert result.blurred == 1
    assert after < before / 4, f"region variance only fell from {before:.0f} to {after:.0f}"
    assert frame[10:90, 10:90].var() == pytest.approx(before), "the caller's array was mutated"


def test_no_image_is_stored_when_redaction_cannot_run(monkeypatch):
    """Fail closed on privacy, and open on the record. Sections 18 and 5.

    A missing cascade must not put an unredacted bystander into a bucket with a
    seven-year governance lock. It must also not stop the inspection being
    recorded — the scan row, its timestamp and its verdicts are written either
    way, because L4's promise is about the *record*, not the photograph.
    """
    monkeypatch.setattr(redact, "_load_cascade", lambda: None)
    plan = storage.plan_for([], is_repeat_sku=False)

    payload, decision = redact_via_plan(plan, blur_faces=True)

    assert payload is None
    assert decision.stored is False
    assert "section 18" in decision.reason


def redact_via_plan(plan, *, blur_faces: bool):
    from api.scanning import prepare_evidence

    return prepare_evidence(
        _frame_with_detail(),
        scan_id=uuid4(),
        captured_at=datetime.now(UTC),
        plan=plan,
        package_box=None,
        blur_faces=blur_faces,
    )


def test_a_non_image_upload_is_rejected_rather_than_degraded():
    """Section 5's ladder is about photographs we cannot read, not about a PDF."""
    with pytest.raises(ValueError, match="not a decodable image"):
        redact.decode_image(b"%PDF-1.7 this is not a photograph")


# ---------------------------------------------------------------------------
# Storage plan — absence of verdicts is not evidence of compliance
# ---------------------------------------------------------------------------


def test_an_unreadable_scan_keeps_its_original_because_the_photograph_is_the_record():
    """L4 produces no verdicts, which reads exactly like a clean pass.

    Filed as compliant it would be downscaled after 90 days, destroying the one
    artefact section 5 says an L4 record exists to preserve.
    """
    plan = storage.plan_for([], is_repeat_sku=False, conclusive=False)

    assert plan.upload_original
    assert plan.tier == "evidence_original"
    assert storage.RETENTION_DAYS[plan.tier] == 365 * 7


def test_a_frame_with_no_package_stores_nothing():
    """Exit one. There is no package, so there is nothing to evidence."""
    plan = storage.plan_for([], is_repeat_sku=False, has_package=False)

    assert not plan.uploads_anything
    assert plan.tier is None


def test_a_conclusive_pass_is_still_only_kept_for_a_year():
    plan = storage.plan_for(
        [
            Verdict(
                rule_id="LMPC.MRP.PRESENT",
                rule_ref="Rule 6(1)(e)",
                status="PASS",
                severity="high",
                expected="an MRP declaration",
                message="MRP declared.",
            )
        ],
        is_repeat_sku=False,
    )
    assert plan.tier == "compliant_downscaled"


# ---------------------------------------------------------------------------
# The spool — where the bytes wait
# ---------------------------------------------------------------------------


def test_the_spool_delivers_its_bytes_exactly_once():
    """Two workers racing must not both upload into a write-once bucket."""
    spool = InMemorySpool()
    assert spool.put("scan-1", b"pixels")

    assert spool.take("scan-1") == b"pixels"
    assert spool.take("scan-1") is None


def test_a_spool_that_cannot_accept_bytes_says_so_rather_than_raising():
    spool = InMemorySpool(max_bytes=10)
    assert spool.put("big", b"x" * 100) is False
    assert len(spool) == 0


def test_a_redis_outage_is_a_false_put_not_an_exception():
    """The caller then uploads inline. An evidence path that fails when the
    queue fails is not an evidence path."""

    class DeadRedis:
        def set(self, *args, **kwargs):
            raise ConnectionError("redis is down")

        def getdel(self, *args, **kwargs):
            raise ConnectionError("redis is down")

    spool = RedisSpool(client=DeadRedis())
    assert spool.put("scan-1", b"pixels") is False
    assert spool.take("scan-1") is None


# ---------------------------------------------------------------------------
# Queue weighting — section 8c's "one overnight bulk job"
# ---------------------------------------------------------------------------


class _Msg:
    def __init__(self, queue_name: str, message_id: str = "m1") -> None:
        self.queue_name = queue_name
        self.message_id = message_id
        self.options: dict = {}

    def copy(self, **_):
        return self


class _Broker:
    def __init__(self) -> None:
        self.requeued: list[tuple[object, int]] = []

    def enqueue(self, message, *, delay=None):
        self.requeued.append((message, delay))


def test_bulk_is_capped_at_a_share_of_the_pool_not_the_whole_of_it():
    """Two queues alone do not do this — the pool is shared, so bulk fills it."""
    from dramatiq.middleware import SkipMessage

    fair = BulkFairShare(worker_threads=8)
    broker = _Broker()
    assert fair.limit == 4

    for index in range(4):
        fair.before_process_message(broker, _Msg(QUEUE_BULK, f"m{index}"))
        fair._local.held = False  # a different worker thread holds each one

    assert fair.in_flight == 4
    with pytest.raises(SkipMessage):
        fair.before_process_message(broker, _Msg(QUEUE_BULK, "m-overflow"))


def test_a_deferred_bulk_message_is_requeued_rather_than_dropped():
    """Skipping acks the message. Without the re-enqueue the image is simply lost."""
    from dramatiq.middleware import SkipMessage

    fair = BulkFairShare(worker_threads=2)  # limit 1
    broker = _Broker()
    fair.before_process_message(broker, _Msg(QUEUE_BULK, "first"))
    fair._local.held = False

    with pytest.raises(SkipMessage):
        fair.before_process_message(broker, _Msg(QUEUE_BULK, "second"))

    assert len(broker.requeued) == 1
    _, delay = broker.requeued[0]
    assert delay and delay > 0, "a requeue with no delay is a spin"


def test_the_delay_grows_so_a_stuck_queue_goes_quiet_instead_of_hot():
    from dramatiq.middleware import SkipMessage

    fair = BulkFairShare(worker_threads=2)
    broker = _Broker()
    fair.before_process_message(broker, _Msg(QUEUE_BULK, "holder"))
    fair._local.held = False

    delays = []
    for _ in range(4):
        with pytest.raises(SkipMessage):
            fair.before_process_message(broker, _Msg(QUEUE_BULK, "bouncer"))
        delays.append(broker.requeued[-1][1])

    assert delays[-1] > delays[0], f"backoff did not grow: {delays}"


def test_an_interactive_scan_message_is_never_deferred():
    fair = BulkFairShare(worker_threads=2)
    broker = _Broker()
    fair.before_process_message(broker, _Msg(QUEUE_BULK, "a"))
    fair._local.held = False

    # The cap is full of bulk work, and a scan sails straight past it.
    fair.before_process_message(broker, _Msg(QUEUE_SCAN, "interactive"))
    assert broker.requeued == []


def test_a_slot_is_returned_when_a_bulk_message_finishes():
    fair = BulkFairShare(worker_threads=2)
    broker = _Broker()
    message = _Msg(QUEUE_BULK, "a")
    fair.before_process_message(broker, message)
    assert fair.in_flight == 1

    fair.after_process_message(broker, message)
    assert fair.in_flight == 0, "a leaked slot pins bulk throughput at zero"


# ---------------------------------------------------------------------------
# run_scan — the shared core
# ---------------------------------------------------------------------------


def test_the_digest_in_the_row_is_over_the_bytes_the_worker_will_upload(world):
    """The invariant the whole ordering exists to protect.

    The row is hash-chained and cannot be edited, so the digest must be taken
    over the redacted bytes *before* the row is written. If it were taken over
    the raw upload, every stored record would attest to an image that does not
    exist anywhere.
    """
    result = run_scan(
        ScanRequest(payload=_packet_jpeg(), officer_id=OFFICER.id, district="Khordha", pack_height_mm=PACK_HEIGHT_MM),
        scans=world["scans"],
        skus=world["skus"],
        settings=SETTINGS,
        spool=world["spool"],
        objects=world["objects"],
        enqueue=world["queue"],
    )

    spooled = world["spool"].take(str(result.scan_id))
    assert spooled is not None
    row = world["scans"].get(result.scan_id)
    assert row["image_sha256"] == storage.sha256_of(spooled)


def test_the_verdict_comes_back_before_the_evidence_is_uploaded(world):
    """Section 8c: evidence upload is off the critical path."""
    result = run_scan(
        ScanRequest(payload=_packet_jpeg(), officer_id=OFFICER.id, pack_height_mm=PACK_HEIGHT_MM),
        scans=world["scans"],
        skus=world["skus"],
        settings=SETTINGS,
        spool=world["spool"],
        objects=world["objects"],
        enqueue=world["queue"],
    )

    assert result.evidence.deferred is True
    assert world["objects"].objects == {}, "nothing was written to MinIO inline"
    assert ("store_evidence", QUEUE_SCAN) in [
        (name, queue) for name, queue, _ in world["queue"].sent
    ]


def test_the_upload_happens_inline_when_the_queue_will_not_take_it(world):
    """A slow response beats a missing photograph."""
    result = run_scan(
        ScanRequest(payload=_packet_jpeg(), officer_id=OFFICER.id, pack_height_mm=PACK_HEIGHT_MM),
        scans=world["scans"],
        skus=world["skus"],
        settings=SETTINGS,
        spool=InMemorySpool(max_bytes=1),  # refuses everything
        objects=world["objects"],
        enqueue=world["queue"],
    )

    assert result.evidence.stored is True
    assert result.evidence.deferred is False
    # The photograph itself went to the evidence bucket, inline, not to a queue.
    # Counting *all* objects was the old assertion and it broke the day OCR
    # started working: with declarations to draw, the scan also writes an
    # annotated exhibit to the derived bucket. That is the exhibit section 13
    # requires, not a double write, and the count was never what this test is
    # about.
    evidence_objects = [
        key for bucket, key in world["objects"].objects if bucket == storage.EVIDENCE_BUCKET
    ]
    assert len(evidence_objects) == 1, evidence_objects
    assert "store_evidence" not in world["queue"].tasks()


def test_a_repeat_sku_uploads_nothing_at_all(world):
    """Section 6's biggest saving, and the cache paying for itself twice."""
    sku = SkuRecord(
        id=uuid4(),
        brand="Parle",
        variant="G",
        pack_size="100 g",
        category="biscuits",
        barcode="8901030865275",
    )
    world["skus"].add(sku)
    world["scans"].save(
        {
            "id": uuid4(),
            "sku_id": sku.id,
            "officer_id": OFFICER.id,
            "source": "photo",
            "degradation_tier": "L0",
            "declaration_set": {},
            "captured_at": datetime.now(UTC),
            "model_versions": {},
            "rulepack_version": "x",
        }
    )

    from api.scanning import prepare_evidence

    plan = storage.plan_for([], is_repeat_sku=True)
    payload, decision = prepare_evidence(
        _frame_with_detail(),
        scan_id=uuid4(),
        captured_at=datetime.now(UTC),
        plan=plan,
        package_box=None,
        blur_faces=True,
    )
    assert payload is None
    assert decision.stored is False
    assert "repeat SKU" in decision.reason


def test_scan_count_is_bumped_on_the_bulk_queue_never_inline(world, monkeypatch):
    """On a shelf of forty packets this is the same row forty times.

    Inline, that is a row lock in the hot path of an interactive request, and a
    burst of scans of one popular SKU serialises behind itself. Section 8c puts
    it on the low queue; a counter thirty seconds stale changes nothing about
    which SKUs are popular.

    SKU resolution is forced here rather than arranged, because what is under
    test is *where the increment goes*, not whether a synthetic frame happens to
    match a pHash.
    """
    from api import scanning

    sku = SkuRecord(
        id=uuid4(),
        brand="Parle",
        variant="G",
        pack_size="100 g",
        category="biscuits",
        barcode="8901030865275",
    )
    world["skus"].add(sku)
    monkeypatch.setattr(scanning, "_resolve_sku", lambda _skus, _identity: sku)

    run_scan(
        ScanRequest(payload=_packet_jpeg(), officer_id=OFFICER.id, pack_height_mm=PACK_HEIGHT_MM),
        scans=world["scans"],
        skus=world["skus"],
        settings=SETTINGS,
        spool=world["spool"],
        objects=world["objects"],
        enqueue=world["queue"],
    )

    bumps = [(name, queue) for name, queue, _ in world["queue"].sent if name == "bump_scan_count"]
    assert bumps == [("bump_scan_count", QUEUE_BULK)]
    assert world["skus"].by_id(sku.id).scan_count == 0, "the counter moved on the request thread"


# ---------------------------------------------------------------------------
# The HTTP surface
# ---------------------------------------------------------------------------


def test_an_upload_returns_a_verdict_and_a_chained_record(client, world):
    response = _upload(client, category="biscuits")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["record_sha256"]
    assert body["chain_seq"] == 0
    assert body["evidence"]["deferred"] is True
    assert body["latency_ms"] >= 0


def test_an_empty_upload_is_a_400(client):
    response = _upload(client, payload=b"")
    assert response.status_code == 400


def test_a_pdf_uploaded_as_a_photograph_is_a_400(client):
    response = _upload(client, payload=b"%PDF-1.7 not a photograph")
    assert response.status_code == 400
    assert "decodable image" in response.json()["detail"]


def test_a_retried_upload_returns_the_first_answer_without_rescanning(client, world):
    """Section 5's idempotency, on the channel where it costs the most.

    Re-running the pipeline would produce a *second* measurement of one
    photograph, which is exactly the ambiguity the evidence chain exists to
    prevent.
    """
    scan_id = str(uuid4())
    first = _upload(client, scan_id=scan_id)
    second = _upload(client, scan_id=scan_id)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == scan_id
    assert len(world["scans"].all_records()) == 1, "a retry appended a second chain entry"
    assert "not a re-scan" in second.json()["message"]


def test_geolocation_is_coarsened_before_it_is_ever_stored(client, world):
    """Section 18: enough to identify a market, not a doorway."""
    response = _upload(client, lat=20.296059123, lon=85.824539987)
    row = world["scans"].get(UUID(response.json()["id"]))

    assert row["geo"] == {"lat": 20.296, "lon": 85.825}


def test_an_upload_is_written_to_the_audit_log(client, world):
    _upload(client)
    actions = [(e["action"], e["entity"]) for e in world["audit"].entries()]
    assert ("create", "scan") in actions


def test_a_report_is_only_queued_when_it_was_asked_for(client, world):
    _upload(client)
    assert "render_report" not in world["queue"].tasks()

    _upload(client, report="true")
    assert "render_report" in world["queue"].tasks()


# ---------------------------------------------------------------------------
# Bulk
# ---------------------------------------------------------------------------


def test_bulk_returns_a_receipt_immediately(client, world):
    files = [
        ("images", (f"shelf-{i}.jpg", _packet_jpeg(), "image/jpeg")) for i in range(3)
    ]
    response = client.post("/api/v1/scans/bulk", headers=_auth(), files=files)

    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] == 3
    assert body["poll"].endswith(body["job_id"])
    # Nothing has been scanned yet — the work is queued, which is the point.
    assert world["scans"].all_records() == []
    assert world["queue"].tasks() == ["ingest_bulk_image"] * 3


def test_a_rejected_file_is_named_not_counted(client, world):
    files = [
        ("images", ("good.jpg", _packet_jpeg(), "image/jpeg")),
        ("images", ("empty.jpg", b"", "image/jpeg")),
    ]
    response = client.post("/api/v1/scans/bulk", headers=_auth(), files=files)

    assert response.status_code == 202
    assert response.json()["accepted"] == 1
    assert response.json()["rejected"] == ["empty.jpg: empty file"]


def test_a_request_where_nothing_could_be_queued_is_a_400(client):
    files = [("images", ("empty.jpg", b"", "image/jpeg"))]
    response = client.post("/api/v1/scans/bulk", headers=_auth(), files=files)
    assert response.status_code == 400


def test_the_job_exists_before_any_message_is_enqueued(client, world):
    """Otherwise a fast worker records a result against nothing and the count
    silently never reaches its total — a hang with no error."""
    files = [("images", ("a.jpg", _packet_jpeg(), "image/jpeg"))]
    response = client.post("/api/v1/scans/bulk", headers=_auth(), files=files)

    job_id = UUID(response.json()["job_id"])
    assert world["jobs"].get(job_id) is not None
    assert world["jobs"].get(job_id).total == 1


def test_a_bulk_job_belonging_to_another_officer_is_not_found(client, world):
    files = [("images", ("a.jpg", _packet_jpeg(), "image/jpeg"))]
    job_id = client.post("/api/v1/scans/bulk", headers=_auth(), files=files).json()["job_id"]

    mine = client.get(f"/api/v1/scans/bulk/{job_id}", headers=_auth())
    theirs = client.get(f"/api/v1/scans/bulk/{job_id}", headers=_auth(OTHER_OFFICER))
    supervisor = client.get(f"/api/v1/scans/bulk/{job_id}", headers=_auth(SUPERVISOR))

    assert mine.status_code == 200
    # 404 rather than 403 — a job id must not be confirmable by its error code.
    assert theirs.status_code == 404
    assert supervisor.status_code == 200


def test_a_bulk_job_reports_progress(client, world):
    files = [("images", (f"a{i}.jpg", _packet_jpeg(), "image/jpeg")) for i in range(2)]
    job_id = client.post("/api/v1/scans/bulk", headers=_auth(), files=files).json()["job_id"]

    body = client.get(f"/api/v1/scans/bulk/{job_id}", headers=_auth()).json()
    assert body == {
        **body,
        "total": 2,
        "completed": 0,
        "failed": 0,
        "pending": 2,
        "status": "running",
    }


# ---------------------------------------------------------------------------
# The workers, actually running
# ---------------------------------------------------------------------------


@pytest.fixture
def wired(world, monkeypatch):
    """Point the actors at the same in-memory world the routes use.

    Actors resolve their stores through `api.deps`, not through FastAPI's
    dependency overrides — a worker process has no request to hang a dependency
    off. So the two are joined here explicitly, which is also a fair model of
    the deployed arrangement where both point at one Postgres.
    """
    import api.deps as deps
    import api.deps.resources as resources

    monkeypatch.setattr(deps, "get_scan_store", lambda: world["scans"])
    monkeypatch.setattr(deps, "get_sku_store", lambda: world["skus"])
    # `render_report` looks the officer up to put a name on the report. Left
    # unpatched, that call falls through to the SQL store and blocks on a
    # Postgres connection that a laptop running unit tests does not have — the
    # test does not fail, it hangs, which is the worst way for this to go wrong.
    monkeypatch.setattr(deps, "get_user_store", lambda: world["users"])
    monkeypatch.setattr(resources, "get_spool", lambda: world["spool"])
    monkeypatch.setattr(resources, "get_bulk_jobs", lambda: world["jobs"])
    monkeypatch.setattr(resources, "get_object_store", lambda: world["objects"])
    get_broker().flush_all()
    return world


def test_the_worker_uploads_the_spooled_bytes_and_only_those(wired):
    result = run_scan(
        ScanRequest(payload=_packet_jpeg(), officer_id=OFFICER.id, pack_height_mm=PACK_HEIGHT_MM),
        scans=wired["scans"],
        skus=wired["skus"],
        settings=SETTINGS,
        spool=wired["spool"],
        objects=wired["objects"],
        enqueue=wired["queue"],
    )
    row = wired["scans"].get(result.scan_id)

    tasks.store_evidence(
        scan_id=str(result.scan_id),
        captured_at=row["captured_at"].isoformat(),
        tier=result.evidence.tier,
        sha256=row["image_sha256"],
    )

    written = list(wired["objects"].objects.values())
    assert len(written) == 1
    assert storage.sha256_of(written[0]) == row["image_sha256"]


def test_the_worker_refuses_bytes_that_do_not_match_the_chained_row(wired):
    """A row asserting a hash the object does not have is a tamper signal.

    Logging it and uploading anyway would surface the alarm months later during
    a verification sweep, with nobody left who remembers the upload.
    """
    wired["spool"].put("deadbeef", b"different pixels entirely")

    with pytest.raises(ValueError, match="do not match the digest"):
        tasks.store_evidence(
            scan_id="deadbeef",
            captured_at=datetime.now(UTC).isoformat(),
            tier="evidence_original",
            sha256="0" * 64,
        )
    assert wired["objects"].objects == {}


def test_a_duplicate_delivery_uploads_nothing_a_second_time(wired):
    """The bucket is versioned and write-once; a second PUT reads as an overwrite."""
    result = run_scan(
        ScanRequest(payload=_packet_jpeg(), officer_id=OFFICER.id, pack_height_mm=PACK_HEIGHT_MM),
        scans=wired["scans"],
        skus=wired["skus"],
        settings=SETTINGS,
        spool=wired["spool"],
        objects=wired["objects"],
        enqueue=wired["queue"],
    )
    row = wired["scans"].get(result.scan_id)
    args = {
        "scan_id": str(result.scan_id),
        "captured_at": row["captured_at"].isoformat(),
        "tier": result.evidence.tier,
        "sha256": row["image_sha256"],
    }

    tasks.store_evidence(**args)
    tasks.store_evidence(**args)  # redelivery

    assert len(wired["objects"].objects) == 1


def test_the_bulk_queue_runs_the_same_scan_the_route_runs(wired):
    """Section 12: "if it diverges, two products exist and only one is tested"."""
    payload = _packet_jpeg()

    # BOTH SIDES ARE THE QUEUE'S OWN INPUTS, and that is the point of the test.
    #
    # It used to compare a photo-channel scan against a queued one. That stopped
    # being a fair comparison once the photo channel began requiring a
    # ruler-measured pack height: a scale does not merely add millimetres to the
    # output, it changes WHICH crops the ROI ranker reads (see
    # `roi.DECLARATION_BAND_MM` -- without a millimetre the eight crops go to the
    # largest print on the pack). Two different inputs producing two different
    # readings proves nothing about whether the worker reimplemented anything.
    #
    # So the inputs are held identical and the question stays the real one from
    # section 12: does the queue run `run_scan`, or a second copy of it? "If it
    # diverges, two products exist and only one is tested."
    direct = run_scan(
        ScanRequest(
            payload=payload,
            officer_id=OFFICER.id,
            source="bulk_image",
            category="biscuits",
        ),
        scans=InMemoryScanStore(),
        skus=wired["skus"],
        settings=SETTINGS,
        spool=InMemorySpool(),
        objects=None,
        enqueue=None,
    )

    job_id, scan_id = uuid4(), uuid4()
    wired["jobs"].create(
        BulkJob(
            id=job_id, officer_id=OFFICER.id, total=1, created_at=datetime.now(UTC)
        )
    )
    wired["spool"].put(f"bulk:{job_id}:{scan_id}", payload)
    tasks.ingest_bulk_image(
        job_id=str(job_id),
        scan_id=str(scan_id),
        officer_id=str(OFFICER.id),
        filename="a.jpg",
        category="biscuits",
    )

    job = wired["jobs"].get(job_id)
    assert job.completed == 1 and job.failed == 0
    bulk_row = wired["scans"].get(scan_id)
    # Same extraction, different provenance. `captured_at` and `source` are the
    # two fields that are *meant* to differ between a queued image and one run
    # directly, so they are lifted out before the comparison -- and the
    # comparison only became meaningful at all once the recogniser was present:
    # before that both sides were the empty dict and this asserted nothing.
    #
    # Nothing else is excluded, deliberately. An exclusion list is how a parity
    # test rots into asserting nothing, and the inputs above are now identical
    # precisely so that none is needed.
    provenance = ("captured_at", "source")
    expected = direct.declarations.model_dump(mode="json") if direct.declarations else {}
    assert {k: v for k, v in bulk_row["declaration_set"].items() if k not in provenance} == {
        k: v for k, v in expected.items() if k not in provenance
    }
    assert bulk_row["declaration_set"], "the bulk path extracted nothing at all"
    assert bulk_row["source"] == "bulk_image"

    # With identical inputs the scale agrees too -- neither side has a ruler.
    assert expected["geometry"]["scale_tier"] == "C"
    assert bulk_row["declaration_set"]["geometry"]["scale_tier"] == "C"


def test_one_bad_file_fails_only_itself(wired):
    """A folder of 300 must not be held hostage by one unreadable file."""
    job_id, scan_id = uuid4(), uuid4()
    wired["jobs"].create(
        BulkJob(id=job_id, officer_id=OFFICER.id, total=1, created_at=datetime.now(UTC))
    )
    wired["spool"].put(f"bulk:{job_id}:{scan_id}", b"%PDF-1.7 not a photograph")

    tasks.ingest_bulk_image(
        job_id=str(job_id),
        scan_id=str(scan_id),
        officer_id=str(OFFICER.id),
        filename="brochure.pdf",
    )

    job = wired["jobs"].get(job_id)
    assert job.failed == 1
    assert job.status == "failed"
    assert "brochure.pdf" in job.errors[0]


def test_the_queue_actually_delivers_end_to_end(wired):
    """Everything above calls the actors directly. This one goes through Dramatiq.

    The stub broker plus a real `dramatiq.Worker` means the middleware runs too,
    so the fair-share cap is exercised by the same path a deployment uses rather
    than being asserted only in isolation.
    """
    from api.deps.resources import enqueue

    job_id, scan_id = uuid4(), uuid4()
    wired["jobs"].create(
        BulkJob(id=job_id, officer_id=OFFICER.id, total=1, created_at=datetime.now(UTC))
    )
    wired["spool"].put(f"bulk:{job_id}:{scan_id}", _packet_jpeg())

    enqueue(
        "ingest_bulk_image",
        queue=QUEUE_BULK,
        job_id=str(job_id),
        scan_id=str(scan_id),
        officer_id=str(OFFICER.id),
        filename="a.jpg",
    )
    drain()

    assert wired["jobs"].get(job_id).completed == 1
    assert wired["scans"].get(scan_id) is not None


def test_enqueueing_onto_the_wrong_lane_is_an_error_not_a_silent_demotion():
    """A message on the wrong queue runs correctly, at the wrong priority, with
    nothing to show for it. Section 8c's whole guarantee is which lane it lands in."""
    from api.deps.resources import enqueue

    with pytest.raises(ValueError, match="declared on the 'bulk' queue"):
        enqueue("ingest_bulk_image", queue=QUEUE_SCAN, job_id="x")

    with pytest.raises(ValueError, match="no such task"):
        enqueue("definitely_not_a_task", queue=QUEUE_SCAN)


# ---------------------------------------------------------------------------
# The report route — sections 13 and 8c
# ---------------------------------------------------------------------------


def _stored_scan(world, **overrides):
    scan_id = uuid4()
    world["scans"].save(
        {
            "id": scan_id,
            "officer_id": OFFICER.id,
            "district": "Khordha",
            "category": "biscuits",
            "source": "photo",
            "degradation_tier": "L1",
            "declaration_set": {"declarations": [{"field": "mrp", "text": "MRP Rs. 10"}]},
            "coverage": 0.8,
            "captured_at": datetime.now(UTC),
            "model_versions": {},
            "rulepack_version": "test",
            **overrides,
        }
    )
    world["scans"].save_verdicts(
        scan_id,
        [
            {
                "rule_id": "LMPC.MRP.NUMERAL_HEIGHT",
                "rule_ref": "Rule 7(2), Table I",
                "status": "FAIL",
                "severity": "high",
                "message": "MRP numerals are below the prescribed height.",
                "measured": 0.82,
                "threshold": 1.0,
                "tolerance": 0.09,
            }
        ],
    )
    return scan_id


def test_the_html_and_docx_reports_render_immediately(client, world):
    """Tens of milliseconds each. Making an officer poll for those is ceremony."""
    scan_id = _stored_scan(world)

    html = client.get(f"/api/v1/scans/{scan_id}/report", headers=_auth())
    docx = client.get(f"/api/v1/scans/{scan_id}/report?format=docx", headers=_auth())

    assert html.status_code == 200
    assert "Part E" in html.text and "Rule 7(2), Table I" in html.text
    assert docx.status_code == 200
    assert docx.content[:2] == b"PK"
    assert "attachment" in docx.headers["content-disposition"]


def test_an_unrendered_pdf_is_rendered_now_and_kept_for_next_time(client, world):
    """Section 8c wants the 300-800 ms renderer off the critical path. It was —
    by answering `202 {"status": "rendering"}` — and that was the wrong shape for
    **this** response.

    The scan page offers the report as `<a href=... download="scan-<id>.pdf">`,
    and a browser following a `download` link saves whatever comes back under
    that name whatever its status. So the 202 arrived on the officer's disk as
    `scan-<id>.pdf` containing thirty bytes of JSON, and no viewer would open it.
    The demonstration stack has no worker, so that was every request.

    A slow response is a smaller problem than a corrupt file. The route renders
    now **and** still enqueues the warm-up, so the next request gets the cheap
    path from the derived bucket — which is what the test below asserts.
    """
    scan_id = _stored_scan(world)

    response = client.get(f"/api/v1/scans/{scan_id}/report?format=pdf", headers=_auth())

    assert response.status_code == 200
    assert response.content[:5] == b"%PDF-", (
        f"the report route handed a browser {response.content[:40]!r}"
    )
    # The bucket is warmed by writing the bytes we just produced, not by asking
    # a worker to produce them again.
    key = storage.report_key(
        str(scan_id), captured_at=world["scans"].get(scan_id)["captured_at"], fmt="pdf"
    )
    stored = world["objects"].objects.get((storage.DERIVED_BUCKET, key))
    assert stored == response.content, "the rendered PDF was not kept for the next request"
    assert "render_report" not in world["queue"].tasks(), (
        "no worker is needed: the document is already rendered"
    )


def test_a_rendered_pdf_is_served_from_the_derived_bucket(client, world):
    """Once the worker has produced it, the route hands it over rather than
    re-rendering — the derived bucket is where a report lives."""
    scan_id = _stored_scan(world)
    row = world["scans"].get(scan_id)
    key = storage.report_key(str(scan_id), captured_at=row["captured_at"], fmt="pdf")
    world["objects"].objects[(storage.DERIVED_BUCKET, key)] = b"%PDF-1.7 pretend"

    response = client.get(f"/api/v1/scans/{scan_id}/report?format=pdf", headers=_auth())

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    assert "render_report" not in world["queue"].tasks()


def test_downloading_a_report_is_audited_as_taking_evidence_not_as_a_view(client, world):
    """Section 18 asks who took a copy out, which is not the same row as who
    opened the app."""
    scan_id = _stored_scan(world)
    client.get(f"/api/v1/scans/{scan_id}/report?format=docx", headers=_auth())

    entries = [(e["action"], e["entity"], e["entity_id"]) for e in world["audit"].entries()]
    assert ("download_evidence", "report", f"{scan_id}:docx") in entries


def test_an_unknown_format_is_rejected_by_the_route(client, world):
    scan_id = _stored_scan(world)
    response = client.get(f"/api/v1/scans/{scan_id}/report?format=xlsx", headers=_auth())
    assert response.status_code == 422


def test_a_report_for_a_scan_that_does_not_exist_is_a_404(client):
    assert client.get(f"/api/v1/scans/{uuid4()}/report", headers=_auth()).status_code == 404


def test_the_render_worker_stores_into_the_derived_bucket(wired):
    """DOCX rather than PDF, because this machine may have no Pango — and the
    storage path is the same either way."""
    scan_id = _stored_scan(wired)

    tasks.render_report(scan_id=str(scan_id), fmt="docx")

    written = {key: value for (bucket, key), value in wired["objects"].objects.items()
               if bucket == storage.DERIVED_BUCKET}
    assert len(written) == 1
    key, payload = next(iter(written.items()))
    assert key.endswith(f"{scan_id}/report.docx")
    assert payload[:2] == b"PK"


# ---------------------------------------------------------------------------
# Multi-frame — one package, several photographs. AKSHAR.md section 8b
# ---------------------------------------------------------------------------


def _upload_frames(client, count: int, **form):
    """Repeat the `image` field, which is how one pack arrives from several sides."""
    form.setdefault("pack_height_mm", PACK_HEIGHT_MM)
    return client.post(
        "/api/v1/scans",
        headers=_auth(),
        files=[
            ("image", (f"frame{index}.jpg", _packet_jpeg(), "image/jpeg"))
            for index in range(count)
        ],
        data=form,
    )


def test_several_photographs_of_one_pack_make_one_scan(client, world):
    """One row, one chain entry, one verdict set — not three scans."""
    response = _upload_frames(client, 3)
    assert response.status_code == 201
    body = response.json()

    assert len(body["frames"]) == 3
    assert [frame["frame"] for frame in body["frames"]] == [0, 1, 2]
    assert body["declarations"]["frame_count"] == 3
    assert len(world["scans"]._rows) == 1


def test_every_photograph_is_hashed_into_the_record(client, world):
    """Section 6: a frame that is evidence but has no digest is indefensible."""
    body = _upload_frames(client, 2).json()
    digests = [frame["image_sha256"] for frame in body["frames"]]
    assert all(digests), digests

    row = world["scans"].get(UUID(body["id"]))
    stored = {entry["image_sha256"] for entry in row["frames"]}
    assert stored == set(digests)


def test_the_frames_are_stored_under_keys_of_their_own(client, world):
    """Two photographs cannot both be `<scan_id>.jpg`."""
    body = _upload_frames(client, 2).json()
    keys = [frame["image_key"] for frame in body["frames"]]
    assert len(set(keys)) == 2
    assert keys[0].endswith(".jpg") and "/frame-01.jpg" in keys[1]


def test_a_single_photograph_carries_no_frames_key_at_all(client, world):
    """The hash chain covers the keys a payload has.

    A single-frame row that grew `frames: null` would hash differently from
    every single-frame row already chained, and all of them would then fail
    verification. So the key appears only when it has something to say.
    """
    body = _upload(client).json()
    assert body["frames"] == []
    row = world["scans"].get(UUID(body["id"]))
    assert "frames" not in row


def test_too_many_photographs_is_a_bad_request_not_a_slow_one(client):
    response = _upload_frames(client, 6)
    assert response.status_code == 400
    assert "bulk upload" in response.json()["detail"]


# ---------------------------------------------------------------------------
# The pack height is required, and required is the point
# ---------------------------------------------------------------------------


def test_a_photo_without_a_pack_height_is_refused(client):
    """Not optional, at the user's explicit instruction, and he was right.

        "see no make the fields permanent to be entered we dont want our system
         to bypass those rules right"

    Optional would mean a hurried officer leaves it blank, the scan falls
    through to no scale, and the report comes back having quietly examined 28 of
    31 rules with nothing on its face to say so. NO_DATA is the honest answer to
    "there was no ruler". It is the wrong answer to "nobody was asked".
    """
    response = client.post(
        "/api/v1/scans",
        headers=_auth(),
        files={"image": ("packet.jpg", _packet_jpeg(), "image/jpeg")},
        data={},
    )
    assert response.status_code == 422


def test_a_decimal_slip_is_refused_with_a_sentence_that_explains_the_danger(client):
    """`9.5` for `95` is one keystroke and a factor of ten, and it has NO visible
    symptom: every character simply measures ten times too small and every
    height rule fails a compliant pack."""
    response = _upload(client, pack_height_mm=0.5)
    assert response.status_code == 400
    assert "plausible height" in response.json()["detail"]


def test_a_measured_height_reaches_the_millimetre_rules(client):
    """The whole chain, end to end: a number off a ruler becomes a scale tier,
    and the three `min_height_mm` rules stop returning NO_DATA."""
    body = _upload(client, pack_height_mm=95.0).json()
    geometry = body["declarations"]["geometry"]
    assert geometry["scale_tier"] == "A"
    assert geometry["mm_per_px"] is not None


def test_without_one_the_same_photograph_is_tier_c(client):
    """The contrast, stated rather than assumed. Same image, no ruler: the
    scan still runs and 28 rules still answer -- it does not fail, it declines
    to measure."""
    from api.scanning import ScanRequest, run_scan

    # `bulk_image`, because the photo channel cannot omit it any more.
    result = run_scan(
        ScanRequest(payload=_packet_jpeg(), officer_id=OFFICER.id, source="bulk_image"),
        scans=InMemoryScanStore(),
        skus=InMemorySkuStore(),
        settings=SETTINGS,
        spool=InMemorySpool(),
        objects=None,
        enqueue=None,
    )
    assert result.declarations is not None
    assert result.declarations.geometry.scale_tier == "C"
    assert result.verdicts, "tier C is not a failure: the other rules still run"
