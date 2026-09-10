"""Dashboard routes over HTTP — AKSHAR.md sections 11, 12, 18.

`test_analytics.py` proves the arithmetic. This file proves the routes: who may
see each view, that the four global filters actually reach the store, that CSV
export works and is logged, and that a supervisor view cannot be reached with an
officer's token.

The store here is the real `InMemoryScanStore` joined to a real
`InMemorySkuStore`, not a stub, so the SKU join that produces `brand` and
`parent` is exercised rather than assumed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.config import Settings, get_settings
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
NOW = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)

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
ADMIN = UserRecord(
    id=uuid4(),
    email="admin@akshar.test",
    full_name="Controller",
    password_hash=hash_password("admin pass"),
    role="admin",
)

PARLE = SkuRecord(
    id=uuid4(),
    brand="Parle",
    brand_group="Parle Products",
    variant="G",
    pack_size="100 g",
    category="biscuits",
    barcode="8901030865275",
)
CEMENT = SkuRecord(
    id=uuid4(),
    brand="Konark",
    brand_group=None,
    variant=None,
    pack_size="50 kg",
    category="cement",
    barcode="8901030000001",
)


def _scan_payload(sku, *, when, district, category, cache_hit=False, latency=561):
    return {
        "id": uuid4(),
        "officer_id": OFFICER.id,
        "sku_id": sku.id,
        "district": district,
        "category": category,
        "source": "photo",
        "degradation_tier": "L0",
        "declaration_set": {"source": "photo", "declarations": []},
        "coverage": 0.92,
        "latency_ms": latency,
        "cache_hit": cache_hit,
        "image_key": None,
        "image_sha256": None,
        "geo": None,
        "captured_at": when,
        "model_versions": {"det": "rtmdet-ins-tiny"},
        "rulepack_version": "lmpc_2011@1.0.0",
    }


def _verdicts(*specs):
    return [
        {
            "rule_id": rule_id,
            "rule_ref": "Rule 6(1)(e)",
            "status": status,
            "severity": severity,
            "advisory": advisory,
            "suppressed_by": None,
            "expected": "present",
            "message": "",
        }
        for rule_id, status, severity, advisory in specs
    ]


@pytest.fixture
def stores():
    skus = InMemorySkuStore()
    skus.add(PARLE)
    skus.add(CEMENT)

    scans = InMemoryScanStore(skus=skus)
    users = InMemoryUserStore()
    audit = InMemoryAuditLog()
    reviews = InMemoryReviewStore()
    for user in (OFFICER, SUPERVISOR, ADMIN):
        users.add(user)

    # Two failing Parle scans in Khordha, one passing cement scan in Cuttack,
    # and one older Parle scan so the trend and the previous period have data.
    failing = _scan_payload(PARLE, when=NOW, district="Khordha", category="biscuits")
    scans.save(failing)
    scans.save_verdicts(
        failing["id"],
        _verdicts(
            ("LMPC.MRP.PRESENT", "FAIL", "high", False),
            ("LMPC.UNIT.ML", "FAIL", "low", True),
        ),
    )

    review = _scan_payload(PARLE, when=NOW, district="Khordha", category="biscuits")
    scans.save(review)
    scans.save_verdicts(review["id"], _verdicts(("LMPC.MRP.HEIGHT", "REVIEW", "high", False)))

    passing = _scan_payload(
        CEMENT, when=NOW, district="Cuttack", category="cement", cache_hit=True, latency=60
    )
    scans.save(passing)
    scans.save_verdicts(passing["id"], _verdicts(("LMPC.MRP.PRESENT", "PASS", "high", False)))

    older = _scan_payload(
        PARLE, when=NOW - timedelta(days=20), district="Khordha", category="biscuits"
    )
    scans.save(older)
    scans.save_verdicts(older["id"], _verdicts(("LMPC.MRP.PRESENT", "FAIL", "high", False)))

    return scans, users, skus, audit, reviews


@pytest.fixture
def client(stores):
    scans, users, skus, audit, reviews = stores
    app.dependency_overrides[get_scan_store] = lambda: scans
    app.dependency_overrides[get_user_store] = lambda: users
    app.dependency_overrides[get_sku_store] = lambda: skus
    app.dependency_overrides[get_audit_log] = lambda: audit
    app.dependency_overrides[get_review_store] = lambda: reviews
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _auth(user: UserRecord = SUPERVISOR) -> dict[str, str]:
    token = create_token(subject=user.id, role=user.role, settings=SETTINGS)  # type: ignore[arg-type]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Access control — section 11's own role table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/dashboard/overview",
        "/api/v1/dashboard/brands",
        "/api/v1/dashboard/rules",
        "/api/v1/dashboard/categories",
        "/api/v1/dashboard/districts",
        "/api/v1/dashboard/health",
        "/api/v1/dashboard/review",
        "/api/v1/summary",
        "/api/v1/summary/report",
    ],
)
def test_dashboard_views_are_closed_to_officers(client, path):
    """These aggregate across officers; that is a supervisor's question."""
    assert client.get(path, headers=_auth(OFFICER)).status_code == 403
    assert client.get(path, headers=_auth(SUPERVISOR)).status_code == 200


