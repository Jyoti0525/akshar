"""The SQL stores — AKSHAR.md sections 5, 10, 11, 12.

Two kinds of test, and the split matters.

**The first kind needs no database.** `api/sql/tables.py` mirrors
`db/schema.sql`, and a mirror that drifts is worse than no mirror: the store
keeps reading every row correctly and writes `NULL` into the forgotten column
forever, with nothing to notice. So the two files are parsed and compared. This
is the same class of bug `tests/test_boundaries.py` already guards between the
model loaders and the fetch script — two files agreeing by convention rather
than by construction.

**The second kind is the store contract**, run against the in-memory
implementation always and against Postgres when `AKSHAR_TEST_DATABASE_URL`
points at one. Section 5's guarantees — idempotent replay, a gapless
server-assigned `chain_seq`, immutability — are *behaviour*, not SQL, and the
whole point of writing them against a Protocol was that both backends could be
held to the same assertions rather than each being trusted separately.

Run the SQL half with:

    docker compose up -d db
    AKSHAR_TEST_DATABASE_URL=postgresql+psycopg://akshar:akshar@localhost:5432/akshar \\
        pytest tests/unit/test_sql_stores.py -m integration
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from api.analytics import ScanFilters
from api.repository import (
    BulkJob,
    InMemoryBulkJobStore,
    InMemoryScanStore,
    InMemorySkuStore,
    SkuRecord,
)
from api.sql import tables as t
from evidence.verify import verify_chain

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")

TEST_DATABASE_URL = os.environ.get("AKSHAR_TEST_DATABASE_URL")

OFFICER_ID = UUID("00000000-0000-4000-8000-00000000a5a5")
"""A fixed officer for the bulk-job fixture, seeded into `users` for the SQL
run because `bulk_jobs.officer_id` references it."""


# ---------------------------------------------------------------------------
# The mirror must not drift
# ---------------------------------------------------------------------------


def _columns_in_sql(table: str) -> set[str]:
    """Column names from a `CREATE TABLE` block in `db/schema.sql`.

    A small parser rather than a real one, and it is honest about its scope: it
    reads the first identifier of each line inside the block, skipping comments,
    blank lines and the table-level `CONSTRAINT` / `PRIMARY KEY` clauses. That
    is enough to catch the failure this exists for — a column added on one side
    and not the other — without pulling a SQL grammar into the test suite.
    """
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", SCHEMA, re.DOTALL
    )
    assert match, f"no CREATE TABLE for {table} in db/schema.sql"

    columns: set[str] = set()
    depth = 0
    for raw in match.group(1).splitlines():
        line = raw.strip()
        # Track parentheses so a CHECK constraint spanning two lines does not
        # contribute its second line as a column name.
        if depth == 0 and line and not line.startswith("--"):
            token = line.split()[0]
            if token.upper() not in {"CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "FOREIGN"}:
                columns.add(token)
        depth += line.count("(") - line.count(")")
    return columns


@pytest.mark.parametrize(
    "table",
    [
        "users",
        "skus",
        "scans",
        "verdicts",
        "corrections",
        "access_log",
        "bulk_jobs",
        "bulk_job_scans",
        "rule_chunks",
    ],
)
def test_the_core_tables_mirror_the_schema_file(table: str) -> None:
    declared = {column.name for column in t.metadata.tables[table].columns}
    assert declared == _columns_in_sql(table), (
        f"api/sql/tables.py and db/schema.sql disagree about {table}; "
        f"only in tables.py: {sorted(declared - _columns_in_sql(table))}, "
        f"only in schema.sql: {sorted(_columns_in_sql(table) - declared)}"
    )


def test_a_verdict_survives_a_round_trip_through_the_schema() -> None:
    """Every field of `contracts.Verdict` has somewhere to live.

    Without `advisory` and `suppressed_by` the dashboard's two most important
    counting rules break *only on Postgres*: advisory unit-symbol checks would
    be reported as non-compliance, and a suppressed verdict would be counted
    beside the one that suppressed it. Both are silent, and both change the
    headline number a department publishes.
    """
    from contracts import Verdict

    stored = {column.name for column in t.verdicts.columns}
    missing = set(Verdict.model_fields) - stored
    assert not missing, f"a Verdict field has no column: {sorted(missing)}"


def test_the_countable_index_matches_the_query_the_dashboard_runs() -> None:
    assert "WHERE NOT advisory AND suppressed_by IS NULL" in SCHEMA


# ---------------------------------------------------------------------------
# The store contract — both backends, same assertions
# ---------------------------------------------------------------------------


def _engine():
    from sqlalchemy import create_engine

    return create_engine(TEST_DATABASE_URL, future=True)


@pytest.fixture(
    params=[
        pytest.param("memory", id="in-memory"),
        pytest.param(
            "sql",
            id="postgres",
            marks=[
                pytest.mark.integration,
                pytest.mark.skipif(
                    not TEST_DATABASE_URL,
                    reason="set AKSHAR_TEST_DATABASE_URL to run the SQL contract",
                ),
            ],
        ),
    ]
)
def stores(request):
    """A `(scans, skus)` pair from whichever backend this parameter names."""
    if request.param == "memory":
        skus = InMemorySkuStore()
        return InMemoryScanStore(skus=skus), skus

    from sqlalchemy import delete

    from api.sql.stores import SqlScanStore, SqlSkuStore

    engine = _engine()
    with engine.begin() as conn:
        # Order matters: children first, or the foreign keys refuse.
        for table in (t.bulk_job_scans, t.bulk_jobs, t.verdicts, t.corrections, t.scans, t.skus):
            conn.execute(delete(table))
    return SqlScanStore(engine), SqlSkuStore(engine)


def _scan(**overrides):
    return {
        "id": uuid4(),
        "officer_id": None,
        "sku_id": None,
        "district": "Khordha",
        "category": "biscuits",
        "source": "photo",
        "degradation_tier": "L0",
        "image_key": None,
        "image_sha256": None,
        "declaration_set": {"source": "photo", "declarations": []},
        "coverage": 0.87,
        "latency_ms": 561,
        "cache_hit": False,
        "geo": {"lat": 20.296, "lon": 85.825},
        "captured_at": datetime.now(UTC) - timedelta(minutes=5),
        "model_versions": {"rulepack": "test"},
        "rulepack_version": "test",
        **overrides,
    }


def test_a_replayed_scan_appends_no_second_chain_entry(stores):
    """Section 5's idempotency, asserted against the interface rather than a dict."""
    scans, _ = stores
    payload = _scan()

    first = scans.save(payload)
    second = scans.save(payload)

    assert first.created is True
    assert second.created is False
    assert second.record.chain_seq == first.record.chain_seq
    assert len(scans.all_records()) == 1


