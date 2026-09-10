"""The background actors. AKSHAR.md sections 8c and 12.

Run them with:

    dramatiq workers.tasks --processes 2 --threads 8

**Every actor here is something an officer is not waiting for.** Section 8c
draws the line: *"Nothing delays the verdict. Report render, dashboard counters,
`scan_count` and evidence upload all come off the critical path."* If a function
below ever becomes something a response blocks on, it is in the wrong file.

**The bulk actor calls the same `run_scan` the HTTP route calls**, which is
section 12's requirement stated as an import rather than as a promise: *"Bulk
runs the identical B1-B10 sequence server-side. If it diverges, two products
exist and only one is tested."*

**Actor arguments are JSON, so they are strings.** UUIDs and datetimes are
passed as text and parsed here. A message that outlives a deploy has to be
decodable by the new code, and `str` is the only type that is certainly still
the same type next week.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import dramatiq

from workers.broker import QUEUE_BULK, QUEUE_SCAN

logger = logging.getLogger("akshar.workers")

MAX_RETRIES = 3
"""Three attempts, then the dead-letter queue.

Not more: every actor here is either idempotent-by-key or a counter, and a
message that has failed three times is failing for a reason retries do not fix —
MinIO down, a corrupt image, a schema mismatch. Retrying it fifty times just
delays the moment somebody looks at the logs.
"""


def _resources() -> dict[str, Any]:
    """Resolve the worker's stores and clients. Imported late, on purpose.

    A worker process boots by importing this module; importing `api.deps` at
    module scope would build the stores before `dramatiq` has finished setting
    up, and would make `workers.tasks` unimportable in any context where the API
    package is only half-configured. Resolving per call costs a dict lookup —
    every factory behind it is `lru_cache`d.
    """
    from api.deps import get_scan_store, get_sku_store
    from api.deps.resources import get_bulk_jobs, get_object_store, get_spool

    return {
        "scans": get_scan_store(),
        "skus": get_sku_store(),
        "spool": get_spool(),
        "objects": get_object_store(),
        "jobs": get_bulk_jobs(),
    }


# ---------------------------------------------------------------------------
# scan queue — an officer is looking at the screen this came from
# ---------------------------------------------------------------------------


@dramatiq.actor(queue_name=QUEUE_SCAN, max_retries=MAX_RETRIES)
def store_evidence(
    *,
    scan_id: str,
    captured_at: str,
    tier: str,
    sha256: str | None = None,
    frame: int = 0,
) -> None:
    """Collect the spooled bytes and write them to the evidence bucket.

    The bytes were redacted and hashed synchronously, before the scan row was
    written — see `api/scanning.py`. This actor moves them; it never changes
    them. **The digest is re-checked against what the row already claims**, and
    a mismatch is raised rather than logged, because a chained record asserting
    a hash the object does not have is a tamper signal, and dropping it here
    would mean the alarm fires months later during a verification sweep with
    nobody left who remembers the upload.

    `take` removes the entry, so a duplicate delivery finds nothing and returns
    quietly. That is the intended behaviour: the evidence bucket is versioned
    and write-once, and a second PUT would create a second version of an object
    that should have exactly one — which reads to an auditor as an overwrite.
    """
    from evidence import storage

    resources = _resources()
    # `frame` defaults to 0 and frame 0 spools under the bare scan id, so a
    # message enqueued before multi-frame capture existed is delivered to
    # exactly the slot it named.
    slot = scan_id if frame == 0 else f"{scan_id}:frame{frame}"
    payload = resources["spool"].take(slot)
    if payload is None:
        logger.warning(
            "evidence for scan %s (frame %d) was not in the spool; either it "
            "was already uploaded or the spool entry expired",
            scan_id,
            frame,
        )
        return

    if sha256 is not None and storage.sha256_of(payload) != sha256:
        raise ValueError(
            f"spooled bytes for scan {scan_id} do not match the digest recorded "
            f"in its chained row; refusing to upload"
        )

    objects = resources["objects"]
    if objects is None:
        raise RuntimeError("no object store configured; evidence cannot be written")

    moment = datetime.fromisoformat(captured_at)
    storage.ensure_buckets(objects)
    storage.put_evidence(
        objects,
        payload,
        scan_id=scan_id,
        key=storage.frame_key(scan_id, frame, captured_at=moment),
        captured_at=moment,
        tier=tier,  # type: ignore[arg-type]
    )
    logger.info("stored evidence for scan %s (%d bytes, %s)", scan_id, len(payload), tier)


@dramatiq.actor(queue_name=QUEUE_SCAN, max_retries=MAX_RETRIES)
def store_annotation(*, scan_id: str, captured_at: str) -> None:
    """Write the annotated label to the derived bucket. Sections 13 and 6.

    **No digest re-check, unlike `store_evidence`, and the difference is the
    point.** That actor guards a hash the scan row has already committed to
    inside a chain; this one carries a drawing that is in no chain at all,
    because it is derived rather than evidential. There is nothing here for a
    substitution to contradict.

    A duplicate delivery overwrites with identical bytes, which is harmless: the
    derived bucket is not versioned.
    """
    from evidence import storage

    resources = _resources()
    payload = resources["spool"].take(f"annot:{scan_id}")
    if payload is None:
        logger.warning("annotation for scan %s was not in the spool", scan_id)
        return

    objects = resources["objects"]
    if objects is None:
        raise RuntimeError("no object store configured; the annotation cannot be written")

    storage.ensure_buckets(objects)
    storage.put_annotation(
        objects,
        payload,
        scan_id=scan_id,
        captured_at=datetime.fromisoformat(captured_at),
    )
    logger.info("stored annotation for scan %s (%d bytes)", scan_id, len(payload))


@dramatiq.actor(queue_name=QUEUE_SCAN, max_retries=MAX_RETRIES)
def render_report(*, scan_id: str, fmt: str = "pdf") -> None:
    """Render the per-product report and put it in the derived bucket. Section 8c.

    On the `scan` queue rather than `bulk` even though nobody blocks on it: an
    officer who has pressed "report" is standing there watching for the link,
    which is a different kind of waiting from an overnight import but is still
    waiting. Section 8c lists "report requests" under the high queue explicitly.

    **This is the only renderer that runs out of process, and PDF is the reason.**
    HTML and DOCX are served inline by the route because they cost tens of
    milliseconds; WeasyPrint lays out a full page and is the 300-800 ms the plan
    budgets for. Rendering the cheap formats here too would mean an officer
    polling for a document that was ready before the poll.

    A missing renderer raises, so the message retries and then dead-letters with
    the installation hint attached — rather than writing a zero-byte object that
    the route would happily serve as a finished report.
    """
    from evidence import storage
    from reports.assemble import from_scan
    from reports.render import to_pdf
    from rules.loader import load_rulepack

    resources = _resources()
    scans = resources["scans"]
    row = scans.get(UUID(scan_id))
    if row is None:
        logger.warning("report requested for unknown scan %s", scan_id)
        return

    sku_id = row.get("sku_id")
    officer_id = row.get("officer_id")
    from api.deps import get_user_store

    officer = get_user_store().by_id(officer_id) if officer_id else None
    report = from_scan(
        scan=dict(row),
        verdicts=scans.verdicts_for(UUID(scan_id)),
        pack=load_rulepack(),
        sku=resources["skus"].by_id(sku_id) if sku_id else None,
        officer_name=getattr(officer, "full_name", None),
        objects=resources["objects"],
    )

    if fmt == "docx":
        from reports.docx_writer import to_docx

        payload = to_docx(report)
    else:
        payload = to_pdf(report)

    objects = resources["objects"]
    if objects is None:
        raise RuntimeError("no object store configured; the report cannot be stored")

    storage.ensure_buckets(objects)
    stored = storage.put_report(
        objects, payload, scan_id=scan_id, captured_at=row["captured_at"], fmt=fmt
    )
    logger.info("rendered %s report for scan %s (%d bytes)", fmt, scan_id, stored.size_bytes)


# ---------------------------------------------------------------------------
# bulk queue — nobody is waiting; correctness matters more than latency
# ---------------------------------------------------------------------------


@dramatiq.actor(queue_name=QUEUE_BULK, max_retries=MAX_RETRIES)
def ingest_bulk_image(
    *,
    job_id: str,
    scan_id: str,
    officer_id: str,
    filename: str = "",
    district: str | None = None,
    category: str | None = None,
    captured_at: str | None = None,
) -> None:
    """Scan one image from a bulk upload. Identical path to the HTTP route.

    A failure is recorded against the job and **swallowed**, not re-raised. That
    is the opposite of the usual instinct and it is deliberate: one unreadable
    file out of three hundred must not retry three times and then dead-letter,
    leaving a job that never reaches its total and an officer refreshing a page
    forever. The error text lands on the job receipt where a person can see
    which file failed and why.

    Genuine infrastructure failures still retry, because they raise before this
    actor catches anything — the spool being empty and MinIO being down both
    surface from `store_evidence`, on its own queue, with its own retries.
    """
    from api.config import get_settings
    from api.scanning import ScanRequest, run_scan

    resources = _resources()
    jobs = resources["jobs"]
    payload = resources["spool"].take(f"bulk:{job_id}:{scan_id}")
    if payload is None:
        jobs.record_result(
            UUID(job_id),
            error=f"{filename or scan_id}: image bytes expired from the spool before ingestion",
        )
        return

    try:
        result = run_scan(
            ScanRequest(
                payload=payload,
                officer_id=UUID(officer_id),
                scan_id=UUID(scan_id),
                source="bulk_image",
                district=district,
                category=category,
                captured_at=datetime.fromisoformat(captured_at) if captured_at else None,
            ),
            scans=resources["scans"],
            skus=resources["skus"],
            settings=get_settings(),
            spool=resources["spool"],
            objects=resources["objects"],
            enqueue=_enqueue,
        )
    except ValueError as exc:
        # A malformed image. Expected, common in a folder of 300 files, and not
        # something a retry will fix.
        jobs.record_result(UUID(job_id), error=f"{filename or scan_id}: {exc}")
        return

    jobs.record_result(UUID(job_id), scan_id=result.scan_id)


@dramatiq.actor(queue_name=QUEUE_BULK, max_retries=MAX_RETRIES)
def bump_scan_count(*, sku_id: str) -> None:
    """Increment a SKU's scan counter. Section 8c puts it here for a reason.

    It feeds `GET /skus/cache`, the offline warm list an officer's phone
    downloads before a drive — "retail is heavily long-tailed, so a few
    megabytes covers close to 90% of what's on those shelves" (section 5). A
    counter that is thirty seconds stale changes nothing about which SKUs are
    popular; a counter that is `UPDATE ... SET scan_count = scan_count + 1`
    inside the scan response adds a row lock to the hot path of an interactive
    request, and on a shelf of forty packets it is the *same* row forty times.
    """
    _resources()["skus"].bump_scan_count(UUID(sku_id))


def _enqueue(task: str, *, queue: str, **kwargs: Any) -> None:
    """Actors enqueueing actors — bulk ingestion still defers its own uploads."""
    from api.deps.resources import enqueue as send

    send(task, queue=queue, **kwargs)


__all__ = [
    "MAX_RETRIES",
    "bump_scan_count",
    "ingest_bulk_image",
    "render_report",
    "store_annotation",
    "store_evidence",
]