@pytest.mark.parametrize(
    "path", ["/api/v1/dashboard/overview", "/api/v1/summary", "/api/v1/search"]
)
def test_an_admin_reaches_every_supervisor_view(client, path):
    """Roles nest through ROLE_RANK. Per-route allow-lists are how an admin
    ends up locked out of the dashboard they are accountable for."""
    assert client.get(path, headers=_auth(ADMIN)).status_code == 200


def test_search_is_open_to_officers(client):
    """An officer must be able to find the pack they scanned this morning."""
    assert client.get("/api/v1/search", headers=_auth(OFFICER)).status_code == 200


@pytest.mark.parametrize("path", ["/api/v1/dashboard/overview", "/api/v1/search"])
def test_every_dashboard_route_requires_a_token(client, path):
    assert client.get(path).status_code == 401


# ---------------------------------------------------------------------------
# The views
# ---------------------------------------------------------------------------


def test_the_overview_answers_its_five_tiles(client):
    body = client.get("/api/v1/dashboard/overview", headers=_auth()).json()
    tiles = body["tiles"]
    assert tiles["scans"]["value"] == 4
    assert tiles["unique_skus"]["value"] == 2
    # Two non-compliant of four conclusive. The advisory FAIL on the first scan
    # adds nothing, and the REVIEW scan is conclusive without being a failure.
    assert tiles["non_compliance_rate"]["value"] == 0.5
    assert tiles["high_severity_open"]["value"] == 2
    assert tiles["awaiting_review"]["value"] == 1


def test_the_overview_carries_the_review_queue_on_the_front_page(client):
    body = client.get("/api/v1/dashboard/overview", headers=_auth()).json()
    assert len(body["review_queue"]) == 1
    assert body["review_queue"][0]["rules"] == ["LMPC.MRP.HEIGHT"]


def test_the_brands_view_joins_the_parent_company(client):
    """The SKU join is what makes a legal notice addressable."""
    body = client.get("/api/v1/dashboard/brands", headers=_auth()).json()
    parle = next(row for row in body["rows"] if row["brand"] == "Parle")
    assert parle["parent"] == "Parle Products"
    assert parle["scans"] == 3


def test_brand_detail_404s_with_a_message_about_the_window(client):
    """"No scans in this window" is not the same statement as "no such brand"."""
    response = client.get("/api/v1/dashboard/brands/Nestle", headers=_auth())
    assert response.status_code == 404
    assert "window" in response.json()["detail"].lower()


def test_the_categories_view_shows_cement_beside_biscuits(client):
    body = client.get("/api/v1/dashboard/categories", headers=_auth()).json()
    names = {row["category"] for row in body["rows"]}
    assert names == {"biscuits", "cement"}


