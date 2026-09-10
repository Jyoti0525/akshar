"""`/api/v1/scans` — the endpoints an officer actually uses. AKSHAR.md sections 5, 8c, 12.

Three things here are worth reading before changing anything.

**The rules engine is called, never re-implemented.** A handler assembles a
`DeclarationSet`, passes it to `rules.engine.evaluate`, and stores what comes
back. No route decides compliance. Section 3: *"Rules decide, models never"* —
and a web handler is not an exception to that; it is the most tempting place to
make one.

**Sync is idempotent, and that is a storage guarantee rather than a handler
one.** `ScanStore.save` returns `created=False` for a UUID it already holds. The
route reports the count honestly instead of pretending everything was new,
because a client that has lost track of its outbox needs to tell the difference.

**Nothing here waits for a report.** Section 8c: *"A PDF takes 300-800 ms to
render and an officer standing in a shop must not wait for it. The verdict
renders; the report link appears when it is ready."* The response carries
`report_status="queued"`; rendering is a low-priority job.
"""

from __future__ import annotations

import contextlib
import time
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from api.deps import (
    AuditDep,
    BulkJobStoreDep,
    CurrentUserDep,
    EnqueueDep,
    ObjectStoreDep,
    ReviewStoreDep,
    ScanStoreDep,
    SettingsDep,
    SkuStoreDep,
    SpoolDep,
    UserStoreDep,
    client_ip,
    require_role,
)
from api.repository import BulkJob, Correction, ReviewResolution
from api.scanning import MAX_UPLOAD_BYTES, EvidenceDecision, ScanRequest, run_scan
from api.schemas import (
    BulkAccepted,
    BulkJobStatus,
    CorrectionRequest,
    EvidenceInfo,
    FrameInfo,
    GeoPoint,
    ListingScanRequest,
    ReviewResolutionRequest,
    ReviewResolutionResponse,
    ScanResponse,
    SyncRequest,
    SyncResponse,
    SyncResult,
)
from api.security import outranks
from contracts import DeclarationSet, PackageContext, Verdict
from evidence import storage
from rules.engine import evaluate
from rules.loader import load_rulepack

router = APIRouter(prefix="/api/v1/scans", tags=["scans"])


def reduce_geo(point: GeoPoint | None, *, decimals: int) -> dict[str, float] | None:
    """Truncate a coordinate before it is ever written. Section 18.

    "Geolocation is stored at reduced precision — enough to identify a market,
    not a doorway." Applied at the boundary rather than at display time,
    deliberately: a coarse value that was never stored precisely cannot later be
    recovered by someone with database access, and cannot leak in a backup.
    """
    if point is None:
        return None
    return {"lat": round(point.lat, decimals), "lon": round(point.lon, decimals)}


@router.post("/listing", response_model=ScanResponse)
async def scan_listing(
    body: ListingScanRequest,
    request: Request,
    user: CurrentUserDep,
    scans: ScanStoreDep,
    settings: SettingsDep,
    audit: AuditDep,
) -> ScanResponse:
    """The third input channel: an e-commerce listing, no image.

    This route is short *because* the wall holds. It parses text into a
    `DeclarationSet` and hands it to the same engine a photograph reaches, so
    every presence, format, unit-symbol and misleading-declaration rule runs
    unchanged, and every geometric rule returns `NO_DATA` rather than `FAIL`.

    Section 3 predicted the cost of getting this wrong: with OCR wired into the
    rules "that third channel becomes a rewrite instead of an afternoon's work".
    """
    from vision.pipeline import scan_listing_text

    started = time.perf_counter()
    pack = load_rulepack()
    outcome = scan_listing_text(body.text, rulepack_version=pack.version_string)

    context = PackageContext(category=body.category or "other")
    verdicts = evaluate(outcome.declarations, context, pack)
    latency_ms = int((time.perf_counter() - started) * 1000)

    scan_id = uuid4()
    payload: dict[str, Any] = {
        "id": scan_id,
        "officer_id": user.id,
        "district": body.district or user.district,
        "source": "listing_text",
        "degradation_tier": outcome.degradation.tier,
        "declaration_set": outcome.declarations.model_dump(mode="json"),
        "coverage": outcome.declarations.coverage,
        "latency_ms": latency_ms,
        "cache_hit": False,
        "image_key": None,
        "image_sha256": None,
        "geo": None,
        "captured_at": datetime.now(UTC),
        "model_versions": outcome.model_versions,
        "rulepack_version": pack.version_string,
    }
    stored = scans.save(payload)
    scans.save_verdicts(scan_id, [verdict.model_dump(mode="json") for verdict in verdicts])

    audit.record(
        user_id=user.id,
        action="create",
        entity="scan",
        entity_id=str(scan_id),
        ip=client_ip(request),
    )

    return ScanResponse(
        id=scan_id,
        exit_path="listing_text",
        source="listing_text",
        degradation_tier=outcome.degradation.tier,
        coverage=outcome.declarations.coverage,
        latency_ms=latency_ms,
        cache_hit=False,
        declarations=outcome.declarations,
        verdicts=verdicts,
        message=outcome.message,
        model_versions=outcome.model_versions,
        rulepack_version=pack.version_string,
        record_sha256=stored.record.record_sha256,
        chain_seq=stored.record.chain_seq,
        report_status="queued",
    )


