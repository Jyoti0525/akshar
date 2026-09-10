"""API responses against the types the browser was compiled with. AKSHAR.md §18.

    "Contract tests validate API responses against the OpenAPI schema, and the
     frontend's Zod types are generated from that same schema, so frontend and
     backend cannot drift apart."                                        -- §18

That sentence is true of most of this API and **was not true of the dashboard**,
which is the half the sentence most needed to cover. `web/src/lib/api/types.ts`
says so in its own header:

    "The dashboard routes are the exception, and honestly so. They return
     `dict[str, Any]` [...] So they are declared here by hand, and each names
     the function in `api/analytics.py` it must match. If that function changes,
     this file has to change with it; nothing will tell us automatically."

This file is that "something". It is deliberately two tests of two different
kinds, because the gap has two halves.

---------------------------------------------------------------------------
HALF ONE: THE ROUTES THAT DO HAVE A SCHEMA
---------------------------------------------------------------------------
`test_every_response_model_reaches_the_openapi_document` walks the app's routes
and asserts that anything declaring a `response_model` actually publishes a
schema under that path. A route whose model is dropped -- by a decorator
argument lost in a refactor, or by FastAPI declining to serialise a type it
cannot introspect -- still returns 200 and still works, and `openapi-typescript`
then generates `unknown` for it. The frontend compiles. Every field access
silently becomes `any`.

---------------------------------------------------------------------------
HALF TWO: THE ROUTES THAT DO NOT
---------------------------------------------------------------------------
The dashboard functions return plain dictionaries, and the browser's idea of
their shape lives in a hand-written TypeScript interface. So the test parses
that TypeScript, runs the real analytics function over synthetic scans, and
compares the key sets.

Parsing TypeScript with a regular expression is ugly and it is the right trade
here: the alternative is a Node subprocess in a Python test, or a third
declaration of the same shapes in Python -- which would be a third thing to keep
in sync, and this file exists because two was already one too many.

**The failure this catches has already happened once.** `TrendPoint.rate` was
declared where the payload said `non_compliance_rate`, so `point.rate` was
`undefined` on every point and Recharts drew axes with no line. It looked like
"no data", not like a bug, and it survived review. The comment recording that is
still in `types.ts`; this is the test that would have caught it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from api import analytics
from api.analytics import ScanFacts, VerdictFact
from api.main import app

ROOT = Path(__file__).resolve().parents[2]
TYPES_TS = (ROOT / "web" / "src" / "lib" / "api" / "types.ts").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Reading the hand-written half of the contract
# ---------------------------------------------------------------------------


def interface_fields(name: str) -> set[str]:
    """Field names declared on one `export interface` in `types.ts`.

    Nested object literals are skipped by brace depth rather than by a nesting
    parser: only top-level members are the contract with the endpoint, and
    `Overview.tiles` is one member whose own five keys are checked separately by
    the test that asserts the tile names.

    Optional markers are stripped, so `previous?: number` compares equal to a
    key the payload always emits. That is the correct direction of leniency --
    an optional field the server always sends is safe, a required field it never
    sends is the bug.
    """
    match = re.search(
        rf"export interface {name}(?:<[^>]*>)?(?:\s+extends\s+[^{{]+)?\s*{{(.*?)^}}",
        TYPES_TS,
        re.DOTALL | re.MULTILINE,
    )
    assert match, f"no `export interface {name}` in web/src/lib/api/types.ts"

    fields: set[str] = set()
    depth = 0
    for line in match.group(1).splitlines():
        stripped = re.sub(r"//.*", "", line).strip()
        if depth == 0:
            member = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\??\s*:", stripped)
            if member:
                fields.add(member.group(1))
        depth += stripped.count("{") - stripped.count("}")
    return fields


def extends_of(name: str) -> str | None:
    match = re.search(rf"export interface {name}\s+extends\s+([A-Za-z_][A-Za-z0-9_]*)", TYPES_TS)
    return match.group(1) if match else None


def declared_fields(name: str) -> set[str]:
    """An interface's own fields plus everything it inherits."""
    fields = interface_fields(name)
    parent = extends_of(name)
    return fields | declared_fields(parent) if parent else fields


