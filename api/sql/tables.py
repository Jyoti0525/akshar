"""`db/schema.sql` as SQLAlchemy Core tables. AKSHAR.md sections 10 and 15b.

**The SQL file is the source of truth, and this is a mirror of it.** Postgres
runs `db/schema.sql` at first boot; nothing here creates a table. Writing the
schema twice is a real cost, and it is paid deliberately for one reason: Core
gives compiled, parameterised queries with no string concatenation anywhere near
a filter value, which is what keeps `ScanFilters` — eleven optional user-supplied
fields, most of them free text — from being a SQL injection surface.

**The duplication is checked, not trusted.** `tests/unit/test_sql_stores.py`
parses both and asserts the column sets agree. This is the same class of bug as
the loader/fetch-script mismatch already guarded in `tests/test_boundaries.py`:
two files agreeing by convention rather than by construction, where the failure
is silent — a column added to the SQL and forgotten here produces a store that
reads every row correctly and writes `NULL` into the new field forever.

**Three column types are declared by hand** because they belong to Postgres
rather than to SQLAlchemy, and importing `pgvector` at module scope would make
this file unimportable in an environment that has no database driver at all —
which is precisely the environment the whole in-memory design exists to serve.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
)
from sqlalchemy.dialects.postgresql import BIT, INET, JSONB, UUID
from sqlalchemy.types import UserDefinedType

metadata = MetaData()


class Point(UserDefinedType):
    """Postgres `POINT`, used for the coarsened officer location (section 18).

    Read back as text and parsed, rather than relying on a driver-specific tuple
    representation: `psycopg` and `psycopg2` disagree about it, and the value
    ends up inside a hash-chained record, where a representation change would
    read as tampering on rows nobody had touched.
    """

    cache_ok = True

    def get_col_spec(self, **_):
        return "POINT"


class Vector(UserDefinedType):
    """pgvector's `VECTOR(n)`. Declared, never queried from here.

    Section 15b puts SKU near-duplicate search behind an HNSW index and the
    embedding is written by the identification pipeline, not by these stores.
    Declaring it keeps the mirror complete so the schema-agreement test is a
    real check rather than one with an exception list.
    """

    cache_ok = True

    def __init__(self, dimensions: int = 512) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_):
        return f"VECTOR({self.dimensions})"


users = Table(
    "users",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("email", String, nullable=False, unique=True),
    Column("full_name", String, nullable=False),
    Column("password_hash", String, nullable=False),
    Column("role", String, nullable=False),
    Column("district", String),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("created_at", DateTime(timezone=True)),
)

skus = Table(
    "skus",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("brand", String, nullable=False),
    Column("brand_group", String),
    Column("variant", String),
    Column("pack_size", String, nullable=False),
    Column("category", String, nullable=False),
    Column("barcode", String),
    Column("phash", BIT(64)),
    Column("embedding", Vector(512)),
    Column("label_w_mm", Numeric),
    Column("label_h_mm", Numeric),
    # A running mean is not a measurement without its count. See 0005.
    Column("label_mm_observations", Integer, nullable=False, default=0),
    Column("label_w_mm_m2", Numeric, nullable=False, default=0),
    Column("scan_count", Integer, nullable=False, default=0),
    Column("first_seen", DateTime(timezone=True)),
)

scans = Table(
    "scans",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("sku_id", UUID(as_uuid=True), ForeignKey("skus.id")),
    Column("officer_id", UUID(as_uuid=True), ForeignKey("users.id")),
    Column("district", String),
    Column("category", String),
    Column("source", String, nullable=False),
    Column("degradation_tier", String, nullable=False),
    Column("image_key", String),
    Column("image_sha256", String(64)),
    Column("frames", JSONB),
    Column("declaration_set", JSONB, nullable=False),
    Column("coverage", Numeric),
    Column("latency_ms", Integer),
    Column("cache_hit", Boolean),
    Column("geo", Point),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("synced_at", DateTime(timezone=True)),
    Column("model_versions", JSONB, nullable=False),
    Column("rulepack_version", String, nullable=False),
    Column("record_sha256", String(64)),
    Column("prev_sha256", String(64)),
    Column("chain_seq", BigInteger, unique=True),
)

verdicts = Table(
    "verdicts",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("scan_id", UUID(as_uuid=True), ForeignKey("scans.id"), nullable=False),
    Column("rule_id", String, nullable=False),
    Column("rule_ref", String, nullable=False),
    Column("status", String, nullable=False),
    Column("severity", String, nullable=False),
    Column("field", String),
    Column("found", String),
    Column("expected", String),
    Column("message", String, nullable=False, default=""),
    Column("advisory", Boolean, nullable=False, default=False),
    Column("suppressed_by", String),
    Column("respondent", String, nullable=False, default="manufacturer"),
    Column("measured", Numeric),
    Column("threshold", Numeric),
    Column("tolerance", Numeric),
    Column("unit", String, nullable=False, default="mm"),
)

corrections = Table(
    "corrections",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("scan_id", UUID(as_uuid=True), ForeignKey("scans.id"), nullable=False),
    Column("box_index", Integer),
    Column("from_field", String),
    Column("to_field", String),
    Column("officer_id", UUID(as_uuid=True), ForeignKey("users.id")),
    Column("created_at", DateTime(timezone=True)),
)

review_resolutions = Table(
    "review_resolutions",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("scan_id", UUID(as_uuid=True), ForeignKey("scans.id"), nullable=False),
    Column("rule_id", String, nullable=False),
    Column("decision", String, nullable=False),
    Column("officer_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("note", String, nullable=False, default=""),
    Column("resolved_at", DateTime(timezone=True)),
    # Deliberately NOT unique on (scan_id, rule_id). A resolution is an
    # append-only statement by a person, and a supervisor revisiting a call is a
    # second statement, not an edit of the first -- section 5 again. The queue
    # reads the set of resolved rule ids, so a repeat is idempotent there, and
    # the retraining export takes the latest per rule.
    Index("ix_review_resolutions_scan", "scan_id"),
)

access_log = Table(
    "access_log",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id")),
    Column("action", String, nullable=False),
    Column("entity", String, nullable=False),
    Column("entity_id", String),
    Column("ip", INET),
    Column("at", DateTime(timezone=True)),
)

bulk_jobs = Table(
    "bulk_jobs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("officer_id", UUID(as_uuid=True), ForeignKey("users.id")),
    Column("total", Integer, nullable=False),
    Column("completed", Integer, nullable=False, default=0),
    Column("failed", Integer, nullable=False, default=0),
    Column("errors", JSONB, nullable=False, default=list),
    Column("created_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
)

bulk_job_scans = Table(
    "bulk_job_scans",
    metadata,
    Column("job_id", UUID(as_uuid=True), ForeignKey("bulk_jobs.id"), primary_key=True),
    Column("scan_id", UUID(as_uuid=True), ForeignKey("scans.id"), primary_key=True),
)


class TSVector(UserDefinedType):
    """Postgres `tsvector`, generated and stored by the database.

    Declared for the same reason as `Vector`: the schema-agreement test is only
    a real check if the mirror is complete. Never written from Python — the
    column is `GENERATED ALWAYS AS ... STORED`, so an INSERT that named it
    would be rejected, which is the behaviour we want.
    """

    cache_ok = True

    def get_col_spec(self, **_):
        return "TSVECTOR"


rule_chunks = Table(
    "rule_chunks",
    metadata,
    # `key` is the tier-1 lookup key, `doc_id::ref`. Search and citation
    # lookup therefore address a clause identically, and a result found by
    # tier 2 resolves through exactly the tier-1 path an officer would reach
    # by tapping "why" on a verdict.
    Column("key", String, primary_key=True),
    Column("doc_id", String, nullable=False),
    Column("ref", String, nullable=False),
    Column("parent_ref", String),
    Column("heading", String, nullable=False, server_default=""),
    Column("text", String, nullable=False),
    Column("page", Integer, nullable=False),
    Column("kind", String, nullable=False),
    Column("source", String, nullable=False),
    Column("embedding", Vector(384)),
    Column("tsv", TSVector()),
)


__all__ = [
    "Point",
    "Vector",
    "access_log",
    "bulk_job_scans",
    "bulk_jobs",
    "corrections",
    "metadata",
    "rule_chunks",
    "scans",
    "skus",
    "users",
    "verdicts",
]