@router.post("/sync", response_model=SyncResponse)
async def sync(
    body: SyncRequest,
    request: Request,
    user: CurrentUserDep,
    scans: ScanStoreDep,
    settings: SettingsDep,
    audit: AuditDep,
) -> SyncResponse:
    """Replay an offline outbox. Idempotent, in the strict sense.

    Section 5: *"Every scan gets a client-generated UUIDv7, which is
    time-ordered so it doubles as a sort key. Sync is idempotent, so replaying
    the outbox never duplicates a record."*

    An officer's phone regains signal halfway through an upload and retries the
    whole batch. Every scan it already delivered comes back `created=False`, and
    — this is the part that matters — **no second chain entry is appended**. A
    duplicated chain entry would break the sequence for a client whose only
    mistake was losing signal.

    Scans arrive in whatever order the outbox held them; `chain_seq` is assigned
    here, server-side, because "offline clients cannot possibly agree on
    ordering among themselves".
    """
    results: list[SyncResult] = []
    created = 0

    for item in body.scans:
        payload: dict[str, Any] = {
            "id": item.id,
            "officer_id": user.id,
            "district": item.district or user.district,
            "source": item.source,
            "degradation_tier": item.degradation_tier,
            "declaration_set": item.declaration_set,
            "coverage": item.coverage,
            "latency_ms": item.latency_ms,
            "cache_hit": item.cache_hit,
            "image_key": item.image_key,
            "image_sha256": item.image_sha256,
            "geo": reduce_geo(item.geo, decimals=settings.geo_precision_dp),
            "captured_at": item.captured_at,
            "model_versions": item.model_versions,
            "rulepack_version": item.rulepack_version,
        }
        outcome = scans.save(payload)
        created += int(outcome.created)
        results.append(
            SyncResult(
                id=item.id,
                created=outcome.created,
                chain_seq=outcome.record.chain_seq,
                record_sha256=outcome.record.record_sha256,
            )
        )

    audit.record(
        user_id=user.id,
        action="sync",
        entity="scan",
        entity_id=f"{len(body.scans)} scans",
        ip=client_ip(request),
    )

    return SyncResponse(
        accepted=len(results),
        created=created,
        duplicates=len(results) - created,
        results=results,
    )


MAX_BULK_FILES = 500
"""Per request, not per job. A district uploading a season's photographs sends
several requests; a single request holding 5,000 files has to be buffered
somewhere before any of it can be queued, and that somewhere is the API
process's memory."""


def _evidence_info(decision: EvidenceDecision) -> EvidenceInfo:
    return EvidenceInfo(
        stored=decision.stored,
        reason=decision.reason,
        key=decision.key,
        sha256=decision.sha256,
        tier=decision.tier,
        deferred=decision.deferred,
        faces_blurred=decision.faces_blurred,
        faces_on_package=decision.faces_on_package,
    )


