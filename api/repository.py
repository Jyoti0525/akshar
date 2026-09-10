"""Storage interfaces, and an in-memory implementation. AKSHAR.md sections 5, 10, 12.

The routers depend on these Protocols, never on SQLAlchemy. Three reasons, and
only the first is about testing:

1.  The whole API can be exercised with no Postgres, no Redis and no MinIO —
    which is how `tests/unit/test_api.py` runs in 2 seconds in CI.
2.  **`vision/` and `rules/` already work this way** (scale tier B and the SKU
    cache both take a callable from the caller), and a codebase where the
    boundary rule changes per layer is one where it stops being followed.
3.  Section 5's sync semantics — idempotent replay, server-assigned chain
    sequence — are *behaviour*, not SQL. Writing them against an interface
    means they are specified in one place and can be asserted directly.

**The one thing that must not be re-implemented per backend is idempotency.**
Section 5: *"Sync is idempotent, so replaying the outbox never duplicates a
record."* An officer's phone regains signal mid-upload, retries, and the same
UUIDv7 arrives twice. Both implementations must return the existing record
rather than raise, and a test asserts it against the interface so the SQL
version cannot quietly diverge.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from api.analytics import UNCLASSIFIED, ScanFacts, ScanFilters, VerdictFact
from evidence.chain import ChainedRecord, append, from_row


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: UUID
    email: str
    full_name: str
    password_hash: str
    role: str
    district: str | None = None
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class SkuRecord:
    id: UUID
    brand: str
    variant: str | None
    pack_size: str
    category: str
    barcode: str | None = None
    phash: str | None = None
    label_w_mm: float | None = None
    label_h_mm: float | None = None
    scan_count: int = 0
    brand_group: str | None = None


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    """What a write did — which the client needs, and an audit needs more.

    `created=False` is the normal, healthy outcome of a retry. It is reported
    rather than swallowed so the sync endpoint can answer honestly about what it
    accepted, and so a client that has lost track of its outbox can tell the
    difference between "stored" and "already stored".
    """

    record: ChainedRecord
    created: bool


VERDICT_FIELDS: tuple[str, ...] = (
    "rule_id",
    "rule_ref",
    "status",
    "severity",
    "field",
    "found",
    "expected",
    "message",
    "advisory",
    "suppressed_by",
    "respondent",
    "measured",
    "threshold",
    "tolerance",
)
"""The columns `verdicts` has, and therefore the keys `verdicts_for` returns.

Shared by both backends deliberately. The in-memory store originally kept
whatever dict it was handed, while the SQL store returned one key per column —
so `row["advisory"]` worked against Postgres and raised `KeyError` against
memory, and the dashboard's advisory rule would have been exercised by exactly
one of the two. A contract that is "whatever the caller passed" is not a
contract; this makes both stores answer the same shape.
"""


def normalise_verdict(verdict: dict[str, Any]) -> dict[str, Any]:
    """One verdict as the stores return it: every field present, defaults filled."""
    return {
        "rule_id": verdict["rule_id"],
        "rule_ref": verdict.get("rule_ref", ""),
        "status": verdict["status"],
        "severity": verdict.get("severity", "medium"),
        "field": verdict.get("field"),
        "found": verdict.get("found"),
        "expected": verdict.get("expected"),
        "message": verdict.get("message", ""),
        "advisory": bool(verdict.get("advisory")),
        "suppressed_by": verdict.get("suppressed_by"),
        "respondent": verdict.get("respondent", "manufacturer"),
        "measured": verdict.get("measured"),
        "threshold": verdict.get("threshold"),
        "tolerance": verdict.get("tolerance"),
        # Defaulted rather than required, so a verdict dict written before the
        # field existed — an offline outbox replay, a stored scan re-evaluated
        # after a rulepack upgrade — still round-trips instead of raising.
        "unit": verdict.get("unit", "mm"),
    }


ReviewDecision = Literal["complies", "does_not_comply", "recapture"]
"""What a human may conclude about a verdict the engine would not decide.

Three options, not two, and the third is the one that makes the vocabulary
honest. Section 8b issues REVIEW when a measurement lands inside tolerance of a
threshold — 1.96 mm against a 2.00 mm requirement — and the correct answer to
that is frequently neither verdict: it is *photograph it again with the card
flat*. Forcing that case into `complies` or `does_not_comply` would put a
coin-flip into an enforcement record and, worse, would feed the coin-flip back
into training as a labelled example.

