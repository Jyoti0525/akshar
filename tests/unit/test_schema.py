"""The schema against AKSHAR.md section 10 — and against itself.

`db/schema.sql` is read by three audiences that can drift apart: a human, the
`docker compose` init, and Alembic. These tests keep them honest without needing
a running Postgres, by parsing the SQL as text.

Two columns in section 10 are called out as "easy to overlook and both matter",
and both are the kind of mistake that produces *silently wrong* output rather
than an error — which is exactly what a test is for.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
MIGRATION = (
    ROOT / "db" / "migrations" / "versions" / "0001_initial_schema.py"
).read_text(encoding="utf-8")

SECTION_10_TABLES = ("skus", "scans", "verdicts", "corrections", "access_log", "users")


def _normalise(sql: str) -> str:
    """Flatten to one lowercase line, WITHOUT the comments.

    Stripping `--` comments matters: this file asserts that certain strings are
    absent from the schema, and the schema's own prose explains why they are
    absent. Without this, the comment "there is no BYTEA column anywhere" would
    fail the test that no BYTEA column exists.
    """
    without_comments = re.sub(r"--[^\n]*", "", sql)
    return re.sub(r"\s+", " ", without_comments).lower()


FLAT = _normalise(SCHEMA)


# ---------------------------------------------------------------------------
# Every table and column section 10 names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table", SECTION_10_TABLES)
def test_every_section_10_table_exists(table):
    assert f"create table if not exists {table} (" in FLAT


@pytest.mark.parametrize(
    "column",
    [
        "brand", "brand_group", "variant", "pack_size", "category", "barcode",
        "phash", "embedding", "label_w_mm", "label_h_mm", "scan_count", "first_seen",
    ],
)
def test_skus_carries_its_columns(column):
    assert re.search(rf"\b{column}\b", FLAT)


@pytest.mark.parametrize(
    "column",
    [
        "sku_id", "officer_id", "district", "source", "degradation_tier",
        "image_key", "image_sha256", "declaration_set", "coverage", "latency_ms",
        "cache_hit", "geo", "captured_at", "synced_at", "model_versions",
        "rulepack_version", "record_sha256", "prev_sha256", "chain_seq",
    ],
)
def test_scans_carries_its_columns(column):
    assert re.search(rf"\b{column}\b", FLAT)


# ---------------------------------------------------------------------------
# The two columns section 10 says are easy to overlook
# ---------------------------------------------------------------------------


def test_pack_size_is_inside_the_unique_constraint():
    """Section 10, and it is the sharpest correctness point in the schema.

    "30 g and 100 g of the same product have DIFFERENT HEIGHT THRESHOLDS. Treat
    them as one SKU and violations vanish silently, with no error to tell you."

    Rule 7(2) Table I is keyed on net quantity: <=200 g needs 1 mm numerals,
    <=500 g needs 2 mm. Collapse two pack sizes into one row and the 500 g pack
    is judged against the 200 g threshold — a real violation reported as a pass.
    """
    match = re.search(r"unique \(([^)]*)\)", FLAT)
    assert match, "no unique constraint on skus"
    columns = {part.strip() for part in match.group(1).split(",")}
    assert columns == {"brand", "variant", "pack_size"}, columns


def test_brand_group_exists_because_a_notice_is_addressed_to_the_parent():
    """Section 11: Lay's and Kurkure are one company, and that is who is served."""
    assert "brand_group" in FLAT


# ---------------------------------------------------------------------------
# The rule the whole storage design rests on
# ---------------------------------------------------------------------------


def test_no_image_bytes_column_anywhere():
    """Section 6: "Images never go in the database."

    A 3 MB blob in a row "wrecks query performance, backup times and
    replication". `image_key` is a MinIO object key; there must be no BYTEA,
    BLOB or LARGE OBJECT column in this schema, ever.
    """
    for forbidden in ("bytea", "blob", "oid", "lo"):
        assert not re.search(rf"\b{forbidden}\b", FLAT), (
            f"schema declares a {forbidden!r} column; images belong in MinIO"
        )


def test_image_key_and_hash_are_present_instead():
    assert "image_key" in FLAT
    assert "image_sha256 char(64)" in FLAT


# ---------------------------------------------------------------------------
# Indexes — section 10's five, plus the one section 15b argues separately
# ---------------------------------------------------------------------------