# ---------------------------------------------------------------------------
# Synthetic scans, shaped so every branch of every view is exercised
# ---------------------------------------------------------------------------


def _verdict(rule_id: str, status: str, severity: str = "high") -> VerdictFact:
    return VerdictFact(
        rule_id=rule_id,
        rule_ref="Rule 7(2), Table I",
        status=status,
        severity=severity,
        advisory=False,
    )


@pytest.fixture(scope="module")
def scans() -> list[ScanFacts]:
    """Enough variety that no view returns an empty list.

    An empty list has no keys, so a contract test over one asserts nothing at
    all while reporting success -- which is the specific way this kind of test
    rots. Every row below exists to make some view non-empty: two brands so
    `by_brand` groups, a REVIEW so `review_queue` has a row, a PASS-only scan so
    `_rate` has a conclusive denominator, and eight weeks of spread so
    `weekly_trend` and `_trend` both have something to divide.
    """
    now = datetime.now(UTC)
    rows: list[ScanFacts] = []
    for week in range(8):
        for index, (brand, category, district) in enumerate(
            [
                ("Parle", "biscuits", "Pune"),
                ("Britannia", "biscuits", "Nashik"),
                ("Dettol", "personal care", "Pune"),
            ]
        ):
            failing = (week + index) % 3 == 0
            reviewing = (week + index) % 5 == 0
            verdicts = [
                _verdict("r7_2_mrp_height", "FAIL" if failing else "PASS"),
                _verdict("r6_1_e_mrp_present", "REVIEW" if reviewing else "PASS", "medium"),
            ]
            rows.append(
                ScanFacts(
                    id=uuid4(),
                    sku_id=uuid4(),
                    officer_id=uuid4(),
                    brand=brand,
                    brand_group=brand,
                    category=category,
                    district=district,
                    source="photo",
                    degradation_tier="L1",
                    coverage=0.82,
                    latency_ms=520 + index,
                    cache_hit=index == 0,
                    captured_at=now - timedelta(weeks=week, hours=index),
                    synced=index != 2,
                    verdicts=tuple(verdicts),
                )
            )
    return rows


# ---------------------------------------------------------------------------
# Half two — the dashboard shapes
# ---------------------------------------------------------------------------


def _assert_keys(payload: dict, interface: str, *, allow_extra: bool = False) -> None:
    declared = declared_fields(interface)
    actual = set(payload)
    missing = declared - actual
    assert not missing, (
        f"`{interface}` in types.ts declares {sorted(missing)}, which the payload does not "
        f"contain. The browser reads these as `undefined` and renders nothing, with no error."
    )
    if not allow_extra:
        extra = actual - declared
        assert not extra, (
            f"the payload carries {sorted(extra)}, which `{interface}` does not declare. "
            f"Add them to types.ts, or the frontend cannot see a field the API is paying to send."
        )


def test_review_queue_rows_match_the_reviewrow_interface(scans):
    rows = analytics.review_queue(scans)
    assert rows, "the fixture must produce at least one REVIEW scan"
    _assert_keys(rows[0], "ReviewRow")


def test_trend_points_match_the_trendpoint_interface(scans):
    """The regression that motivated this file. `rate` vs `non_compliance_rate`."""
    points = analytics.weekly_trend(scans)
    assert points
    _assert_keys(points[0], "TrendPoint")


def test_rule_rows_match_the_rulerow_interface(scans):
    rows = analytics.by_rule(scans)
    assert rows
    _assert_keys(rows[0], "RuleRow")


def test_brand_rows_match_the_brandrow_interface(scans):
    rows = analytics.by_brand(scans)
    assert rows
    _assert_keys(rows[0], "BrandRow")


def test_category_rows_match_the_categoryrow_interface(scans):
    rows = analytics.by_category(scans)
    assert rows
    _assert_keys(rows[0], "CategoryRow")


def test_district_rows_match_the_districtrow_interface(scans):
    rows = analytics.by_district(scans)
    assert rows
    _assert_keys(rows[0], "DistrictRow")


def test_brand_detail_matches_the_branddetail_interface(scans):
    _assert_keys(analytics.brand_detail(scans, "Parle"), "BrandDetail")