Deliberately not the verdict vocabulary (`PASS`/`FAIL`). A `Verdict` is what the
rulepack decided; a resolution is what a person decided afterwards. Naming them
the same would invite somebody to write the resolution back over the verdict,
and section 5 says scans are immutable facts.
"""


@dataclass(frozen=True, slots=True)
class ReviewResolution:
    """One officer's decision on one REVIEW verdict. Append-only, like everything else."""

    scan_id: UUID
    rule_id: str
    decision: ReviewDecision
    officer_id: UUID
    note: str = ""
    resolved_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class Correction:
    """An officer relabelling a box. Section 14's training example, actually stored."""

    scan_id: UUID
    officer_id: UUID
    box_index: int | None = None
    from_field: str | None = None
    to_field: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ReviewStore(Protocol):
    """Officer output about a scan, in the two shapes section 14 asks for.

    Both are append-only and neither touches the scan, because section 5 makes
    the scan an immutable fact whose hash is in the evidence chain. A resolution
    that edited the verdict it resolved would break the chain at that row, and
    the tamper check in `evidence.chain.verify` would be right to fail.

    One store rather than two because both kinds of row answer the same
    question — *"what did a human who was actually doing the job say about
    this?"* — and because they are exported together: section 14's retraining
    feed is corrections plus resolutions, and splitting them across two
    interfaces would mean two exports that can disagree about a date range.
    """

    def resolve(self, resolution: ReviewResolution) -> ReviewResolution: ...
    def correct(self, correction: Correction) -> Correction: ...
    def resolutions_for(self, scan_id: UUID) -> list[ReviewResolution]: ...
    def corrections_for(self, scan_id: UUID) -> list[Correction]: ...

    def resolved_rules(self) -> dict[UUID, set[str]]:
        """Every scan with resolutions, and which of its rules are settled.

        Returned whole rather than queried per scan on purpose. The review queue
        is built from at most a few hundred `ScanFacts` already in memory, and
        asking the database once per row is the N+1 that turns a 40 ms dashboard
        into a 4 s one. Section 6 sizes the deployment at roughly 10,000 scans,
        of which only the REVIEW ones ever appear here, so the whole map is a
        few thousand strings at worst — the same bet `facts()` makes one method
        up, for the same reason.
        """
        ...


class UserStore(Protocol):
    def by_email(self, email: str) -> UserRecord | None: ...
    def by_id(self, user_id: UUID) -> UserRecord | None: ...


class SkuStore(Protocol):
    def by_id(self, sku_id: UUID) -> SkuRecord | None: ...
    def by_barcode(self, barcode: str) -> SkuRecord | None: ...
    def by_phash(self, phash: str, *, max_hamming: int = 8) -> SkuRecord | None: ...
    def cache_for_district(self, district: str | None, limit: int) -> list[SkuRecord]: ...

    def bump_scan_count(self, sku_id: UUID) -> None:
        """One more scan of this SKU. Called from the `bulk` queue, never inline.

        Section 8c keeps it off the critical path, and section 5 says what it is
        for: the offline warm list an officer's phone downloads before a drive.
        On a shelf of forty packets this is the same row forty times, so putting
        it in the scan response would add a row lock to the hot path and
        serialise a burst of scans behind each other.
        """
        ...


class ScanStore(Protocol):
    def get(self, scan_id: UUID) -> dict[str, Any] | None: ...
    def tail(self) -> ChainedRecord | None: ...
    def save(self, payload: dict[str, Any]) -> SyncOutcome: ...
    def all_records(self) -> list[ChainedRecord]: ...
    def verdicts_for(self, scan_id: UUID) -> list[dict[str, Any]]: ...
    def save_verdicts(self, scan_id: UUID, verdicts: Iterable[dict[str, Any]]) -> None: ...

    def latest_for_sku(self, sku_id: UUID) -> UUID | None:
        """The most recent scan of this SKU, or None. Section 4, exit zero.

        This is what makes the cache a cache rather than a claim. It is also
        what `evidence/storage.py` asks in order to decide that a repeat SKU
        stores no image — the same question, answered once.

        Deliberately *not* "the most recent scan whose rulepack matches": the
        caller checks that, because the two uses want different answers. The
        cache must miss after an amendment; the repeat-SKU storage rule must
        not, since the label was photographed either way.
        """
        ...

    def facts(self, filters: ScanFilters) -> list[ScanFacts]:
        """Scans joined to their SKU and verdicts, filtered. Section 11.

        **The store applies the filters; `api.analytics` does the shaping.** The
        filters are the selective part and belong in SQL; the aggregation is
        arithmetic and belongs somewhere both backends share, or the dashboard
        can report two different numbers for one question depending on how the
        stack was deployed.

        Returning rows rather than pre-aggregated counts is a deliberate bet on
        scale. Section 6 sizes the system at roughly 10,000 scans, and the plan
        already makes this trade once — the 1,700-row rule corpus is left
        unindexed because "a sequential scan beats HNSW at that size". If a
        deployment ever outgrows it, the fix is `GROUP BY` inside this method,
        with `api.analytics` kept as the reference the SQL must agree with.
        """
        ...


