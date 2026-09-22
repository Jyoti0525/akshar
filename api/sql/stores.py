"""SQL implementations of the storage Protocols. AKSHAR.md sections 5, 10, 11, 12.

The in-memory stores in `api/repository.py` are not mocks — they implement
section 5's guarantees, and `tests/unit/test_sql_stores.py` runs the same
contract against both. So this file has a specification to meet rather than a
shape to invent, and the interesting parts are the three places where "the same
behaviour" is harder in SQL than in a dict.

**1. Idempotent append under concurrency.** The chain is a linked list: each
record hashes the previous record's digest. Two workers appending at the same
moment both read the same tail and both write records claiming the same
predecessor, which forks the chain — and a forked chain fails verification
forever, on records nobody edited. `INSERT ... ON CONFLICT DO NOTHING` gives
idempotency but not ordering, so the append takes a **transaction-scoped
advisory lock** first. It is held for microseconds and only by writers; readers
never touch it.

**2. Round-tripping a hashed row.** `verify_chain` re-hashes stored records, so
a row read back from Postgres must produce *byte-identical* canonical JSON to
the row that was written. Two column types quietly break that and both are
handled in `_payload_from_row`: `NUMERIC` comes back as `Decimal` (which
canonicalises as a string, not a number) and `POINT` comes back in a
driver-specific representation. Neither is a hypothetical — either one turns
every stored scan into a false tamper alarm, and section 6 is explicit that a
false alarm teaches people to ignore the alarm.

**3. Filtering in SQL, aggregating in Python.** `facts()` applies
`ScanFilters` here — that is the selective part, and it belongs in the database —
then returns rows for `api.analytics` to shape. Section 11's arithmetic stays in
one place, so the JSON view, the CSV export and the PDF summary cannot compute
three different non-compliance rates depending on how the stack was deployed.
"""

from __future__ import annotations

import zlib
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Numeric,
    String,
    and_,
    case,
    cast,
    delete,
    func,
    insert,
    literal,
    literal_column,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine, Row

from api.analytics import UNCLASSIFIED, ScanFacts, ScanFilters, VerdictFact
from api.repository import (
    BulkJob,
    Correction,
    ReviewResolution,
    SkuRecord,
    SyncOutcome,
    UserRecord,
    normalise_verdict,
)
from api.sql import tables as t
from evidence.chain import ChainedRecord, append, from_row

_MEASURED_COLUMNS = frozenset({"measured", "threshold", "tolerance"})
"""The `NUMERIC` columns on `verdicts`. Module level rather than class level
because the comprehension in `verdicts_for` cannot see class scope."""

CHAIN_LOCK_KEY = zlib.crc32(b"akshar.scans.chain")
"""A stable 32-bit key for `pg_advisory_xact_lock`.

Derived from a string rather than picked as a magic number so a second system
sharing the database cannot collide with it by accident, and so the meaning is
readable at the call site instead of living in a comment.
"""


# ---------------------------------------------------------------------------
# Round-tripping
# ---------------------------------------------------------------------------


def _as_float(value: Any) -> float | None:
    """`NUMERIC` arrives as `Decimal`, which canonicalises as a *string*.

    `evidence.chain._encode` serialises a `Decimal` with `str()` — deliberately,
    because routing a NUMERIC through binary floating point would make the digest
    depend on rounding. That is right for a millimetre measurement and wrong
    here: `coverage` was hashed as the float `0.87` on the way in, so reading it
    back as `Decimal("0.87")` re-hashes to `"0.87"` and the record fails
    verification without anyone having touched it.

    Coerced on read rather than changed to `double precision` in the schema,
    because `NUMERIC` is the right column type for a value whose neighbours in
    that table are millimetre measurements.
    """
    return None if value is None else float(value)


def _point_to_geo(value: Any) -> dict[str, float] | None:
    """Postgres `POINT` back to the `{"lat", "lon"}` dict the payload carried.

    Accepts the two shapes a driver may hand over — a `(x, y)` tuple or the
    literal text `(x,y)` — because `psycopg` 3 and 2 differ and the answer must
    not depend on which one is installed. `x` is longitude: `point(lon, lat)` is
    what `_geo_to_point` writes, matching the usual x/y convention rather than
    the spoken "lat, long" order, which is the classic way to store every
    inspection in the Arabian Sea.
    """
    if value is None:
        return None
    if isinstance(value, str):
        lon, lat = (float(part) for part in value.strip("()").split(","))
    else:
        lon, lat = float(value[0]), float(value[1])
    return {"lat": lat, "lon": lon}