def test_the_chain_sequence_is_server_assigned_and_gapless(stores):
    """"Offline clients cannot possibly agree on ordering among themselves"."""
    scans, _ = stores
    for _ in range(4):
        scans.save(_scan())

    assert [record.chain_seq for record in scans.all_records()] == [0, 1, 2, 3]


def test_a_stored_scan_still_verifies_after_a_round_trip(stores):
    """The one that catches `Decimal` and `POINT`.

    `verify_chain` re-hashes what it reads. A column type that comes back as a
    different Python type produces different canonical JSON, so every record
    reports as altered — a false tamper alarm on rows nobody touched, which
    section 6 calls out by name as worse than having no chain.
    """
    scans, _ = stores
    for _ in range(3):
        scans.save(_scan())

    report = verify_chain(scans.all_records())
    assert report.ok, report.failures


def test_the_latest_scan_of_a_sku_is_what_the_cache_looks_up(stores):
    scans, skus = stores
    sku = SkuRecord(
        id=uuid4(),
        brand="Parle",
        variant="G",
        pack_size="100 g",
        category="biscuits",
        barcode="8901030865275",
    )
    skus.add(sku) if hasattr(skus, "add") else _insert_sku(skus, sku)

    assert scans.latest_for_sku(sku.id) is None
    first = scans.save(_scan(sku_id=sku.id)).record.payload["id"]
    second = scans.save(_scan(sku_id=sku.id)).record.payload["id"]

    assert scans.latest_for_sku(sku.id) == second
    assert first != second


def _insert_sku(store, sku: SkuRecord) -> None:
    from sqlalchemy import insert

    with store.engine.begin() as conn:
        conn.execute(
            insert(t.skus).values(
                id=sku.id,
                brand=sku.brand,
                variant=sku.variant,
                pack_size=sku.pack_size,
                category=sku.category,
                barcode=sku.barcode,
                scan_count=sku.scan_count,
                first_seen=datetime.now(UTC),
            )
        )


def test_a_stored_measurement_comes_back_as_a_number(stores):
    """`measured`, `threshold` and `tolerance` are floats on the way out.

    They are `NUMERIC` columns, so Postgres hands them back as `Decimal`, and a
    `Decimal` serialises to JSON as a **string**. `contracts.Verdict` declares
    all three as `float | None`, so a store returning Decimals puts the API in
    breach of its own schema.

    Nothing caught it for a long time because the scan itself never takes this
    path — a fresh scan returns the engine's own Python floats. Only the *saved*
    record does, so `POST /scans` served `0.5` and `GET /scans/{id}` served
    `"0.5"`, and the full-record page attached to a notice died with `toFixed is
    not a function` while the result card beside it rendered perfectly.

    Trivially true of the in-memory store, which is the point: the assertion is
    written against the shared contract so that the Postgres run is held to it
    too, and that is the run where it fails.
    """
    scans, _ = stores
    scan_id = scans.save(_scan()).record.payload["id"]
    scans.save_verdicts(
        scan_id,
        [
            {
                "rule_id": "LMPC.CHAR.WIDTH_RATIO",
                "rule_ref": "Rule 7(3) proviso",
                "status": "PASS",
                "severity": "low",
                "measured": 0.5,
                "threshold": 0.3333,
                "tolerance": None,
                "unit": "ratio",
            },
            {
                "rule_id": "LMPC.CONTRAST.NUMERALS",
                "rule_ref": "Rule 9(1)(b)",
                "status": "PASS",
                "severity": "medium",
                "measured": 4.46840290211378,
                "threshold": 3.0,
                "tolerance": 0.2,
            },
        ],
    )

    stored = scans.verdicts_for(scan_id)
    for verdict in stored:
        for field in ("measured", "threshold", "tolerance"):
            value = verdict[field]
            assert value is None or type(value) is float, (
                f"{verdict['rule_id']}.{field} came back as {type(value).__name__}; "
                f"contracts.Verdict declares it float | None, and a Decimal is "
                f"serialised to JSON as a string"
            )

    assert stored[0]["measured"] == pytest.approx(0.5)
    assert stored[1]["tolerance"] == pytest.approx(0.2)