@dataclass(frozen=True, slots=True)
class BulkJob:
    """One bulk upload, and how far through it the workers are. Section 12.

    A job is a *receipt*, not a transaction. Section 8c puts bulk ingestion on
    the low-priority queue precisely because nobody is waiting on it, so an
    officer who uploaded 300 shelf photographs needs something to poll — and,
    more importantly, needs to be told which ones failed rather than being
    handed a count that quietly does not add up.

    `errors` holds text, not exceptions. It is shown to a person, so "image 41:
    upload is not a decodable image" is the useful form; a traceback belongs in
    the worker's log.
    """

    id: UUID
    officer_id: UUID
    total: int
    created_at: datetime
    completed: int = 0
    failed: int = 0
    scan_ids: tuple[UUID, ...] = ()
    errors: tuple[str, ...] = ()
    finished_at: datetime | None = None

    @property
    def pending(self) -> int:
        return max(0, self.total - self.completed - self.failed)

    @property
    def status(self) -> str:
        if self.pending:
            return "running"
        return "failed" if self.failed and not self.completed else "complete"


class BulkJobStore(Protocol):
    def create(self, job: BulkJob) -> BulkJob: ...
    def get(self, job_id: UUID) -> BulkJob | None: ...

    def record_result(
        self, job_id: UUID, *, scan_id: UUID | None = None, error: str | None = None
    ) -> BulkJob | None:
        """One image finished, well or badly. Called from a worker thread.

        Implementations must make this atomic against concurrent workers: two
        threads finishing at once must produce a count of two, and the obvious
        read-modify-write does not guarantee that.
        """
        ...


