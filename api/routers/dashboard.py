"""The dashboard, faceted search, and the violation summary. AKSHAR.md sections 11, 12, 13a.

Every route here is thin on purpose. It parses the four global filters, asks the
store for facts, and hands them to `api.analytics`. No counting happens in this
module — the same arithmetic has to serve the JSON API, the CSV export and the
PDF summary, and three implementations of "non-compliance rate" is three chances
for a department to be given three different numbers for one morning.

**Role split, from section 11's own table.** `/search` is officer-and-above,
because an officer needs to look up a pack they scanned. Everything under
`/dashboard` and `/summary` is supervisor-and-above: these views aggregate
across officers, and "which officers are active" is a performance-management
question, not an enforcement one.

**Every table paginates server-side and exports to CSV** — section 11's build
rule, and the reason for the `?format=csv` parameter rather than a separate
export route. Officials copy numbers into reports; a table they cannot paste is
a table they will retype by hand and get wrong.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from api.analytics import (
    ScanFacts,
    ScanFilters,
    brand_detail,
    by_brand,
    by_category,
    by_district,
    by_rule,
    health,
    overview,
    review_queue,
    summary,
)
from api.deps import (
    AuditDep,
    CurrentUserDep,
    ReviewStoreDep,
    ScanStoreDep,
    client_ip,
    require_role,
)
from api.schemas import CurrentUser

router = APIRouter(prefix="/api/v1", tags=["dashboard"])

SupervisorDep = Annotated[CurrentUser, Depends(require_role("supervisor"))]


def filters_from_query(
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    district: str | None = None,
    category: str | None = None,
    severity: Annotated[Literal["low", "medium", "high"] | None, Query()] = None,
    brand: str | None = None,
    rule_id: str | None = None,
    status_filter: Annotated[
        Literal["PASS", "FAIL", "REVIEW"] | None, Query(alias="status")
    ] = None,
) -> ScanFilters:
    """The four global filters, as URL parameters.

    Section 11: *"Each is a URL parameter, so any view can be shared as a link —
    which matters more than it sounds, because that's how a finding gets
    escalated to a controller."* Shared as a dependency so every view accepts
    exactly the same set and none can quietly ignore one.
    """
    return ScanFilters(
        date_from=date_from,
        date_to=date_to,
        district=district,
        category=category,
        severity=severity,
        brand=brand,
        rule_id=rule_id,
        status=status_filter,
    )


FiltersDep = Annotated[ScanFilters, Depends(filters_from_query)]


def _csv_response(rows: list[dict[str, Any]], filename: str) -> Response:
    """A CSV of exactly the rows the JSON view returned.

    Nested values are JSON-encoded rather than dropped, so `top_brands` survives
    the export in a form a spreadsheet shows as text instead of silently losing
    a column between the screen and the report.
    """
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (
                        ""
                        if value is None
                        else value
                        if isinstance(value, str | int | float | bool)
                        else repr(value)
                    )
                    for key, value in row.items()
                }
            )
    # utf-8-sig: Excel on a Windows machine in a district office opens plain
    # UTF-8 CSV as mojibake, and half these columns are brand names in
    # Devanagari. The BOM is what makes the export usable where it is used.
    return Response(
        content=buffer.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _table(
    rows: list[dict[str, Any]],
    *,
    fmt: str,
    filename: str,
    limit: int,
    offset: int,
) -> Any:
    """Server-side pagination, with CSV escaping it deliberately.

    An export that returns only the page you are looking at is the export people
    complain about, so `format=csv` serialises the whole filtered result. That is
    a considered exception to the pagination rule, not an oversight.
    """
    if fmt == "csv":
        return _csv_response(rows, filename)
    return {
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        "rows": rows[offset : offset + limit],
    }


def _audit_export(
    audit: AuditDep, user: CurrentUser, request: Request, fmt: str, entity_id: str
) -> None:
    """Section 18: `access_log` is written on every record view **and export**.

    An export is the event that actually matters — it is the moment enforcement
    data leaves the system — so it is logged as `export`, distinctly from a view.
    """
    if fmt == "csv":
        audit.record(
            user_id=user.id,
            action="export",
            entity="dashboard",
            entity_id=entity_id,
            ip=client_ip(request),
        )


def _facts(scans: ScanStoreDep, filters: ScanFilters) -> list[ScanFacts]:
    return scans.facts(filters)


# ---------------------------------------------------------------------------
# Overview — Q1, Q6, Q8
# ---------------------------------------------------------------------------


@router.get("/dashboard/overview")
async def dashboard_overview(
    user: SupervisorDep,
    scans: ScanStoreDep,
    reviews: ReviewStoreDep,
    filters: FiltersDep,
) -> dict[str, Any]:
    """Five tiles, a trend, the top eight rules, and the review queue.

    The previous period is fetched only when the filters bound one. An unbounded
    "all time" view has no previous period, and the tiles say so with a null
    change rather than comparing against a window nobody asked for.
    """
    current = _facts(scans, filters)
    prior = filters.previous_period()
    previous = _facts(scans, prior) if prior else None
    return overview(current, previous, resolved=reviews.resolved_rules())


# ---------------------------------------------------------------------------
# Brands — Q3, and Q7 in the detail view
# ---------------------------------------------------------------------------


@router.get("/dashboard/brands")
async def dashboard_brands(
    request: Request,
    user: SupervisorDep,
    scans: ScanStoreDep,
    audit: AuditDep,
    filters: FiltersDep,
    format: Literal["json", "csv"] = "json",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Any:
    rows = by_brand(_facts(scans, filters))
    _audit_export(audit, user, request, format, "brands")
    return _table(rows, fmt=format, filename="brands.csv", limit=limit, offset=offset)


@router.get("/dashboard/brands/{brand}")
async def dashboard_brand_detail(
    brand: str,
    user: SupervisorDep,
    scans: ScanStoreDep,
    filters: FiltersDep,
) -> dict[str, Any]:
    """Q7 — the before-and-after view.

    Section 11 calls this *"the most persuasive artefact this system can
    produce, because it shows enforcement working"*. A 404 here means we have no
    scans of that brand in the filtered window, which is a different statement
    from "that brand does not exist" — the message says so.
    """
    detail = brand_detail(_facts(scans, filters), brand)
    if detail["scans"] == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No scans of {brand!r} in this window. Widen the date range before concluding anything.",
        )
    return detail


# ---------------------------------------------------------------------------
# Rules — Q2
# ---------------------------------------------------------------------------


@router.get("/dashboard/rules")
async def dashboard_rules(
    request: Request,
    user: SupervisorDep,
    scans: ScanStoreDep,
    audit: AuditDep,
    filters: FiltersDep,
    format: Literal["json", "csv"] = "json",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Any:
    rows = by_rule(_facts(scans, filters))
    _audit_export(audit, user, request, format, "rules")
    return _table(rows, fmt=format, filename="rules.csv", limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Categories — Q4
# ---------------------------------------------------------------------------


@router.get("/dashboard/categories")
async def dashboard_categories(
    request: Request,
    user: SupervisorDep,
    scans: ScanStoreDep,
    audit: AuditDep,
    filters: FiltersDep,
    format: Literal["json", "csv"] = "json",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Any:
    rows = by_category(_facts(scans, filters))
    _audit_export(audit, user, request, format, "categories")
    return _table(rows, fmt=format, filename="categories.csv", limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Districts — Q5
# ---------------------------------------------------------------------------


@router.get("/dashboard/districts")
async def dashboard_districts(
    request: Request,
    user: SupervisorDep,
    scans: ScanStoreDep,
    audit: AuditDep,
    filters: FiltersDep,
    format: Literal["json", "csv"] = "json",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Any:
    rows = by_district(_facts(scans, filters))
    _audit_export(audit, user, request, format, "districts")
    return _table(rows, fmt=format, filename="districts.csv", limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# System health — Q8
# ---------------------------------------------------------------------------


@router.get("/dashboard/health")
async def dashboard_health(
    user: SupervisorDep,
    scans: ScanStoreDep,
    filters: FiltersDep,
) -> dict[str, Any]:
    """Not `/healthz`. That one answers "is the process up"; this one answers
    "is the tool still reading labels as well as it did last month"."""
    return health(_facts(scans, filters))


# ---------------------------------------------------------------------------
# Review queue — Q6
# ---------------------------------------------------------------------------


@router.get("/dashboard/review")
async def dashboard_review(
    user: SupervisorDep,
    scans: ScanStoreDep,
    reviews: ReviewStoreDep,
    filters: FiltersDep,
    limit: int = Query(25, ge=1, le=200),
) -> dict[str, Any]:
    """Oldest first. Section 8c: the review queue is a worklist, not a chart.

    Rules a supervisor has already settled through `POST /scans/{id}/review`
    are dropped, and a scan whose every REVIEW rule is settled leaves the list
    entirely. That is the whole point of the resolution endpoint: without this
    argument the queue is rebuilt from verdicts on every load and the work
    reappears the moment the page is refreshed.
    """
    rows = review_queue(_facts(scans, filters), resolved=reviews.resolved_rules(), limit=limit)
    return {"total": len(rows), "rows": rows}


# ---------------------------------------------------------------------------
# Faceted search — officer and above
# ---------------------------------------------------------------------------


@router.get("/search")
async def search(
    request: Request,
    user: CurrentUserDep,
    scans: ScanStoreDep,
    audit: AuditDep,
    filters: FiltersDep,
    format: Literal["json", "csv"] = "json",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Any:
    """Section 12: brand, barcode, date, district, rule, status.

    Newest first — the opposite of the review queue, and for the opposite
    reason. Search is "what did I just scan"; the queue is "what has waited
    longest".
    """
    found = sorted(_facts(scans, filters), key=lambda s: s.captured_at, reverse=True)
    rows = [
        {
            "scan_id": str(s.id),
            "captured_at": s.captured_at.isoformat(),
            "brand": s.brand,
            "parent": s.parent,
            "category": s.category,
            "district": s.district,
            "source": s.source,
            "degradation_tier": s.degradation_tier,
            "coverage": s.coverage,
            "status": (
                "FAIL"
                if s.is_non_compliant
                else "REVIEW"
                if s.needs_review
                else "PASS"
                if s.is_conclusive
                else "NO_DATA"
            ),
            "high_severity": s.high_severity_failures,
            "failed_rules": ";".join(v.rule_id for v in s.failures),
        }
        for s in found
    ]
    _audit_export(audit, user, request, format, "search")
    return _table(rows, fmt=format, filename="search.csv", limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Violation summary — section 13a
# ---------------------------------------------------------------------------


@router.get("/summary")
async def violation_summary(
    request: Request,
    user: SupervisorDep,
    scans: ScanStoreDep,
    audit: AuditDep,
    filters: FiltersDep,
) -> dict[str, Any]:
    """The dashboard's printable form, as JSON.

    Section 13a: *"The dashboard is the live view; the summary is its printable
    form."* The PDF and DOCX renderings take this exact structure, so a number
    in the report and the same number on screen come from one computation.
    """
    audit.record(
        user_id=user.id,
        action="view",
        entity="summary",
        entity_id=None,
        ip=client_ip(request),
    )
    return summary(_facts(scans, filters), filters=filters)


@router.get("/summary/report")
async def violation_summary_report(
    request: Request,
    user: SupervisorDep,
    scans: ScanStoreDep,
    audit: AuditDep,
    filters: FiltersDep,
    format: Literal["html", "docx", "pdf"] = "html",
) -> Response:
    """The same summary, laid out to be filed. Sections 13a, 13 and 8c.

    **Built over `analytics.summary()`, the identical call the JSON route
    makes.** Section 13a asks for the dashboard's printable form, and the cheap
    way to build one is a second query shaped for printing — which is how a
    department ends up with a tabled document and a screen that disagree about
    the same week. There is one computation and three layouts of it.

    **All three formats render inline here, and the per-product report's PDF
    does not — deliberately.** That route defers because an officer requests a
    PDF from a shelf, on a phone, one product at a time, and the artefact has a
    scan to be stored against. A summary has neither property: it is an
    aggregate over whatever the filters selected at the instant it was asked
    for, so there is no scan it belongs to and no capture date to partition it
    under, and storing one would mean answering tomorrow's request with
    yesterday's numbers. It is also a deliberate export by a supervisor at a
    desk, not a step in a shelf-side workflow. So the ~500 ms is spent in the
    request, and where WeasyPrint cannot run the route says which two formats
    need no native libraries rather than failing.
    """
    from reports import summary_model

    audit.record(
        user_id=user.id,
        action="download_evidence",
        entity="summary",
        entity_id=format,
        ip=client_ip(request),
    )

    report = summary_model.build(
        summary(_facts(scans, filters), filters=filters),
        prepared_by=user.full_name,
    )

    if format == "docx":
        from reports.docx_writer import summary_to_docx

        return Response(
            content=summary_to_docx(report),
            media_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            headers={
                "Content-Disposition": 'attachment; filename="akshar-violation-summary.docx"'
            },
        )

    from reports.render import RendererUnavailableError, to_html, to_pdf

    if format == "pdf":
        try:
            payload = to_pdf(report, template="summary.html")
        except RendererUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    f"{exc} Request ?format=docx or ?format=html, which render "
                    f"immediately and need no native libraries."
                ),
            ) from exc
        return Response(
            content=payload,
            media_type="application/pdf",
            headers={
                "Content-Disposition": 'inline; filename="akshar-violation-summary.pdf"'
            },
        )

    return Response(
        content=to_html(report, template="summary.html"), media_type="text/html; charset=utf-8"
    )


__all__ = ["router"]