def test_the_health_view_splits_cache_hits_from_misses(client):
    body = client.get("/api/v1/dashboard/health", headers=_auth()).json()
    assert body["median_latency_ms_cache_hit"] == 60
    assert body["median_latency_ms_cache_miss"] == 561


# ---------------------------------------------------------------------------
# Filters — every one is a URL parameter
# ---------------------------------------------------------------------------


def test_the_district_filter_reaches_the_store(client):
    body = client.get(
        "/api/v1/dashboard/overview", params={"district": "Cuttack"}, headers=_auth()
    ).json()
    assert body["tiles"]["scans"]["value"] == 1
    assert body["tiles"]["non_compliance_rate"]["value"] == 0.0


def test_the_date_window_excludes_older_scans(client):
    body = client.get(
        "/api/v1/dashboard/overview",
        params={"from": "2026-09-01", "to": "2026-09-30"},
        headers=_auth(),
    ).json()
    assert body["tiles"]["scans"]["value"] == 3


def test_a_bounded_window_produces_a_previous_period_comparison(client):
    """The 40-day-old scan lands in the preceding window, not this one."""
    body = client.get(
        "/api/v1/dashboard/overview",
        params={"from": "2026-09-01", "to": "2026-09-30"},
        headers=_auth(),
    ).json()
    assert body["tiles"]["scans"]["previous"] == 1


def test_an_unbounded_window_reports_no_change_rather_than_inventing_one(client):
    body = client.get("/api/v1/dashboard/overview", headers=_auth()).json()
    assert body["tiles"]["non_compliance_rate"]["previous"] is None
    assert body["tiles"]["non_compliance_rate"]["change"] is None


def test_the_severity_filter_selects_on_failures(client):
    body = client.get(
        "/api/v1/search", params={"severity": "high"}, headers=_auth(OFFICER)
    ).json()
    assert body["total"] == 2


def test_the_rule_filter_drills_into_one_rule(client):
    body = client.get(
        "/api/v1/search", params={"rule_id": "LMPC.MRP.HEIGHT"}, headers=_auth(OFFICER)
    ).json()
    assert body["total"] == 1


def test_the_status_filter_finds_the_review_queue(client):
    body = client.get(
        "/api/v1/search", params={"status": "REVIEW"}, headers=_auth(OFFICER)
    ).json()
    assert body["total"] == 1
    assert body["rows"][0]["status"] == "REVIEW"


# ---------------------------------------------------------------------------
# Pagination and export — section 11's build rules
# ---------------------------------------------------------------------------


def test_search_paginates_server_side(client):
    body = client.get(
        "/api/v1/search", params={"limit": 1, "offset": 0}, headers=_auth(OFFICER)
    ).json()
    assert body["total"] == 4
    assert len(body["rows"]) == 1


def test_search_is_newest_first(client):
    body = client.get("/api/v1/search", headers=_auth(OFFICER)).json()
    stamps = [row["captured_at"] for row in body["rows"]]
    assert stamps == sorted(stamps, reverse=True)