def _replay(row: dict[str, Any], verdicts: list[dict[str, Any]]) -> ScanResponse:
    """Rebuild the response for a scan we already hold. Section 5, idempotency.

    A phone that lost signal mid-upload retries with the same UUIDv7, and this
    returns what the first attempt returned without running the pipeline again.
    That is not only 561 ms saved: re-running it would produce a *second*
    measurement of the same photograph, and two measurements of one packet is
    exactly the ambiguity an evidence chain exists to prevent.
    """
    declarations = row.get("declaration_set") or None
    return ScanResponse(
        id=row["id"],
        exit_path="full",
        source=row.get("source", "photo"),
        degradation_tier=row.get("degradation_tier", "L0"),
        coverage=float(row.get("coverage") or 0.0),
        latency_ms=int(row.get("latency_ms") or 0),
        cache_hit=bool(row.get("cache_hit")),
        declarations=DeclarationSet.model_validate(declarations) if declarations else None,
        verdicts=[Verdict.model_validate(v) for v in verdicts],
        message="Already recorded; this is the stored result, not a re-scan.",
        model_versions=row.get("model_versions") or {},
        rulepack_version=row.get("rulepack_version", ""),
        record_sha256=row.get("record_sha256"),
        chain_seq=row.get("chain_seq"),
        report_status="queued",
        evidence=EvidenceInfo(
            stored=row.get("image_key") is not None,
            reason="stored when this scan was first recorded",
            key=row.get("image_key"),
            sha256=row.get("image_sha256"),
        ),
    )


@router.post("", response_model=ScanResponse, status_code=status.HTTP_201_CREATED)
async def scan_photo(
    request: Request,
    user: CurrentUserDep,
    scans: ScanStoreDep,
    skus: SkuStoreDep,
    settings: SettingsDep,
    audit: AuditDep,
    spool: SpoolDep,
    objects: ObjectStoreDep,
    enqueue: EnqueueDep,
    image: Annotated[
        list[UploadFile],
        File(
            description=(
                "The photograph, JPEG or PNG. Repeat the field to send several "
                "photographs OF THE SAME PACKAGE — front, back, side. They are "
                "read separately, their evidence is unioned, and the rules are "
                "evaluated once on the union. Several packages is /scans/bulk."
            )
        ),
    ],
    scan_id: Annotated[UUID | None, Form()] = None,
    category: Annotated[str | None, Form()] = None,
    district: Annotated[str | None, Form()] = None,
    lat: Annotated[float | None, Form()] = None,
    lon: Annotated[float | None, Form()] = None,
    captured_at: Annotated[datetime | None, Form()] = None,
    report: Annotated[bool, Form()] = False,
) -> ScanResponse:
    """The first input channel: one photograph, one verdict, now.

    **`scan_id` is the client's, not ours.** Section 5: a UUIDv7 generated on
    the phone is what makes a retry idempotent, and it is accepted here for the
    same reason `/sync` accepts one — an officer on a bad connection retries the
    upload, and the second attempt must return the first attempt's answer rather
    than create a second inspection record of the same packet.

    **The scan runs in a thread.** `run_scan` is several hundred milliseconds of
    OpenCV and ONNX Runtime, all of it holding the GIL in C code that never
    awaits. Called directly from this coroutine it would block the event loop
    for the whole duration, so every other officer's request — including the
    cheap ones — would queue behind it. `run_in_threadpool` is the difference
    between a concurrency of one and a concurrency of the pool.
    """
    payloads = [await upload.read() for upload in image]
    payloads = [chunk for chunk in payloads if chunk]
    if not payloads:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No image data was uploaded."
        )

    scan_id = scan_id or uuid4()
    existing = scans.get(scan_id)
    if existing is not None:
        audit.record(
            user_id=user.id,
            action="view",
            entity="scan",
            entity_id=str(scan_id),
            ip=client_ip(request),
        )
        return _replay(dict(existing), scans.verdicts_for(scan_id))

    geo = reduce_geo(
        GeoPoint(lat=lat, lon=lon) if lat is not None and lon is not None else None,
        decimals=settings.geo_precision_dp,
    )

    try:
        result = await run_in_threadpool(
            run_scan,
            ScanRequest(
                payload=payloads[0],
                extra_frames=tuple(payloads[1:]),
                officer_id=user.id,
                scan_id=scan_id,
                source="photo",
                district=district or user.district,
                category=category,
                geo=geo,
                captured_at=captured_at,
            ),
            scans=scans,
            skus=skus,
            settings=settings,
            spool=spool,
            objects=objects,
            enqueue=enqueue,
        )
    except ValueError as exc:
        # Not an image, or over the size limit. A malformed request, not a scan
        # that degraded — section 5's ladder is about photographs we cannot
        # read, not about a client sending a PDF.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if report and enqueue is not None:
        from workers.broker import QUEUE_SCAN

        enqueue("render_report", queue=QUEUE_SCAN, scan_id=str(scan_id), fmt="pdf")

    audit.record(
        user_id=user.id,
        action="create",
        entity="scan",
        entity_id=str(scan_id),
        ip=client_ip(request),
    )

    return ScanResponse(
        id=result.scan_id,
        exit_path=result.exit_path,
        source=result.source,
        degradation_tier=result.degradation_tier,
        coverage=result.coverage,
        latency_ms=result.latency_ms,
        cache_hit=result.cache_hit,
        declarations=result.declarations,
        verdicts=result.verdicts,
        message=result.message,
        model_versions=result.model_versions,
        rulepack_version=result.rulepack_version,
        record_sha256=result.stored.record.record_sha256,
        chain_seq=result.stored.record.chain_seq,
        report_status="queued" if report else "not_requested",
        evidence=_evidence_info(result.evidence),
        capture_quality=result.capture_quality,
        framing=result.framing,
        frames=[
            FrameInfo(
                frame=frame.frame,
                exit_path=frame.exit_path,
                read=frame.read,
                message=frame.message,
                capture_quality=frame.quality,
                framing=frame.framing,
                image_key=frame.image_key,
                image_sha256=frame.image_sha256,
                stored=frame.stored,
            )
            for frame in result.frames
        ],
    )


