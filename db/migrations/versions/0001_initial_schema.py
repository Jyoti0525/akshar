"""Initial schema — AKSHAR.md section 10.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-07

This migration applies `db/schema.sql` verbatim rather than restating it in
SQLAlchemy. One definition, in the file a human reads, so the two cannot drift —
and `tests/unit/test_schema.py` fails the build if they ever do.

Reading the file at runtime is deliberate: a hand-transcribed copy here would be
a second source of truth for the `pack_size` unique constraint, and section 10
is explicit that collapsing pack sizes makes violations "vanish silently, with
no error to tell you". That is not a constraint to maintain in two places.
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = Path(__file__).resolve().parents[2] / "schema.sql"

# Dropped in reverse dependency order. `verdicts` and `corrections` reference
# `scans`, and `scans` references `skus` and `users`.
_TABLES = ("access_log", "corrections", "verdicts", "scans", "skus", "users")


def upgrade() -> None:
    sql = SCHEMA.read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    # The extensions are left in place. `vector` and `uuid-ossp` may be in use
    # by something else in the same database, and dropping an extension takes
    # its data types with it.
