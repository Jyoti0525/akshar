"""What a verdict's measurement is counted in — AKSHAR.md sections 11 and 13.

Revision ID: 0004_verdict_unit
Revises: 0003_scan_frames
Create Date: 2026-09-10

`verdicts.measured` and `verdicts.threshold` had no unit beside them, and every
renderer assumed millimetres because most rules measure millimetres. Two do not.
Rule 7(3)'s proviso is a width-to-height RATIO; Rule 8(1)'s proviso yields a
COUNT of intruding regions. Both were printed as millimetres, so a user scanning
a compliant cheese carton was shown

    Clear space around net quantity     13.00 mm    required 0.00 mm

The number was right. "required 0.00 mm" is not a quantity anyone can check, and
a report that prints one reads as a broken tool rather than as a finding.

**`DEFAULT 'mm'` and NOT NULL, and the default is the point.** Every row written
before this revision was produced by a rule that measured millimetres or by one
of the two that measured something else and said millimetres anyway; backfilling
`mm` restores the first exactly and leaves the second no worse than it was.
There is no way to tell the two apart from the stored row, and inventing a
backfill that guessed would put a fabricated unit on a sealed record.

Unlike `0003`, nothing here touches `scans`, so the evidence chain is untouched:
`verdicts` rows are not part of the canonical payload that `evidence/chain.py`
hashes. A new column on a table outside the chain cannot change a digest.

`ADD COLUMN IF NOT EXISTS` keeps this in agreement with `db/schema.sql`, which a
fresh database is created from directly; `tests/unit/test_schema.py` asserts the
two definitions match, and `test_a_verdict_survives_a_round_trip_through_the_schema`
is what caught the missing column in the first place.
"""

from __future__ import annotations

from alembic import op

revision = "0004_verdict_unit"
down_revision = "0003_scan_frames"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE verdicts ADD COLUMN IF NOT EXISTS unit TEXT NOT NULL DEFAULT 'mm'")
    op.execute(
        "ALTER TABLE verdicts DROP CONSTRAINT IF EXISTS verdicts_unit_check;"
        "ALTER TABLE verdicts ADD CONSTRAINT verdicts_unit_check "
        "CHECK (unit IN ('mm', 'ratio', 'count', 'cm2'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE verdicts DROP CONSTRAINT IF EXISTS verdicts_unit_check")
    op.execute("ALTER TABLE verdicts DROP COLUMN IF EXISTS unit")