def test_the_sku_vector_index_is_hnsw_with_the_stated_parameters():
    """Section 15b: "Here an index IS justified: SKU count grows without bound."

    And the parameters are named — `m=16`, `ef_construction=64` — so they are
    asserted rather than left to whatever the default happens to be.
    """
    assert "using hnsw (embedding vector_cosine_ops)" in FLAT
    assert "m = 16" in FLAT
    assert "ef_construction = 64" in FLAT


@pytest.mark.parametrize(
    "index",
    [
        "skus (phash)",
        "skus (brand_group, category)",
        "verdicts (rule_id, status)",
        "scans (district, captured_at desc)",
    ],
)
def test_section_10_indexes_exist(index):
    assert index in FLAT


def test_the_rule_corpus_gets_no_vector_index():
    """The deliberate asymmetry, and it is worth being able to explain.

    Section 15b: 1,700 rule chunks are ~1.3 ms by sequential scan, and "an HNSW
    or IVF index would take longer to build than brute force takes to run". The
    SKU table gets an index because it grows without bound; the rule corpus does
    not. If a `rules`/`clauses` table ever appears here with an hnsw index, that
    reasoning has been lost.
    """
    hnsw_targets = re.findall(r"on (\w+) using hnsw", FLAT)
    assert hnsw_targets == ["skus"], hnsw_targets


# ---------------------------------------------------------------------------
# Constraints that encode vocabulary from contracts/
# ---------------------------------------------------------------------------


def test_status_check_matches_the_five_verdict_statuses():
    """Including REVIEW and NO_DATA.

    A schema that permitted only PASS/FAIL would quietly make the two statuses
    that keep this system defensible unstorable.
    """
    from typing import get_args

    from contracts.declarations import VerdictStatus

    match = re.search(r"status text not null\s*check \(status in \(([^)]*)\)", FLAT)
    assert match, "verdicts.status has no CHECK constraint"
    allowed = {part.strip().strip("'") for part in match.group(1).split(",")}
    assert allowed == {status.lower() for status in get_args(VerdictStatus)}


def test_degradation_tier_check_covers_l0_to_l4():
    match = re.search(r"check \(degradation_tier in \(([^)]*)\)", FLAT)
    assert match
    tiers = {part.strip().strip("'") for part in match.group(1).split(",")}
    assert tiers == {"l0", "l1", "l2", "l3", "l4"}


def test_source_check_covers_all_three_input_channels():
    """Photo, bulk image, and listing text. The PS names three; so does the schema."""
    match = re.search(r"check \(source in \(([^)]*)\)", FLAT)
    assert match
    sources = {part.strip().strip("'") for part in match.group(1).split(",")}
    assert sources == {"photo", "bulk_image", "listing_text"}


def test_roles_are_the_three_in_section_12():
    match = re.search(r"check \(role in \(([^)]*)\)", FLAT)
    assert match
    roles = {part.strip().strip("'") for part in match.group(1).split(",")}
    assert roles == {"officer", "supervisor", "admin"}


# ---------------------------------------------------------------------------
# Alembic must not become a second source of truth
# ---------------------------------------------------------------------------


def test_the_migration_applies_the_schema_file_rather_than_restating_it():
    """One definition, in the file a human reads.

    A hand-transcribed copy inside the migration would be a second place for the
    `pack_size` constraint to live, and section 10 is explicit about what
    happens when that one is wrong.
    """
    assert "schema.sql" in MIGRATION.lower()
    assert "SCHEMA.read_text" in MIGRATION
    assert "CREATE TABLE" not in MIGRATION.upper().replace("DROP TABLE", "")


def test_the_migration_can_be_reversed():
    for table in SECTION_10_TABLES:
        assert table in MIGRATION, f"downgrade does not drop {table}"


def test_no_connection_string_is_committed():
    """`alembic.ini` must not carry a URL; it comes from the environment."""
    ini = (ROOT / "alembic.ini").read_text(encoding="utf-8")
    match = re.search(r"^sqlalchemy\.url[ \t]*=[ \t]*(.*)$", ini, re.M)
    assert match, "alembic.ini has no sqlalchemy.url line"
    assert not match.group(1).strip(), "a connection string is committed in alembic.ini"
