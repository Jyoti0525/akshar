"""Review resolutions — AKSHAR.md section 8b, section 11 Q6.

Revision ID: 0002_review_resolutions
Revises: 0001_initial_schema
Create Date: 2026-09-09

The review queue was a list rebuilt from verdicts on every load, so the work
reappeared the moment the page was refreshed. `POST /scans/{id}/review` writes
here, and `api.analytics.review_queue` reads it back to drop what has been
settled.

**This one restates its DDL rather than re-reading `db/schema.sql`,** which is
the opposite of what 0001 does and the difference is deliberate. 0001 *is* the
schema file — running it twice on a fresh database is the point. A second
migration that re-applied the whole file would silently pick up every later edit
to it as part of *this* revision, so an existing deployment upgrading from 0001
to 0002 would get changes nobody wrote a migration for. The `IF NOT EXISTS`
clauses keep the two paths in agreement: a database created from `schema.sql`
already has the table and this migration is a no-op on it.

`tests/unit/test_schema.py` asserts the two definitions match.
"""

from __future__ import annotations

from alembic import op

revision = "0002_review_resolutions"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS review_resolutions (
          id          BIGSERIAL PRIMARY KEY,
          scan_id     UUID NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
          rule_id     TEXT NOT NULL,
          decision    TEXT NOT NULL,
          officer_id  UUID NOT NULL REFERENCES users(id),
          note        TEXT NOT NULL DEFAULT '',
          resolved_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_review_resolutions_scan ON review_resolutions (scan_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS review_resolutions CASCADE")