def test_verdicts_round_trip_with_their_advisory_and_suppression_flags(stores):
    """The dashboard reads these three fields and counts nothing else. Section 11."""
    scans, _ = stores
    scan_id = scans.save(_scan()).record.payload["id"]
    scans.save_verdicts(
        scan_id,
        [
            {
                "rule_id": "LMPC.UNIT.SYMBOL",
                "rule_ref": "Rule 8(1)",
                "status": "FAIL",
                "severity": "low",
                "advisory": True,
            },
            {
                "rule_id": "LMPC.MRP.HEIGHT",
                "rule_ref": "Rule 7(2)",
                "status": "FAIL",
                "severity": "high",
                "suppressed_by": "LMPC.MRP.NUMERAL_HEIGHT",
            },
        ],
    )

    stored = scans.verdicts_for(scan_id)
    assert [v["advisory"] for v in stored] == [True, False]
    assert stored[1]["suppressed_by"] == "LMPC.MRP.NUMERAL_HEIGHT"

    facts = scans.facts(ScanFilters())
    assert len(facts) == 1
    # Neither verdict counts: one is advisory, the other suppressed. Both are
    # FAIL, so a store that dropped these two flags would report this scan as
    # two non-compliances.
    assert facts[0].failures == ()
    assert facts[0].is_conclusive is False


def test_a_filter_narrows_the_facts_the_dashboard_sees(stores):
    scans, _ = stores
    scans.save(_scan(district="Khordha"))
    scans.save(_scan(district="Cuttack"))

    assert len(scans.facts(ScanFilters())) == 2
    assert len(scans.facts(ScanFilters(district="Cuttack"))) == 1


# ---------------------------------------------------------------------------
# Bulk job receipts
# ---------------------------------------------------------------------------


@pytest.fixture(
    params=[
        pytest.param("memory", id="in-memory"),
        pytest.param(
            "sql",
            id="postgres",
            marks=[
                pytest.mark.integration,
                pytest.mark.skipif(
                    not TEST_DATABASE_URL,
                    reason="set AKSHAR_TEST_DATABASE_URL to run the SQL contract",
                ),
            ],
        ),
    ]
)
def jobs(request):
    if request.param == "memory":
        return InMemoryBulkJobStore()

    from sqlalchemy import delete, insert, select

    from api.sql.stores import SqlBulkJobStore

    engine = _engine()
    with engine.begin() as conn:
        conn.execute(delete(t.bulk_job_scans))
        conn.execute(delete(t.bulk_jobs))
        # `bulk_jobs.officer_id` is a foreign key into `users`. The in-memory
        # store has no such constraint, so these tests passed for months with a
        # random UUID for an officer and only failed the first time they were
        # run against a real database. Seeding the officer is what makes the
        # two implementations actually agree.
        exists = conn.execute(select(t.users.c.id).where(t.users.c.id == OFFICER_ID)).first()
        if exists is None:
            conn.execute(
                insert(t.users).values(
                    id=OFFICER_ID,
                    email="bulk-fixture@example.invalid",
                    full_name="Bulk Fixture",
                    password_hash="x",
                    role="officer",
                )
            )
    return SqlBulkJobStore(engine)


def test_a_job_is_only_finished_once_every_image_is_accounted_for(jobs):
    job = jobs.create(
        BulkJob(id=uuid4(), officer_id=OFFICER_ID, total=3, created_at=datetime.now(UTC))
    )

    jobs.record_result(job.id, scan_id=None, error="a.jpg: not a decodable image")
    running = jobs.get(job.id)
    assert running.status == "running"
    assert running.pending == 2
    assert running.finished_at is None

    jobs.record_result(job.id)
    final = jobs.record_result(job.id)

    assert final.pending == 0
    assert final.completed == 2 and final.failed == 1
    assert final.status == "complete"
    assert final.finished_at is not None


def test_a_job_where_everything_failed_says_failed_not_complete(jobs):
    """"3 of 3 complete" for a folder where nothing was read is a lie."""
    job = jobs.create(
        BulkJob(id=uuid4(), officer_id=OFFICER_ID, total=2, created_at=datetime.now(UTC))
    )
    jobs.record_result(job.id, error="a.jpg: empty")
    jobs.record_result(job.id, error="b.jpg: empty")

    assert jobs.get(job.id).status == "failed"


def test_recording_against_a_job_that_does_not_exist_returns_none(jobs):
    assert jobs.record_result(uuid4()) is None