def test_csv_export_returns_the_whole_result_not_one_page(client):
    """An export that only gives you the page you are looking at is the export
    people complain about."""
    response = client.get(
        "/api/v1/search", params={"format": "csv", "limit": 1}, headers=_auth(OFFICER)
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.strip().splitlines()
    assert len(lines) == 5  # header plus four scans


def test_csv_carries_a_bom_so_excel_reads_devanagari(client):
    """Half these columns are brand names; without the BOM a district office
    opens the export as mojibake."""
    response = client.get(
        "/api/v1/dashboard/brands", params={"format": "csv"}, headers=_auth()
    )
    assert response.content.startswith(b"\xef\xbb\xbf")


def test_an_export_is_written_to_the_audit_log(client, stores):
    """Section 18: the access log covers every record view **and export**.
    An export is the moment enforcement data leaves the system."""
    *_, audit, _reviews = stores
    client.get("/api/v1/dashboard/brands", params={"format": "csv"}, headers=_auth())
    actions = [entry["action"] for entry in audit.entries()]
    assert "export" in actions


def test_a_json_view_is_not_logged_as_an_export(client, stores):
    *_, audit, _reviews = stores
    client.get("/api/v1/dashboard/brands", headers=_auth())
    assert [e for e in audit.entries() if e["action"] == "export"] == []


def test_the_summary_view_is_audited(client, stores):
    *_, audit, _reviews = stores
    client.get("/api/v1/summary", headers=_auth())
    assert any(entry["entity"] == "summary" for entry in audit.entries())


def test_the_summary_is_the_dashboards_printable_form(client):
    """One computation behind the screen and the report, or they disagree."""
    summary = client.get("/api/v1/summary", headers=_auth()).json()
    overview = client.get("/api/v1/dashboard/overview", headers=_auth()).json()
    assert summary["non_compliance_rate"] == overview["tiles"]["non_compliance_rate"]["value"]
    assert summary["top_violations"] == overview["violations_by_rule"]


def test_the_dashboard_routes_are_in_the_openapi_schema(client):
    """The frontend's TypeScript is generated from it."""
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/dashboard/overview" in paths
    assert "/api/v1/search" in paths
    assert "/api/v1/summary" in paths


# ---------------------------------------------------------------------------
# The printed summary — section 13a
# ---------------------------------------------------------------------------


def test_the_printed_summary_reports_the_same_figures_as_the_json(client):
    """Section 13a: *the dashboard is the live view; the summary is its
    printable form.* One computation, two renderings — so the rate on screen and
    the rate in the tabled document are the same string."""
    from reports.summary_model import percent

    payload = client.get("/api/v1/summary", headers=_auth()).json()
    page = client.get("/api/v1/summary/report", headers=_auth())

    assert page.status_code == 200
    assert percent(payload["non_compliance_rate"]) in page.text
    assert str(payload["scans"]) in page.text


def test_the_printed_summary_honours_the_global_filters(client):
    """A summary detached from its scope gets forwarded as though it covered
    the whole state, so the filters must reach the store *and* the page."""
    page = client.get("/api/v1/summary/report?district=Cuttack", headers=_auth())

    assert "Cuttack district" in page.text


def test_the_summary_downloads_as_an_editable_document(client):
    """The problem statement names the editable format; DOCX needs no native
    libraries, so it works wherever the API does."""
    response = client.get("/api/v1/summary/report?format=docx", headers=_auth())

    assert response.status_code == 200
    assert response.content[:2] == b"PK"  # a .docx is a zip
    assert "attachment" in response.headers["content-disposition"]


def test_the_summary_pdf_is_a_pdf_on_every_host(client):
    """Section 5's discipline applied to a renderer: degrade, but still deliver.

    This used to answer **503 with a JSON body** where WeasyPrint's native
    libraries were absent, naming DOCX and HTML as the alternatives. That is a
    reasonable API and the wrong answer here, because the dashboard offers the
    export as `<a href=... download="violation-summary.pdf">` and a browser
    following a `download` link saves whatever comes back under that name. The
    officer received a JSON error called `violation-summary.pdf`.

    `reports.render.to_pdf` now falls back to `reports.pdf_fallback`, which is
    pure Python. Asserted on the magic bytes rather than the status: a 200
    carrying JSON would pass a status check and still be the bug.
    """
    response = client.get("/api/v1/summary/report?format=pdf", headers=_auth())

    assert response.status_code == 200
    assert response.content[:5] == b"%PDF-", (
        f"the export route handed a browser {response.content[:40]!r}"
    )
    assert "application/pdf" in response.headers["content-type"]


def test_exporting_the_summary_is_audited_as_a_download_not_a_view(client, stores):
    """Section 18's question is not who opened the app, but who took a copy of
    enforcement material out of it."""
    *_, audit, _reviews = stores

    client.get("/api/v1/summary/report?format=docx", headers=_auth())

    actions = [(entry["action"], entry["entity"]) for entry in audit.entries()]
    assert ("download_evidence", "summary") in actions