def _geo_to_point(geo: dict[str, float] | None):
    if geo is None:
        return None
    return func.point(geo["lon"], geo["lat"])


def _payload_from_row(row: Row) -> dict[str, Any]:
    """A `scans` row as the dict that was hashed. Order is irrelevant; types are not.

    **`frames` appears only when the column is not NULL**, and that omission is
    load-bearing rather than tidy. The chain hashes the keys the payload has, so
    adding `frames: None` to every single-frame row would change the digest of
    every scan recorded before multi-frame capture existed and `verify_chain`
    would report CONTENT_ALTERED on records nobody touched. A key that appears
    only when it carries something keeps them all verifiable.
    """
    mapping = row._mapping
    frames = mapping["frames"] if "frames" in mapping else None
    payload: dict[str, Any] = {
        "id": mapping["id"],
        "sku_id": mapping["sku_id"],
        "officer_id": mapping["officer_id"],
        "district": mapping["district"],
        "category": mapping["category"],
        "source": mapping["source"],
        "degradation_tier": mapping["degradation_tier"],
        "image_key": mapping["image_key"],
        "image_sha256": mapping["image_sha256"],
        "declaration_set": mapping["declaration_set"],
        "coverage": _as_float(mapping["coverage"]),
        "latency_ms": mapping["latency_ms"],
        "cache_hit": mapping["cache_hit"],
        "geo": _point_to_geo(mapping["geo"]),
        "captured_at": mapping["captured_at"],
        "synced_at": mapping["synced_at"],
        "model_versions": mapping["model_versions"],
        "rulepack_version": mapping["rulepack_version"],
        "record_sha256": mapping["record_sha256"],
        "prev_sha256": mapping["prev_sha256"],
        "chain_seq": mapping["chain_seq"],
    }
    if frames is not None:
        payload["frames"] = frames
    return payload


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class SqlUserStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _one(self, clause) -> UserRecord | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(t.users).where(clause)).first()
        if row is None:
            return None
        m = row._mapping
        return UserRecord(
            id=m["id"],
            email=m["email"],
            full_name=m["full_name"],
            password_hash=m["password_hash"],
            role=m["role"],
            district=m["district"],
            is_active=m["is_active"],
        )

    def by_email(self, email: str) -> UserRecord | None:
        # Lower-cased in the query rather than in Python so the comparison
        # matches whatever the database holds; sign-up normalises, but a row
        # imported from a department's existing user list may not have been.
        return self._one(func.lower(t.users.c.email) == email.lower())

    def by_id(self, user_id: UUID) -> UserRecord | None:
        return self._one(t.users.c.id == user_id)

    def add(self, user: UserRecord) -> UserRecord:
        with self.engine.begin() as conn:
            conn.execute(
                insert(t.users).values(
                    id=user.id,
                    email=user.email,
                    full_name=user.full_name,
                    password_hash=user.password_hash,
                    role=user.role,
                    district=user.district,
                    is_active=user.is_active,
                    created_at=datetime.now(UTC),
                )
            )
        return user


# ---------------------------------------------------------------------------
# SKUs
# ---------------------------------------------------------------------------


def _sku(row: Row) -> SkuRecord:
    m = row._mapping
    phash = m["phash"]
    return SkuRecord(
        id=m["id"],
        brand=m["brand"],
        brand_group=m["brand_group"],
        variant=m["variant"],
        pack_size=m["pack_size"],
        category=m["category"],
        barcode=m["barcode"],
        # BIT(64) reads as a string of ones and zeros. The rest of the system
        # speaks 16 hex characters, so it is converted here rather than leaking
        # a storage detail into `vision/` and the API.
        phash=f"{int(phash, 2):016x}" if phash else None,
        label_w_mm=_as_float(m["label_w_mm"]),
        label_h_mm=_as_float(m["label_h_mm"]),
        label_mm_observations=int(m["label_mm_observations"] or 0),
        # Welford's M2 is what is stored; the standard deviation is derived
        # here so no caller has to know that, and so the storage form stays
        # free to change. Undefined below two observations, and `None` says
        # that rather than `0.0` — a zero spread would read as a perfectly
        # measured SKU and produce a tolerance of nothing.
        label_w_mm_stddev=_stddev(
            _as_float(m["label_w_mm_m2"]), int(m["label_mm_observations"] or 0)
        ),
        scan_count=m["scan_count"],
    )