class AuditLog(Protocol):
    def record(
        self,
        *,
        user_id: UUID | None,
        action: str,
        entity: str,
        entity_id: str | None,
        ip: str | None = None,
    ) -> None: ...
    def entries(self) -> list[dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# In-memory implementation — tests, and an offline demo with no stack running
# ---------------------------------------------------------------------------


@dataclass
class InMemoryScanStore:
    """A scan store that keeps section 5's guarantees without a database.

    Not a mock. It implements the actual sync semantics — idempotent insert,
    server-assigned gapless `chain_seq`, immutability — so a test that passes
    here is testing the contract the SQL implementation must also meet.
    """

    _rows: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    _order: list[UUID] = field(default_factory=list)
    _verdicts: dict[UUID, list[dict[str, Any]]] = field(default_factory=dict)

    skus: SkuStore | None = None
    """Optional, and only the dashboard uses it. Brand and parent company live
    on `skus`, not on `scans` (section 10), so the join has to happen somewhere;
    doing it in the store keeps `api.analytics` a pure function of facts."""

    def get(self, scan_id: UUID) -> dict[str, Any] | None:
        return self._rows.get(scan_id)

    def tail(self) -> ChainedRecord | None:
        if not self._order:
            return None
        return from_row(self._rows[self._order[-1]])

    def save(self, payload: dict[str, Any]) -> SyncOutcome:
        scan_id = payload["id"]
        if not isinstance(scan_id, UUID):
            scan_id = UUID(str(scan_id))

        existing = self._rows.get(scan_id)
        if existing is not None:
            # THE idempotency guarantee. A retry is not an error and must not
            # append a second chain entry — that would break the chain's
            # gaplessness for a client that merely lost signal.
            return SyncOutcome(record=from_row(existing), created=False)

        # `synced_at` is set BEFORE hashing, not after.
        #
        # An earlier version stamped it onto the row `append()` returned, which
        # meant the stored row carried a field the digest had never seen — so
        # `verify_chain` reported CONTENT_ALTERED on records nobody had touched.
        # That is the exact failure `evidence/chain.py` warns about: "a false
        # alarm teaches people to ignore the alarm", and here it would have
        # taught a department to ignore an evidence-tampering warning.
        #
        # The invariant this restores is worth stating plainly: **everything in
        # a stored row is inside its hash.** An exclusion list would work too and
        # is much harder to keep true, because every new column is a chance to
        # forget.
        complete = {**payload, "id": scan_id, "synced_at": datetime.now(UTC)}
        chained = append(complete, previous=self.tail())
        self._rows[scan_id] = chained.as_row()
        self._order.append(scan_id)
        return SyncOutcome(record=chained, created=True)

    def all_records(self) -> list[ChainedRecord]:
        return [from_row(self._rows[scan_id]) for scan_id in self._order]

    def verdicts_for(self, scan_id: UUID) -> list[dict[str, Any]]:
        return list(self._verdicts.get(scan_id, []))

    def save_verdicts(self, scan_id: UUID, verdicts: Iterable[dict[str, Any]]) -> None:
        self._verdicts[scan_id] = [normalise_verdict(v) for v in verdicts]

    def latest_for_sku(self, sku_id: UUID) -> UUID | None:
        # `_order` is insertion order, and ids are UUIDv7, so the last match is
        # the most recent scan. Walking backwards means the common case — a SKU
        # scanned moments ago on the same shelf — stops at the first row.
        for scan_id in reversed(self._order):
            if self._rows[scan_id].get("sku_id") == sku_id:
                return scan_id
        return None

    def facts(self, filters: ScanFilters) -> list[ScanFacts]:
        rows = [self._facts_for(scan_id) for scan_id in self._order]
        return [row for row in rows if filters.matches(row)]

    def _facts_for(self, scan_id: UUID) -> ScanFacts:
        row = self._rows[scan_id]
        sku = None
        sku_id = row.get("sku_id")
        if sku_id is not None and self.skus is not None:
            sku = getattr(self.skus, "by_id", lambda _: None)(sku_id)

        return ScanFacts(
            id=scan_id,
            captured_at=_as_datetime(row.get("captured_at")),
            district=row.get("district"),
            # The category the rules were EVALUATED under, not the SKU's — see
            # D16. When a scan has no category of its own we fall back to the
            # SKU's, and only then to "unclassified".
            category=row.get("category") or (sku.category if sku else None) or UNCLASSIFIED,
            brand=sku.brand if sku else None,
            brand_group=sku.brand_group if sku else None,
            officer_id=row.get("officer_id"),
            sku_id=sku_id,
            coverage=row.get("coverage"),
            latency_ms=row.get("latency_ms"),
            cache_hit=bool(row.get("cache_hit")),
            degradation_tier=row.get("degradation_tier", "L0"),
            source=row.get("source", "photo"),
            synced=row.get("synced_at") is not None,
            verdicts=tuple(
                VerdictFact(
                    rule_id=v["rule_id"],
                    rule_ref=v["rule_ref"],
                    status=v["status"],
                    severity=v["severity"],
                    advisory=v["advisory"],
                    suppressed_by=v["suppressed_by"],
                )
                for v in self._verdicts.get(scan_id, [])
            ),
        )


def _as_datetime(value: Any) -> datetime:
    """Rows arrive from memory as datetimes and from JSON as ISO strings."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return datetime.now(UTC)


@dataclass
class InMemoryUserStore:
    _by_email: dict[str, UserRecord] = field(default_factory=dict)

    def add(self, user: UserRecord) -> UserRecord:
        self._by_email[user.email.lower()] = user
        return user

    def by_email(self, email: str) -> UserRecord | None:
        return self._by_email.get(email.lower())

    def by_id(self, user_id: UUID) -> UserRecord | None:
        return next((u for u in self._by_email.values() if u.id == user_id), None)


@dataclass
class InMemorySkuStore:
    _skus: list[SkuRecord] = field(default_factory=list)

    def add(self, sku: SkuRecord) -> SkuRecord:
        self._skus.append(sku)
        return sku

    def by_id(self, sku_id: UUID) -> SkuRecord | None:
        return next((s for s in self._skus if s.id == sku_id), None)

    def by_barcode(self, barcode: str) -> SkuRecord | None:
        return next((s for s in self._skus if s.barcode == barcode), None)

    def by_phash(self, phash: str, *, max_hamming: int = 8) -> SkuRecord | None:
        """Nearest SKU within the Hamming radius section 4 specifies.

        Exact-match-only would defeat the point: two photographs of the same
        pack under different shop lighting differ by a few bits, and the whole
        cache argument rests on recognising that as the same SKU.
        """
        best: SkuRecord | None = None
        best_distance = max_hamming + 1
        for sku in self._skus:
            if not sku.phash:
                continue
            distance = _hamming(sku.phash, phash)
            if distance < best_distance:
                best, best_distance = sku, distance
        return best if best_distance <= max_hamming else None

    def cache_for_district(self, district: str | None, limit: int) -> list[SkuRecord]:
        """Section 5: the top-N most-scanned SKUs, for offline cache warming.

        "Retail is heavily long-tailed, so a few megabytes covers close to 90%
        of what's actually on those shelves."
        """
        return sorted(self._skus, key=lambda s: s.scan_count, reverse=True)[:limit]

    def bump_scan_count(self, sku_id: UUID) -> None:
        # `SkuRecord` is frozen, so this replaces the row rather than mutating
        # it. Cheap here, and it keeps the record type immutable everywhere else
        # — a SKU handed to the rules layer must not change under it mid-scan.
        for index, sku in enumerate(self._skus):
            if sku.id == sku_id:
                self._skus[index] = replace(sku, scan_count=sku.scan_count + 1)
                return


@dataclass
class InMemoryBulkJobStore:
    """Bulk job receipts, guarded by a lock.

    The lock is not decoration. Every other in-memory store here is written from
    the request thread; this one is written from Dramatiq worker threads, several
    at a time, and `dataclasses.replace` on a frozen record is a read-modify-write.
    Without the lock two images finishing simultaneously increment `completed`
    once, and a job silently never reaches its total — a hang with no error, which
    is the hardest kind of bug to be handed by a district office at 9 pm.
    """

    _jobs: dict[UUID, BulkJob] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def create(self, job: BulkJob) -> BulkJob:
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: UUID) -> BulkJob | None:
        return self._jobs.get(job_id)

    def record_result(
        self, job_id: UUID, *, scan_id: UUID | None = None, error: str | None = None
    ) -> BulkJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            updated = replace(
                job,
                completed=job.completed + (1 if error is None else 0),
                failed=job.failed + (1 if error is not None else 0),
                scan_ids=job.scan_ids + ((scan_id,) if scan_id else ()),
                errors=job.errors + ((error,) if error else ()),
            )
            if updated.pending == 0:
                updated = replace(updated, finished_at=datetime.now(UTC))
            self._jobs[job_id] = updated
            return updated


@dataclass
class InMemoryReviewStore:
    """Two append-only lists. Locked, because a bulk job resolves from a worker.

    `_settled` is a derived index rather than a recomputation, for the reason
    `resolved_rules` gives: the dashboard asks for it on every render and the
    review queue is the one panel on that page representing work owed rather
    than work done.
    """

    _resolutions: list[ReviewResolution] = field(default_factory=list)
    _corrections: list[Correction] = field(default_factory=list)
    _settled: dict[UUID, set[str]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def resolve(self, resolution: ReviewResolution) -> ReviewResolution:
        with self._lock:
            self._resolutions.append(resolution)
            # `setdefault` then `add`, not `|=` on a fetched set: a second
            # officer resolving a different rule on the same scan must widen
            # the entry, not replace it.
            self._settled.setdefault(resolution.scan_id, set()).add(resolution.rule_id)
        return resolution

    def correct(self, correction: Correction) -> Correction:
        with self._lock:
            self._corrections.append(correction)
        return correction

    def resolutions_for(self, scan_id: UUID) -> list[ReviewResolution]:
        return [r for r in self._resolutions if r.scan_id == scan_id]

    def corrections_for(self, scan_id: UUID) -> list[Correction]:
        return [c for c in self._corrections if c.scan_id == scan_id]

    def resolved_rules(self) -> dict[UUID, set[str]]:
        with self._lock:
            return {scan_id: set(rules) for scan_id, rules in self._settled.items()}


@dataclass
class InMemoryAuditLog:
    _entries: list[dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        *,
        user_id: UUID | None,
        action: str,
        entity: str,
        entity_id: str | None,
        ip: str | None = None,
    ) -> None:
        self._entries.append(
            {
                "user_id": user_id,
                "action": action,
                "entity": entity,
                "entity_id": entity_id,
                "ip": ip,
                "at": datetime.now(UTC),
            }
        )

    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)


def _hamming(a: str, b: str) -> int:
    """Hamming distance between two hex-encoded 64-bit hashes."""
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return 65  # unparseable: further than any threshold allows


__all__ = [
    "VERDICT_FIELDS",
    "AuditLog",
    "BulkJob",
    "BulkJobStore",
    "Correction",
    "InMemoryAuditLog",
    "InMemoryBulkJobStore",
    "InMemoryReviewStore",
    "InMemoryScanStore",
    "InMemorySkuStore",
    "InMemoryUserStore",
    "ReviewDecision",
    "ReviewResolution",
    "ReviewStore",
    "ScanStore",
    "SkuRecord",
    "SkuStore",
    "SyncOutcome",
    "UserRecord",
    "UserStore",
    "normalise_verdict",
]