def test_health_matches_the_healthview_interface(scans):
    _assert_keys(analytics.health(scans), "HealthView")


def test_summary_matches_the_summaryview_interface(scans):
    _assert_keys(analytics.summary(scans), "SummaryView")


def test_overview_matches_the_overview_interface(scans):
    payload = analytics.overview(scans)
    _assert_keys(payload, "Overview")

    # `tiles` is the one nested literal worth checking by hand: the five names
    # in it are section 11's five tiles, and a renamed key there blanks a card
    # on the front page rather than failing anything.
    declared_tiles = set(
        re.findall(
            r"([a-z_]+):\s*Tile",
            re.search(r"tiles:\s*{(.*?)};", TYPES_TS, re.DOTALL).group(1),  # type: ignore[union-attr]
        )
    )
    assert declared_tiles == set(payload["tiles"]), (
        f"types.ts declares tiles {sorted(declared_tiles)}, analytics emits "
        f"{sorted(payload['tiles'])}"
    )


def test_every_tile_matches_the_tile_interface(scans):
    """`previous` and `change` are optional in the interface and always present
    in the payload, which is the safe direction -- see `interface_fields`."""
    for name, tile in analytics.overview(scans, scans)["tiles"].items():
        assert set(tile) <= declared_fields("Tile"), f"tile {name} carries {sorted(tile)}"
        assert "value" in tile, f"tile {name} has no value"


# ---------------------------------------------------------------------------
# Half one — the routes that declare a model
# ---------------------------------------------------------------------------


def test_every_response_model_reaches_the_openapi_document():
    """A declared `response_model` that publishes no schema generates `unknown`.

    The frontend still compiles -- every field access on `unknown` after a cast
    is `any` -- so the symptom appears at runtime, in the browser, as a blank
    panel.
    """
    document = app.openapi()
    missing: list[str] = []
    for route in app.routes:
        model = getattr(route, "response_model", None)
        if model is None or not getattr(route, "include_in_schema", True):
            continue
        for method in {m.lower() for m in getattr(route, "methods", set())} - {"head", "options"}:
            operation = document["paths"].get(route.path, {}).get(method)
            if operation is None:
                missing.append(f"{method.upper()} {route.path}: absent from the document")
                continue
            # Any 2xx, not just 200. `POST /scans/bulk` answers 202 by
            # design -- section 12 accepts the batch and hands back a job id --
            # and a test that only looked at 200 would report the one correctly
            # asynchronous endpoint in the API as broken.
            successes = [
                response
                for code, response in operation.get("responses", {}).items()
                if code.startswith("2")
            ]
            schema = next(
                (
                    response["content"]["application/json"]["schema"]
                    for response in successes
                    if response.get("content", {}).get("application/json", {}).get("schema")
                ),
                None,
            )
            if not schema:
                missing.append(f"{method.upper()} {route.path}: no JSON schema on its success")
    assert not missing, "routes declaring a response_model but publishing no schema:\n" + "\n".join(
        missing
    )


def test_the_committed_openapi_export_is_not_stale():
    """`web_openapi.json` is the input to `openapi-typescript`, and it is a build
    artefact that CI regenerates. It is checked here too because a stale export
    is the one way the generated types can disagree with the running API while
    every other test passes.

    Compared on the *route table* rather than byte-for-byte: FastAPI's document
    carries descriptions lifted from docstrings, and a reworded docstring is not
    a contract change.
    """
    export = ROOT / "web_openapi.json"
    if not export.exists():
        pytest.skip("web_openapi.json is a build artefact and is not in the tree")

    import json

    committed = json.loads(export.read_text(encoding="utf-8"))
    live = app.openapi()
    committed_ops = {
        f"{method.upper()} {path}"
        for path, item in committed["paths"].items()
        for method in item
    }
    live_ops = {
        f"{method.upper()} {path}" for path, item in live["paths"].items() for method in item
    }
    assert committed_ops == live_ops, (
        "web_openapi.json is stale; run the export in .github/workflows/ci.yml, "
        f"added={sorted(live_ops - committed_ops)} removed={sorted(committed_ops - live_ops)}"
    )