def _stddev(m2: float | None, observations: int) -> float | None:
    if m2 is None or observations < 2:
        return None
    return (max(m2, 0.0) / (observations - 1)) ** 0.5


class SqlSkuStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def by_id(self, sku_id: UUID) -> SkuRecord | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(t.skus).where(t.skus.c.id == sku_id)).first()
        return _sku(row) if row else None

    def by_barcode(self, barcode: str) -> SkuRecord | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(t.skus).where(t.skus.c.barcode == barcode)).first()
        return _sku(row) if row else None

    def by_phash(self, phash: str, *, max_hamming: int = 8) -> SkuRecord | None:
        """Nearest SKU within the Hamming radius section 4 specifies.

        Computed in Postgres with `bit_count(phash # :probe)` — XOR then count
        the set bits, which is the definition of Hamming distance and is one
        instruction on any modern CPU. Doing it in Python would mean reading
        every SKU row on every scan, which is the opposite of what exit zero is
        for.
        """
        probe = f"{int(phash, 16):064b}"
        distance = func.bit_count(t.skus.c.phash.op("#")(literal_column(f"B'{probe}'")))
        query = (
            select(t.skus)
            .where(t.skus.c.phash.isnot(None))
            .where(distance <= max_hamming)
            .order_by(distance)
            .limit(1)
        )
        with self.engine.connect() as conn:
            row = conn.execute(query).first()
        return _sku(row) if row else None

    def cache_for_district(self, district: str | None, limit: int) -> list[SkuRecord]:
        """Section 5's offline warm list. Long-tailed, so the top N covers most shelves.

        `district` is accepted and not filtered on, and that is deliberate rather
        than unfinished: `skus` has no district column because a SKU is not
        local — a Parle-G 100 g pack is the same pack in Khordha and in Cuttack.
        Making the warm list district-specific would need a join through `scans`,
        which is a real feature and a different one; today the argument shapes
        the endpoint's contract so adding it later changes no caller.
        """
        query = select(t.skus).order_by(t.skus.c.scan_count.desc()).limit(limit)
        with self.engine.connect() as conn:
            return [_sku(row) for row in conn.execute(query)]

    def bump_scan_count(self, sku_id: UUID) -> None:
        # `scan_count = scan_count + 1` in SQL, never read-then-write in Python:
        # this runs on several worker threads at once and a read-modify-write
        # loses increments silently.
        with self.engine.begin() as conn:
            conn.execute(
                update(t.skus)
                .where(t.skus.c.id == sku_id)
                .values(scan_count=t.skus.c.scan_count + 1)
            )

    def record_dimensions(self, sku_id: UUID, *, width_mm: float, height_mm: float) -> None:
        """Welford, as one UPDATE, for the same reason as the increment above.

        Every right-hand side below reads the row as it was *before* this
        statement, which is what makes the three-line recurrence safe to write
        as a single atomic update:

            n'    = n + 1
            mean' = mean + (x - mean) / n'
            M2'   = M2 + (x - mean) * (x - mean')

        Reading the row into Python first would lose an observation whenever two
        photographs of the same SKU finish together — silently, since the count
        would simply be one lower than the number of scans that took place, and
        nothing anywhere would report an error.

        `label_mm_observations = 0` makes the stored mean invisible to the
        recurrence: a dimension seeded by hand is replaced by the first real
        observation rather than averaged with it, because it was never measured
        and has no weight to carry.
        """
        count = t.skus.c.label_mm_observations
        mean = case((count == 0, literal(0.0)), else_=func.coalesce(t.skus.c.label_w_mm, 0.0))
        height_mean = case(
            (count == 0, literal(0.0)), else_=func.coalesce(t.skus.c.label_h_mm, 0.0)
        )
        delta = literal(width_mm) - mean
        new_count = count + 1
        new_mean = mean + delta / cast(new_count, Numeric)
        with self.engine.begin() as conn:
            conn.execute(
                update(t.skus)
                .where(t.skus.c.id == sku_id)
                .values(
                    label_w_mm=new_mean,
                    label_h_mm=height_mean
                    + (literal(height_mm) - height_mean) / cast(new_count, Numeric),
                    label_w_mm_m2=case(
                        (count == 0, literal(0.0)),
                        else_=func.coalesce(t.skus.c.label_w_mm_m2, 0.0)
                        + delta * (literal(width_mm) - new_mean),
                    ),
                    label_mm_observations=new_count,
                )
            )


