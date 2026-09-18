"""What `label_w_mm` was averaged from — AKSHAR.md section 17, M2.

Revision ID: 0005_sku_dimension_observations
Revises: 0004_verdict_unit
Create Date: 2026-09-19

Scale tier B is the one that lets an officer photograph a pack *without* the
marker card:

    "Tier A is impressive but needs a prop in every photograph, which is a
     procedure officers will forget. Tier B needs nothing: once any officer
     anywhere has measured a Parle-G 100 g pack with a marker, every subsequent
     photograph of that SKU is measurable without one."

It could not fire. `vision/scale/tier_b.estimate` refuses to answer below three
observations, and there was nowhere to record that a scan had happened at all —
so the guard was permanently tripped and the tier was dead code with passing
tests. Nothing wrote a dimension back either, so the repository could not have
filled even if the guard had allowed it.

**Why two columns rather than one.** `label_w_mm` is a running mean. A mean
without its count cannot be updated, and a mean without its spread cannot say
how much to trust it — tier B feeds the standard deviation straight into the
measurement tolerance, which is what turns a marginal height into REVIEW rather
than a confident FAIL. `label_w_mm_m2` is Welford's M2 (the running sum of
squared deviations); the standard deviation is derived from it on read.

Storing M2 instead of the deviation itself is what lets an observation be
folded in by one UPDATE whose right-hand sides all read the pre-update row:

    n' = n + 1
    mean' = mean + (x - mean) / n'
    M2'  = M2 + (x - mean) * (x - mean')

No read-then-write, so two worker threads finishing at the same moment cannot
lose an observation between them — the same reason `bump_scan_count` is
`scan_count = scan_count + 1` in SQL.

**Backfill is deliberately zero.** Any `label_w_mm` already present was seeded
by hand or by a fixture, not observed through a marker, and `DEFAULT 0` says so
honestly: tier B will not use it, and the first real observation replaces it
rather than averaging against a number with no provenance. Backfilling a count
of 1 would be inventing a measurement nobody took, on a column that decides
whether a millimetre goes into a legal notice.

Nothing here touches `scans`, so the evidence chain is untouched — `skus` rows
are not part of the canonical payload `evidence/chain.py` hashes.
"""

from __future__ import annotations

from alembic import op

revision = "0005_sku_dimension_observations"
down_revision = "0004_verdict_unit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE skus ADD COLUMN IF NOT EXISTS "
        "label_mm_observations INT NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE skus ADD COLUMN IF NOT EXISTS "
        "label_w_mm_m2 NUMERIC NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE skus DROP COLUMN IF EXISTS label_w_mm_m2")
    op.execute("ALTER TABLE skus DROP COLUMN IF EXISTS label_mm_observations")
