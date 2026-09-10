"""Per-frame evidence for multi-frame scans — AKSHAR.md sections 6 and 8b.

Revision ID: 0003_scan_frames
Revises: 0002_review_resolutions
Create Date: 2026-09-10

An officer photographs one package from two or three sides, the evidence is
unioned and the rules are evaluated once on the union. That produces one scan
row with several photographs behind it, and section 6 requires *every*
photograph's digest to sit inside the hash chain — a frame that is evidence but
has no digest in the record is a frame nobody can defend six months later.

The chain covers the `scans` row, so the digests go in the row. One nullable
JSONB column, one entry per photograph:

    [{"frame": 0, "exit_path": "full", "read": true,
      "image_key": "2026/09/10/<id>.jpg", "image_sha256": "...",
      "stored": true}, ...]

**NULL for a single-frame scan, and the NULL is the point.** `image_key` and
`image_sha256` already describe the one photograph completely, and
`_payload_from_row` omits the key entirely when the column is NULL so that the
canonical payload of every row written before this revision is byte-for-byte
what it was when it was hashed. Default it to `'[]'` instead and every existing
record fails `verify_chain` with CONTENT_ALTERED the next time anyone sweeps.

`ADD COLUMN IF NOT EXISTS` keeps this in agreement with `db/schema.sql`, which
a fresh database is created from directly; `tests/unit/test_schema.py` asserts
the two definitions match.
"""

from __future__ import annotations

from alembic import op

revision = "0003_scan_frames"
down_revision = "0002_review_resolutions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE scans ADD COLUMN IF NOT EXISTS frames JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE scans DROP COLUMN IF EXISTS frames")