# ---------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------


class SqlScanStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # -- reads --------------------------------------------------------------

    def get(self, scan_id: UUID) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(t.scans).where(t.scans.c.id == scan_id)).first()
        return _payload_from_row(row) if row else None

    def tail(self) -> ChainedRecord | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(t.scans).order_by(t.scans.c.chain_seq.desc()).limit(1)
            ).first()
        return from_row(_payload_from_row(row)) if row else None

    def all_records(self) -> list[ChainedRecord]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(t.scans).order_by(t.scans.c.chain_seq)).all()
        return [from_row(_payload_from_row(row)) for row in rows]

    def verdicts_for(self, scan_id: UUID) -> list[dict[str, Any]]:
        """Stored verdicts, with the measurements as numbers rather than Decimals.

        `measured`, `threshold` and `tolerance` are `NUMERIC` columns, so the
        driver hands them back as `Decimal`, and a `Decimal` is serialised to
        JSON as a **string**. `contracts.Verdict` declares all three as
        `float | None`, so the stored row was leaving this method in breach of
        the API's own contract.

        It was invisible from the scan itself: a fresh scan returns the engine's
        Python floats and never touches this path. Only the saved record does,
        which is why `GET /scans/{id}` served `"0.5"` where `POST /scans` served
        `0.5`, and why the full-record page — the one attached to a notice —
        crashed with `toFixed is not a function` while the result card beside it
        rendered perfectly. Measured 2026-09-18 on the two ratio rules that
        carry a measurement at tier C, `LMPC.CHAR.WIDTH_RATIO` and
        `LMPC.CONTRAST.NUMERALS`.

        Coerced here rather than in the browser, because a client that repairs
        its server's types is a client that hides the breach from every other
        consumer — the DOCX report and the PDF read the same rows.
        """
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(t.verdicts).where(t.verdicts.c.scan_id == scan_id).order_by(t.verdicts.c.id)
            ).all()
        return [
            {
                key: float(value) if key in _MEASURED_COLUMNS and value is not None else value
                for key, value in row._mapping.items()
                if key not in {"id", "scan_id"}
            }
            for row in rows
        ]

    def latest_for_sku(self, sku_id: UUID) -> UUID | None:
        with self.engine.connect() as conn:
            return conn.execute(
                select(t.scans.c.id)
                .where(t.scans.c.sku_id == sku_id)
                .order_by(t.scans.c.chain_seq.desc())
                .limit(1)
            ).scalar_one_or_none()

    # -- writes -------------------------------------------------------------

    def save(self, payload: dict[str, Any]) -> SyncOutcome:
        """Append one scan. Idempotent, and serialised against other appends.

        The advisory lock is transaction-scoped, so it is released by the commit
        or the rollback and cannot be leaked by a crashing worker. It is taken
        *before* reading the tail, which is the whole point: read-then-append
        without it is a lost-update race, and the thing being lost is the
        integrity of the chain rather than a counter.
        """
        scan_id = payload["id"]
        if not isinstance(scan_id, UUID):
            scan_id = UUID(str(scan_id))

        with self.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CHAIN_LOCK_KEY})

            existing = conn.execute(select(t.scans).where(t.scans.c.id == scan_id)).first()
            if existing is not None:
                # A retry. Not an error, and it must not append a second chain
                # entry — that would break gaplessness for a client whose only
                # mistake was losing signal.
                return SyncOutcome(record=from_row(_payload_from_row(existing)), created=False)

            tail_row = conn.execute(
                select(t.scans).order_by(t.scans.c.chain_seq.desc()).limit(1)
            ).first()
            previous = from_row(_payload_from_row(tail_row)) if tail_row else None

            # `synced_at` is set BEFORE hashing. Everything in a stored row is
            # inside its hash; a field added afterwards makes `verify_chain`
            # report CONTENT_ALTERED on records nobody touched.
            complete = {**payload, "id": scan_id, "synced_at": datetime.now(UTC)}
            chained = append(complete, previous=previous)
            row = chained.as_row()

            conn.execute(
                insert(t.scans).values(
                    id=scan_id,
                    sku_id=row.get("sku_id"),
                    officer_id=row.get("officer_id"),
                    district=row.get("district"),
                    category=row.get("category"),
                    source=row["source"],
                    degradation_tier=row["degradation_tier"],
                    image_key=row.get("image_key"),
                    image_sha256=row.get("image_sha256"),
                    frames=row.get("frames"),
                    declaration_set=row.get("declaration_set") or {},
                    coverage=row.get("coverage"),
                    latency_ms=row.get("latency_ms"),
                    cache_hit=row.get("cache_hit"),
                    geo=_geo_to_point(row.get("geo")),
                    captured_at=row["captured_at"],
                    synced_at=row["synced_at"],
                    model_versions=row.get("model_versions") or {},
                    rulepack_version=row["rulepack_version"],
                    record_sha256=row["record_sha256"],
                    prev_sha256=row["prev_sha256"],
                    chain_seq=row["chain_seq"],
                )
            )
        return SyncOutcome(record=chained, created=True)

    def save_verdicts(self, scan_id: UUID, verdicts: Iterable[dict[str, Any]]) -> None:
        """Replace this scan's verdicts. Called once, immediately after `save`.

        A delete-then-insert rather than an upsert because verdicts have no
        natural key — one rule can produce several verdicts for one scan, one
        per measured declaration — and because re-running the engine on a stored
        `DeclarationSet` (a rulepack upgrade, a dispute) must not leave the
        superseded verdicts behind beside the new ones.
        """
        rows = [{"scan_id": scan_id, **normalise_verdict(v)} for v in verdicts]
        with self.engine.begin() as conn:
            conn.execute(delete(t.verdicts).where(t.verdicts.c.scan_id == scan_id))
            if rows:
                conn.execute(insert(t.verdicts), rows)

    # -- the dashboard ------------------------------------------------------

    def facts(self, filters: ScanFilters) -> list[ScanFacts]:
        """Scans joined to their SKU and verdicts, filtered in SQL. Section 11.

        The verdict filters (`severity`, `rule_id`, `status`) are `EXISTS`
        subqueries, not joins. A join would multiply the scan row by its
        matching verdicts and every count on the dashboard would be inflated by
        however many rules happened to match — silently, and differently per
        filter, which is the hardest kind of wrong number to notice.
        """
        query = (
            select(
                t.scans,
                t.skus.c.brand,
                t.skus.c.brand_group,
                t.skus.c.variant,
                t.skus.c.pack_size,
                t.skus.c.category.label("sku_category"),
            )
            .select_from(t.scans.outerjoin(t.skus, t.scans.c.sku_id == t.skus.c.id))
            .order_by(t.scans.c.captured_at)
        )

        for clause in self._clauses(filters):
            query = query.where(clause)

        with self.engine.connect() as conn:
            rows = conn.execute(query).all()
            if not rows:
                return []
            ids = [row._mapping["id"] for row in rows]
            verdict_rows = conn.execute(
                select(t.verdicts).where(t.verdicts.c.scan_id.in_(ids)).order_by(t.verdicts.c.id)
            ).all()

        by_scan: dict[UUID, list[VerdictFact]] = {}
        for row in verdict_rows:
            m = row._mapping
            by_scan.setdefault(m["scan_id"], []).append(
                VerdictFact(
                    rule_id=m["rule_id"],
                    rule_ref=m["rule_ref"],
                    status=m["status"],
                    severity=m["severity"],
                    advisory=bool(m["advisory"]),
                    suppressed_by=m["suppressed_by"],
                )
            )

        return [self._facts(row, by_scan) for row in rows]

    def _clauses(self, filters: ScanFilters) -> list[Any]:
        clauses: list[Any] = []
        if filters.date_from:
            clauses.append(t.scans.c.captured_at >= filters.date_from)
        if filters.date_to:
            clauses.append(t.scans.c.captured_at <= filters.date_to)
        if filters.district:
            clauses.append(t.scans.c.district == filters.district)
        if filters.category:
            clauses.append(
                func.coalesce(t.scans.c.category, t.skus.c.category, UNCLASSIFIED)
                == filters.category
            )
        if filters.brand:
            clauses.append(
                func.lower(t.skus.c.brand).contains(filters.brand.lower())
                | func.lower(func.coalesce(t.skus.c.brand_group, "")).contains(
                    filters.brand.lower()
                )
            )
        if filters.barcode:
            clauses.append(t.skus.c.barcode == filters.barcode)

        verdict_conditions = []
        if filters.severity:
            verdict_conditions.append(t.verdicts.c.severity == filters.severity)
        if filters.rule_id:
            verdict_conditions.append(t.verdicts.c.rule_id == filters.rule_id)
        if filters.status:
            verdict_conditions.append(t.verdicts.c.status == filters.status)
        if verdict_conditions:
            clauses.append(
                select(literal_column("1"))
                .select_from(t.verdicts)
                .where(and_(t.verdicts.c.scan_id == t.scans.c.id, *verdict_conditions))
                .exists()
            )
        return clauses

    def _facts(self, row: Row, by_scan: dict[UUID, list[VerdictFact]]) -> ScanFacts:
        m = row._mapping
        return ScanFacts(
            id=m["id"],
            captured_at=m["captured_at"],
            district=m["district"],
            category=m["category"] or m["sku_category"] or UNCLASSIFIED,
            brand=m["brand"],
            brand_group=m["brand_group"],
            variant=m["variant"],
            pack_size=m["pack_size"],
            officer_id=m["officer_id"],
            sku_id=m["sku_id"],
            coverage=_as_float(m["coverage"]),
            latency_ms=m["latency_ms"],
            cache_hit=bool(m["cache_hit"]),
            degradation_tier=m["degradation_tier"],
            source=m["source"],
            synced=m["synced_at"] is not None,
            verdicts=tuple(by_scan.get(m["id"], ())),
        )