@router.post("/bulk", response_model=BulkAccepted, status_code=status.HTTP_202_ACCEPTED)
async def bulk_upload(
    request: Request,
    user: CurrentUserDep,
    settings: SettingsDep,
    audit: AuditDep,
    jobs: BulkJobStoreDep,
    spool: SpoolDep,
    enqueue: EnqueueDep,
    images: Annotated[list[UploadFile], File(description="Photographs to ingest.")],
    district: Annotated[str | None, Form()] = None,
    category: Annotated[str | None, Form()] = None,
) -> BulkAccepted:
    """The second input channel: a folder of photographs, ingested in the background.

    **202, not 200.** Nobody is waiting on this and section 8c puts it on the
    low-priority queue for exactly that reason. The response is a receipt with
    somewhere to poll.

    **Every file is spooled before the job is created, and the job is created
    before anything is enqueued.** That order is not incidental. A worker that
    picks up a message before its job row exists records a result against
    nothing, and the count silently never reaches its total — a job that hangs
    with no error, which is the worst thing to hand a district office at 9 pm.

    **Rejected files are named, not counted.** "3 of 300 rejected" sends
    somebody scrolling through a folder; the filename and the reason do not.
    """
    if enqueue is None:  # pragma: no cover - only with the queue disabled
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bulk ingestion needs the task queue, which is not configured.",
        )
    if len(images) > MAX_BULK_FILES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"{len(images)} files in one request; the limit is {MAX_BULK_FILES}.",
        )

    job_id = uuid4()
    queued: list[tuple[UUID, str]] = []
    rejected: list[str] = []

    for upload in images:
        name = upload.filename or "(unnamed)"
        payload = await upload.read()
        if not payload:
            rejected.append(f"{name}: empty file")
            continue
        if len(payload) > MAX_UPLOAD_BYTES:
            rejected.append(f"{name}: {len(payload) / 1e6:.1f} MB exceeds the upload limit")
            continue
        scan_id = uuid4()
        if not spool.put(f"bulk:{job_id}:{scan_id}", payload):
            # The spool refused. Unlike the interactive path there is no inline
            # fallback to take: the whole point of this endpoint is that the
            # request returns before the work happens, so a file we cannot hand
            # off is a file we must decline out loud.
            rejected.append(f"{name}: could not be queued (the spool refused the bytes)")
            continue
        queued.append((scan_id, name))

    if not queued:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "No file in this request could be queued.", "rejected": rejected},
        )

    jobs.create(
        BulkJob(
            id=job_id,
            officer_id=user.id,
            total=len(queued),
            created_at=datetime.now(UTC),
        )
    )

    from workers.broker import QUEUE_BULK

    for scan_id, name in queued:
        enqueue(
            "ingest_bulk_image",
            queue=QUEUE_BULK,
            job_id=str(job_id),
            scan_id=str(scan_id),
            officer_id=str(user.id),
            filename=name,
            district=district or user.district,
            category=category,
        )

    audit.record(
        user_id=user.id,
        action="create",
        entity="bulk_job",
        entity_id=str(job_id),
        ip=client_ip(request),
    )

    return BulkAccepted(
        job_id=job_id,
        accepted=len(queued),
        rejected=rejected,
        poll=f"/api/v1/scans/bulk/{job_id}",
    )