# ---------------------------------------------------------------------------
# Audit log and bulk jobs
# ---------------------------------------------------------------------------


class SqlAuditLog:
    """Section 18's `access_log`: who *did* look, as distinct from who *could*."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def record(
        self,
        *,
        user_id: UUID | None,
        action: str,
        entity: str,
        entity_id: str | None,
        ip: str | None = None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                insert(t.access_log).values(
                    user_id=user_id,
                    action=action,
                    entity=entity,
                    entity_id=entity_id,
                    ip=ip,
                    at=datetime.now(UTC),
                )
            )

    def entries(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(t.access_log).order_by(t.access_log.c.id)).all()
        return [dict(row._mapping) for row in rows]


class SqlBulkJobStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create(self, job: BulkJob) -> BulkJob:
        with self.engine.begin() as conn:
            conn.execute(
                insert(t.bulk_jobs).values(
                    id=job.id,
                    officer_id=job.officer_id,
                    total=job.total,
                    completed=job.completed,
                    failed=job.failed,
                    errors=list(job.errors),
                    created_at=job.created_at,
                    finished_at=job.finished_at,
                )
            )
        return job

    def get(self, job_id: UUID) -> BulkJob | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(t.bulk_jobs).where(t.bulk_jobs.c.id == job_id)).first()
            if row is None:
                return None
            scan_ids = conn.execute(
                select(t.bulk_job_scans.c.scan_id).where(t.bulk_job_scans.c.job_id == job_id)
            ).scalars()
            return self._job(row, tuple(scan_ids))

    def record_result(
        self, job_id: UUID, *, scan_id: UUID | None = None, error: str | None = None
    ) -> BulkJob | None:
        """One image finished. Atomic, because several workers finish at once.

        The counter is incremented **in SQL** — `completed = completed + 1` —
        rather than read into Python and written back. With eight worker threads
        the read-modify-write loses increments, and a job that never reaches its
        total is a hang with no error attached to it.
        """
        with self.engine.begin() as conn:
            values: dict[str, Any] = {}
            if error is None:
                values["completed"] = t.bulk_jobs.c.completed + 1
            else:
                values["failed"] = t.bulk_jobs.c.failed + 1
                # `jsonb || jsonb` appends a scalar as one element, so the
                # error list grows atomically in the database instead of being
                # read into Python, appended to, and written back — which loses
                # entries when two workers fail at the same moment.
                values["errors"] = t.bulk_jobs.c.errors.op("||")(
                    func.to_jsonb(cast(error, String))
                )

            row = conn.execute(
                update(t.bulk_jobs)
                .where(t.bulk_jobs.c.id == job_id)
                .values(**values)
                .returning(t.bulk_jobs)
            ).first()
            if row is None:
                return None
            if scan_id is not None:
                conn.execute(insert(t.bulk_job_scans).values(job_id=job_id, scan_id=scan_id))

            # Stamp the finish time in the same transaction, so a poller can
            # never see total == completed + failed with no `finished_at`.
            m = row._mapping
            if m["completed"] + m["failed"] >= m["total"] and m["finished_at"] is None:
                row = conn.execute(
                    update(t.bulk_jobs)
                    .where(t.bulk_jobs.c.id == job_id)
                    .values(finished_at=datetime.now(UTC))
                    .returning(t.bulk_jobs)
                ).first()

            scan_ids = conn.execute(
                select(t.bulk_job_scans.c.scan_id).where(t.bulk_job_scans.c.job_id == job_id)
            ).scalars()
            return self._job(row, tuple(scan_ids))

    def _job(self, row: Row, scan_ids: tuple[UUID, ...]) -> BulkJob:
        m = row._mapping
        return BulkJob(
            id=m["id"],
            officer_id=m["officer_id"],
            total=m["total"],
            completed=m["completed"],
            failed=m["failed"],
            errors=tuple(m["errors"] or ()),
            scan_ids=scan_ids,
            created_at=m["created_at"],
            finished_at=m["finished_at"],
        )


# ---------------------------------------------------------------------------
# Review resolutions and corrections
# ---------------------------------------------------------------------------


class SqlReviewStore:
    """Section 8b's *"one-click resolve, resolution stored as a labelled example
    for retraining"*, and section 14's corrections, over two append-only tables.

    Every method here inserts or selects. There is no `UPDATE` in this class and
    there must never be one: a row states what a named person concluded at a
    named time, and rewriting it would destroy the only record that they
    concluded something else first.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def resolve(self, resolution: ReviewResolution) -> ReviewResolution:
        with self.engine.begin() as conn:
            conn.execute(
                insert(t.review_resolutions).values(
                    scan_id=resolution.scan_id,
                    rule_id=resolution.rule_id,
                    decision=resolution.decision,
                    officer_id=resolution.officer_id,
                    note=resolution.note,
                    resolved_at=resolution.resolved_at,
                )
            )
        return resolution

    def correct(self, correction: Correction) -> Correction:
        with self.engine.begin() as conn:
            conn.execute(
                insert(t.corrections).values(
                    scan_id=correction.scan_id,
                    box_index=correction.box_index,
                    from_field=correction.from_field,
                    to_field=correction.to_field,
                    officer_id=correction.officer_id,
                    created_at=correction.created_at,
                )
            )
        return correction

    def resolutions_for(self, scan_id: UUID) -> list[ReviewResolution]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(t.review_resolutions)
                .where(t.review_resolutions.c.scan_id == scan_id)
                .order_by(t.review_resolutions.c.resolved_at)
            ).all()
        return [
            ReviewResolution(
                scan_id=r._mapping["scan_id"],
                rule_id=r._mapping["rule_id"],
                decision=r._mapping["decision"],
                officer_id=r._mapping["officer_id"],
                note=r._mapping["note"] or "",
                resolved_at=r._mapping["resolved_at"],
            )
            for r in rows
        ]

    def corrections_for(self, scan_id: UUID) -> list[Correction]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(t.corrections)
                .where(t.corrections.c.scan_id == scan_id)
                .order_by(t.corrections.c.created_at)
            ).all()
        return [
            Correction(
                scan_id=r._mapping["scan_id"],
                officer_id=r._mapping["officer_id"],
                box_index=r._mapping["box_index"],
                from_field=r._mapping["from_field"],
                to_field=r._mapping["to_field"],
                created_at=r._mapping["created_at"],
            )
            for r in rows
        ]

    def resolved_rules(self) -> dict[UUID, set[str]]:
        """One `DISTINCT` over a table that only ever holds REVIEW verdicts.

        `distinct()` rather than a `GROUP BY` in Python: an officer re-resolving
        the same rule writes a second row by design, and the queue only cares
        that at least one exists.
        """
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(
                    t.review_resolutions.c.scan_id, t.review_resolutions.c.rule_id
                ).distinct()
            ).all()
        settled: dict[UUID, set[str]] = {}
        for row in rows:
            settled.setdefault(row._mapping["scan_id"], set()).add(row._mapping["rule_id"])
        return settled


__all__ = [
    "CHAIN_LOCK_KEY",
    "SqlAuditLog",
    "SqlBulkJobStore",
    "SqlReviewStore",
    "SqlScanStore",
    "SqlSkuStore",
    "SqlUserStore",
]