@router.get("/bulk/{job_id}", response_model=BulkJobStatus)
async def bulk_status(
    job_id: UUID,
    user: CurrentUserDep,
    jobs: BulkJobStoreDep,
) -> BulkJobStatus:
    """How far through a bulk upload the workers are.

    Visible to the officer who started it and to a supervisor. Not audited:
    section 18 logs who looked at *evidence*, and a progress counter is not
    evidence — writing an audit row per poll would bury the reads that matter
    under thousands that do not.
    """
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such job.")
    if job.officer_id != user.id and not outranks(user.role, "supervisor"):
        # 404 rather than 403: a job id belonging to another officer should not
        # be confirmable by its error code.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such job.")

    return BulkJobStatus(
        job_id=job.id,
        status=job.status,  # type: ignore[arg-type]
        total=job.total,
        completed=job.completed,
        failed=job.failed,
        pending=job.pending,
        scan_ids=list(job.scan_ids),
        errors=list(job.errors),
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


@router.get("/{scan_id}")
async def get_scan(
    scan_id: UUID,
    request: Request,
    user: CurrentUserDep,
    scans: ScanStoreDep,
    audit: AuditDep,
) -> dict[str, Any]:
    """One scan record, with its verdicts.

    **Every read is logged.** Section 18: "Role-based access says who *can* see
    something. An audit log records who *did* ... in an enforcement context, who
    looked at a pending case is exactly the question that eventually gets
    asked."
    """
    row = scans.get(scan_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such scan.")

    audit.record(
        user_id=user.id,
        action="view",
        entity="scan",
        entity_id=str(scan_id),
        ip=client_ip(request),
    )
    return {
        "scan": dict(row),
        "verdicts": scans.verdicts_for(scan_id),
    }


REPORT_FORMATS = ("html", "docx", "pdf")


@router.get("/{scan_id}/report")
async def get_report(
    scan_id: UUID,
    request: Request,
    user: CurrentUserDep,
    scans: ScanStoreDep,
    skus: SkuStoreDep,
    users: UserStoreDep,
    audit: AuditDep,
    objects: ObjectStoreDep,
    enqueue: EnqueueDep,
    format: Annotated[str, Query(pattern="^(html|docx|pdf)$")] = "html",
) -> Response:
    """The per-product report, in the format asked for. Sections 13 and 8c.

    **HTML and DOCX render here; PDF does not.** That split is section 8c's
    300-800 ms rule applied honestly rather than uniformly. `python-docx` writes
    a zip in a few tens of milliseconds and Jinja is faster still, so making an
    officer poll for those would be ceremony. WeasyPrint lays out a full page
    and is the renderer the plan actually puts a budget on, so a PDF is rendered
    by a worker and served from the derived bucket — `202` with a `Retry-After`
    until it exists.

    **A report download is audited as `download_evidence`, not `view`.** Section
    18's question is not "who opened the app" but who took a copy of enforcement
    material out of it, and those two must not be the same row.
    """
    row = scans.get(scan_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such scan.")

    audit.record(
        user_id=user.id,
        action="download_evidence",
        entity="report",
        entity_id=f"{scan_id}:{format}",
        ip=client_ip(request),
    )

    report = _assemble(dict(row), scans=scans, skus=skus, users=users, objects=objects)

    if format == "pdf":
        return _pdf_response(dict(row), report=report, scan_id=scan_id, objects=objects)

    if format == "docx":
        from reports.docx_writer import to_docx

        return Response(
            content=to_docx(report),
            media_type=storage.REPORT_CONTENT_TYPES["docx"],
            headers={"Content-Disposition": f'attachment; filename="akshar-{scan_id}.docx"'},
        )

    from reports.render import to_html

    return HTMLResponse(content=to_html(report))


def _assemble(
    row: dict[str, Any], *, scans: Any, skus: Any, users: Any, objects: Any = None
) -> Any:
    """Build the report model from stored rows only. Section 14."""
    from reports.assemble import from_scan

    sku_id = row.get("sku_id")
    officer_id = row.get("officer_id")
    officer = users.by_id(officer_id) if officer_id else None
    return from_scan(
        scan=row,
        verdicts=scans.verdicts_for(row["id"]),
        pack=load_rulepack(),
        sku=skus.by_id(sku_id) if sku_id else None,
        officer_name=getattr(officer, "full_name", None),
        objects=objects,
    )


def _pdf_response(row: dict[str, Any], *, report: Any, scan_id: UUID, objects: Any) -> Response:
    """Serve a PDF. Always a PDF.

    ---------------------------------------------------------------------------
    WHY THIS NO LONGER ANSWERS 202
    ---------------------------------------------------------------------------
    It used to: cached copy, else enqueue a worker and reply
    `202 {"status": "rendering"}`, which is the correct shape for a slow render
    and is what section 8c's 300-800 ms rule asks for.

    It is the wrong shape for **this** response, because of how the client asks.
    The scan page offers the report as `<a href=... download="scan-<id>.pdf">`,
    and a browser following a `download` link saves whatever comes back under
    that name whatever its status or content type. So a 202 arrived on the
    officer's disk as `scan-<id>.pdf` containing thirty bytes of JSON, and every
    PDF viewer refused it. The same held for the 503 when no queue was
    configured — which is the demonstration stack, where there is no worker.

    A slow response is a smaller problem than a corrupt file. So: serve the
    stored copy when there is one, otherwise render now and store what was
    rendered, so the *next* request gets the cheap path without a worker ever
    being involved. `reports.render.to_pdf` falls back to a pure-Python writer
    where WeasyPrint's native libraries are absent, so "render now" cannot fail
    for the reason it used to.
    """
    key = storage.report_key(str(scan_id), captured_at=row["captured_at"], fmt="pdf")

    payload = storage.get_report(objects, key) if objects is not None else None
    if payload is None:
        from reports.render import to_pdf

        payload = to_pdf(report)
        # Store what we just rendered, rather than asking a worker to render the
        # same document a second time.
        #
        # The first version enqueued `render_report` here as a cache warm-up,
        # which is simply wasteful: the finished PDF is already in hand, and the
        # worker's only job would be to produce it again. Writing the bytes we
        # have is cheaper, needs no broker, and warms the same bucket.
        #
        # It also keeps a request path free of a queue it does not need. That is
        # a smaller claim than the one first written here -- an earlier note in
        # this place asserted that the enqueue could *block* on an unreachable
        # broker and hang the download. That was never verified and is not the
        # behaviour under test: `workers.broker` hands a `StubBroker` to any
        # process with pytest loaded, and `RedisBroker` builds its client
        # lazily. The honest reason is the wasted render, not a hang.
        if objects is not None:
            # A full or unreachable bucket must not lose a report that is
            # already rendered and about to be returned.
            with contextlib.suppress(Exception):
                storage.put_report(
                    objects,
                    payload,
                    scan_id=str(scan_id),
                    captured_at=row["captured_at"],
                    fmt="pdf",
                )

    return Response(
        content=payload,
        media_type=storage.REPORT_CONTENT_TYPES["pdf"],
        headers={"Content-Disposition": f'inline; filename="akshar-{scan_id}.pdf"'},
    )




@router.post("/{scan_id}/corrections", status_code=status.HTTP_201_CREATED)
async def add_correction(
    scan_id: UUID,
    body: CorrectionRequest,
    request: Request,
    user: CurrentUserDep,
    scans: ScanStoreDep,
    reviews: ReviewStoreDep,
    audit: AuditDep,
) -> dict[str, Any]:
    """Record an officer override.

    **Append-only, and the scan is not touched.** Section 5: "Scans are
    immutable facts. Corrections are append-only rows, never edits. Nothing is
    ever updated in place, so nothing can conflict." That is also the answer to
    "what is your merge strategy" — there is nothing to merge.

    Section 14: each of these is a labelled training example produced by
    somebody already doing the job.
    """
    if scans.get(scan_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such scan.")

    stored = reviews.correct(
        Correction(
            scan_id=scan_id,
            officer_id=user.id,
            box_index=body.box_index,
            from_field=body.from_field,
            to_field=body.to_field,
        )
    )
    audit.record(
        user_id=user.id,
        action="correct",
        entity="scan",
        entity_id=str(scan_id),
        ip=client_ip(request),
    )
    return {
        "scan_id": str(scan_id),
        "box_index": stored.box_index,
        "from_field": stored.from_field,
        "to_field": stored.to_field,
        "officer_id": str(user.id),
        "created_at": stored.created_at.isoformat(),
        "note": "Recorded as a new row; the scan itself is unchanged.",
    }


@router.post(
    "/{scan_id}/review",
    response_model=ReviewResolutionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("supervisor"))],
)
async def resolve_review(
    scan_id: UUID,
    body: ReviewResolutionRequest,
    request: Request,
    user: CurrentUserDep,
    scans: ScanStoreDep,
    reviews: ReviewStoreDep,
    audit: AuditDep,
) -> ReviewResolutionResponse:
    """Settle one REVIEW verdict. Section 8b, section 11's Q6.

    **Supervisor and above.** The other officer-facing write on this router,
    `corrections`, is open to any signed-in officer because relabelling a box is
    a statement about what the photograph shows. This is not that: it is a
    compliance conclusion recorded against an enforcement record where the
    rulepack deliberately declined to reach one, and section 11 already puts the
    review queue on the supervisor's dashboard rather than the officer's scan
    screen. The guard is here rather than in the navigation because hiding a
    link is courtesy and `require_role` is the control.

    **The scan is not touched.** Section 5 makes it an immutable fact whose hash
    is in the evidence chain; a row that rewrote the verdict would break
    `verify_chain` at that record, and correctly so. What changes is that the
    scan stops appearing in the queue once every rule that asked for a human has
    an answer — which is what `outstanding` reports.

    A rule that never asked for review is refused with 409 rather than accepted
    quietly. Accepting it would put a decision in the retraining feed that no
    verdict ever prompted, and section 14's whole argument for that feed is that
    every row in it came from somebody doing the actual job.
    """
    if scans.get(scan_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such scan.")

    verdicts = scans.verdicts_for(scan_id)
    awaiting = {
        verdict["rule_id"]
        for verdict in verdicts
        if verdict.get("status") == "REVIEW" and not verdict.get("advisory")
    }
    if body.rule_id not in awaiting:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Rule {body.rule_id!r} on this scan is not awaiting review. "
                f"Awaiting: {', '.join(sorted(awaiting)) or 'nothing'}."
            ),
        )

    stored = reviews.resolve(
        ReviewResolution(
            scan_id=scan_id,
            rule_id=body.rule_id,
            decision=body.decision,
            officer_id=user.id,
            note=body.note,
        )
    )
    audit.record(
        user_id=user.id,
        action="resolve_review",
        entity="scan",
        entity_id=str(scan_id),
        ip=client_ip(request),
    )
    settled = {resolution.rule_id for resolution in reviews.resolutions_for(scan_id)}
    return ReviewResolutionResponse(
        scan_id=scan_id,
        rule_id=stored.rule_id,
        decision=stored.decision,
        officer_id=stored.officer_id,
        resolved_at=stored.resolved_at,
        outstanding=sorted(awaiting - settled),
    )
