"""Dashboard aggregation. AKSHAR.md section 11.

Pure functions over a list of facts. No SQL, no HTTP, no FastAPI. The store
pushes down the four global filters — the selective part — and the shaping
happens here, so the in-memory and Postgres backends cannot produce different
numbers for the same question. A dashboard that disagrees with itself depending
on deployment is worse than no dashboard.

**Three counting rules, and every one of them changes the headline figure.**

*Advisory verdicts are not non-compliance.* Section 13 puts the five unit-symbol
checks in a separate advisory block "so a `250 ML` never sits beside a missing
MRP". If they are counted here, section 11's most useful chart — violations by
rule — reports that the country's biggest labelling problem is capitalising the
litre symbol, and the department publishes an advisory about the wrong thing.

*Suppressed verdicts are not counted at all.* `Verdict.suppressed_by` is set
when another rule measured the same thing and won: "one measurement yields one
verdict". Counting both double-counts a single defect and inflates every rate on
the page.

*NO_DATA is never a failure.* The plan is explicit that absence of evidence is
not evidence of a violation. A scan whose height rules all returned NO_DATA
because there was no scale reference is a scan we learned nothing from — it must
not appear as a compliant one either, so it is excluded from the rate's
denominator rather than counted as a pass.

Section 11's eight questions map to the functions here:

| Q | Question                                    | Function            |
|---|---------------------------------------------|---------------------|
| 1 | Is non-compliance getting better or worse?  | `overview` (trend)  |
| 2 | Which rule is broken most often?            | `by_rule`           |
| 3 | Which brands are repeat offenders?          | `by_brand`          |
| 4 | Which categories are worst?                 | `by_category`       |
| 5 | Which districts are dark?                   | `by_district`       |
| 6 | What needs a human decision right now?      | `review_queue`      |
| 7 | Is a brand improving after being notified?  | `brand_detail`      |
| 8 | Is the tool itself healthy?                 | `health`            |

*"If a chart doesn't map to a numbered question, cut it."*
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

UNCLASSIFIED = "unclassified"

# Section 11: "Horizontal bars, descending, top eight."
TOP_RULES = 8

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


@dataclass(frozen=True, slots=True)
class VerdictFact:
    """One verdict, flattened to what aggregation needs.

    Deliberately not `contracts.Verdict`: the message and the remediation text
    are report content, and carrying them through a 10,000-row aggregation costs
    memory to no purpose.
    """

    rule_id: str
    rule_ref: str
    status: str
    severity: str
    advisory: bool = False
    suppressed_by: str | None = None

    def counts(self) -> bool:
        """Whether this verdict participates in compliance arithmetic at all."""
        return self.suppressed_by is None and not self.advisory

    def is_failure(self) -> bool:
        return self.counts() and self.status == "FAIL"

    def needs_human(self) -> bool:
        return self.counts() and self.status == "REVIEW"


@dataclass(frozen=True, slots=True)
class ScanFacts:
    """One scan, joined to its SKU, flattened for aggregation."""

    id: UUID
    captured_at: datetime
    district: str | None
    category: str
    brand: str | None
    brand_group: str | None
    officer_id: UUID | None
    sku_id: UUID | None
    coverage: float | None
    latency_ms: int | None
    cache_hit: bool
    degradation_tier: str
    source: str
    synced: bool
    variant: str | None = None
    """The SKU's variant, e.g. "Original" for a Dettol soap. Carried so the
    review queue can name the packet a supervisor is deciding about rather than
    only its brand — `Dettol` is not enough to pick one of nine Dettol SKUs out
    of a worklist, and the supervisor is being asked for a compliance
    conclusion on a specific pack."""
    pack_size: str | None = None
    """The SKU's declared pack size, e.g. "52 ml". Same reason as `variant`, and
    it is the field that most often distinguishes two otherwise identical rows,
    because Rule 7(2) Table I bands its thresholds on net quantity."""
    verdicts: tuple[VerdictFact, ...] = ()

    # -- derived --------------------------------------------------------

    @property
    def scored(self) -> tuple[VerdictFact, ...]:
        return tuple(v for v in self.verdicts if v.counts())

    @property
    def failures(self) -> tuple[VerdictFact, ...]:
        return tuple(v for v in self.verdicts if v.is_failure())

    @property
    def is_non_compliant(self) -> bool:
        return bool(self.failures)

    @property
    def high_severity_failures(self) -> int:
        return sum(1 for v in self.failures if v.severity == "high")

    @property
    def needs_review(self) -> bool:
        return any(v.needs_human() for v in self.verdicts)

    @property
    def is_conclusive(self) -> bool:
        """Did we learn anything about compliance from this scan?

        A scan whose every countable verdict came back NO_DATA or
        NOT_APPLICABLE told us nothing. It is excluded from the rate rather than
        counted as compliant — otherwise a bad photograph improves the numbers,
        which is precisely the incentive an enforcement tool must not create.
        """
        return any(v.status in {"PASS", "FAIL", "REVIEW"} for v in self.scored)

    @property
    def parent(self) -> str | None:
        """The entity a legal notice is addressed to. Section 10."""
        return self.brand_group or self.brand


@dataclass(frozen=True, slots=True)
class ScanFilters:
    """Section 11's four global filters, plus paging.

    "Each is a URL parameter, so any view can be shared as a link — which
    matters more than it sounds, because that's how a finding gets escalated to
    a controller."
    """

    date_from: date | None = None
    date_to: date | None = None
    district: str | None = None
    category: str | None = None
    severity: str | None = None
    brand: str | None = None
    rule_id: str | None = None
    status: str | None = None
    barcode: str | None = None

    def matches(self, scan: ScanFacts) -> bool:
        """Applied in-process by the in-memory store; pushed into SQL by the other."""
        captured = scan.captured_at.astimezone(UTC).date()
        if self.date_from and captured < self.date_from:
            return False
        if self.date_to and captured > self.date_to:
            return False
        if self.district and scan.district != self.district:
            return False
        if self.category and scan.category != self.category:
            return False
        if self.brand and self.brand.lower() not in (scan.brand or "").lower():
            return False
        if self.severity:
            floor = SEVERITY_RANK.get(self.severity, 0)
            if not any(SEVERITY_RANK.get(v.severity, 0) >= floor for v in scan.failures):
                return False
        if self.rule_id and not any(v.rule_id == self.rule_id for v in scan.scored):
            return False
        if self.status:
            if self.status == "REVIEW" and not scan.needs_review:
                return False
            if self.status == "FAIL" and not scan.is_non_compliant:
                return False
            if self.status == "PASS" and (scan.is_non_compliant or not scan.is_conclusive):
                return False
        return True

    def previous_period(self) -> ScanFilters | None:
        """The same window, immediately before this one.

        Section 11: every overview tile "shows the value, the change against the
        previous period". Without a bounded window there is no previous period
        to compare with, so the tiles report no change rather than inventing one.
        """
        if self.date_from is None or self.date_to is None:
            return None
        span = self.date_to - self.date_from + timedelta(days=1)
        return ScanFilters(
            date_from=self.date_from - span,
            date_to=self.date_from - timedelta(days=1),
            district=self.district,
            category=self.category,
            severity=self.severity,
        )


# ---------------------------------------------------------------------------
# Shared arithmetic
# ---------------------------------------------------------------------------


def _rate(non_compliant: int, conclusive: int) -> float | None:
    """Non-compliance rate, or None when there is nothing to divide by.

    None rather than 0.0 deliberately. A district with no scans has an *unknown*
    compliance rate, and section 11's districts view exists to find exactly those
    — "that last column identifies districts that are dark rather than
    compliant". Rendering 0% would say the opposite of the truth.
    """
    if conclusive == 0:
        return None
    return round(non_compliant / conclusive, 4)


def _delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return round(current - previous, 4)


@dataclass
class _Bucket:
    """Running totals for one slice — a brand, a rule, a district."""

    scans: int = 0
    conclusive: int = 0
    non_compliant: int = 0
    high_severity: int = 0
    review: int = 0
    skus: set[UUID] = field(default_factory=set)
    officers: set[UUID] = field(default_factory=set)
    rule_failures: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    last_seen: datetime | None = None

    def add(self, scan: ScanFacts) -> None:
        self.scans += 1
        self.conclusive += int(scan.is_conclusive)
        self.non_compliant += int(scan.is_non_compliant)
        self.high_severity += scan.high_severity_failures
        self.review += int(scan.needs_review)
        if scan.sku_id:
            self.skus.add(scan.sku_id)
        if scan.officer_id:
            self.officers.add(scan.officer_id)
        for verdict in scan.failures:
            self.rule_failures[verdict.rule_id] += 1
        if self.last_seen is None or scan.captured_at > self.last_seen:
            self.last_seen = scan.captured_at

    def worst_rule(self) -> str | None:
        if not self.rule_failures:
            return None
        return max(self.rule_failures.items(), key=lambda kv: (kv[1], kv[0]))[0]

    def as_row(self) -> dict[str, Any]:
        return {
            "scans": self.scans,
            "skus_checked": len(self.skus),
            "fail_rate": _rate(self.non_compliant, self.conclusive),
            "high_severity": self.high_severity,
            "awaiting_review": self.review,
            "worst_rule": self.worst_rule(),
            "last_scanned": self.last_seen.isoformat() if self.last_seen else None,
        }


def _group(scans: Iterable[ScanFacts], key) -> dict[Any, _Bucket]:
    buckets: dict[Any, _Bucket] = defaultdict(_Bucket)
    for scan in scans:
        buckets[key(scan)].add(scan)
    return buckets


# ---------------------------------------------------------------------------
# The views
# ---------------------------------------------------------------------------


def overview(
    scans: Sequence[ScanFacts],
    previous: Sequence[ScanFacts] | None = None,
    *,
    resolved: Mapping[UUID, AbstractSet[str]] | None = None,
    weeks: int = 12,
) -> dict[str, Any]:
    """Q1, Q6, Q8 — five tiles, one trend line, one bar chart, one worklist.

    `previous=None` means *there is no comparable period* — an unbounded "all
    time" view has nothing before it. That is a different statement from an
    empty previous period, which means enforcement genuinely started inside this
    window, and the tiles must not conflate them: "—" tells a supervisor we are
    not comparing, "0" tells them last month was silent. An earlier version
    wrote `len(previous) or None` and turned every honest zero into a dash.
    """
    conclusive = sum(1 for s in scans if s.is_conclusive)
    non_compliant = sum(1 for s in scans if s.is_non_compliant)
    rate = _rate(non_compliant, conclusive)

    def prior(value):
        return None if previous is None else value(previous)

    prior_rate = (
        None
        if previous is None
        else _rate(
            sum(1 for s in previous if s.is_non_compliant),
            sum(1 for s in previous if s.is_conclusive),
        )
    )

    return {
        "tiles": {
            "scans": {"value": len(scans), "previous": prior(len)},
            "unique_skus": {
                "value": len({s.sku_id for s in scans if s.sku_id}),
                "previous": prior(lambda rows: len({s.sku_id for s in rows if s.sku_id})),
            },
            "non_compliance_rate": {
                "value": rate,
                "previous": prior_rate,
                "change": _delta(rate, prior_rate),
            },
            "high_severity_open": {
                "value": sum(s.high_severity_failures for s in scans),
                "previous": prior(lambda rows: sum(s.high_severity_failures for s in rows)),
            },
            # Counted through the same filter the queue below it uses, or the
            # tile would say "6 awaiting review" over a list of four. The
            # previous period is deliberately *not* filtered: resolutions are
            # recorded now and would retroactively empty a comparison window,
            # making every period look worse than the one before it for ever.
            "awaiting_review": {
                "value": len(review_queue(scans, resolved=resolved, limit=len(scans) or 1)),
                "previous": prior(lambda rows: sum(1 for s in rows if s.needs_review)),
            },
        },
        "trend": weekly_trend(scans, weeks=weeks),
        "violations_by_rule": by_rule(scans)[:TOP_RULES],
        "review_queue": review_queue(scans, resolved=resolved),
    }


def weekly_trend(scans: Sequence[ScanFacts], *, weeks: int = 12) -> list[dict[str, Any]]:
    """Q1 — weekly buckets, ISO weeks.

    Weeks with no scans are emitted with a null rate rather than skipped, so a
    gap in enforcement activity shows as a gap in the line instead of being
    smoothed into a trend that never happened.
    """
    if not scans:
        return []

    latest = max(s.captured_at for s in scans).astimezone(UTC).date()
    start_of_week = latest - timedelta(days=latest.weekday())
    windows = [start_of_week - timedelta(weeks=offset) for offset in range(weeks - 1, -1, -1)]

    buckets: dict[date, _Bucket] = {w: _Bucket() for w in windows}
    for scan in scans:
        day = scan.captured_at.astimezone(UTC).date()
        week = day - timedelta(days=day.weekday())
        if week in buckets:
            buckets[week].add(scan)

    return [
        {
            "week": week.isoformat(),
            "scans": bucket.scans,
            # The numerator and the denominator, not only the quotient. Section
            # 11 gives every chart a table view, and a table that repeats the
            # percentage adds nothing: what a controller about to quote a figure
            # needs is how many scans it rests on and how many of them told us
            # anything at all. `conclusive` is the denominator — scans whose
            # every verdict was NO_DATA are excluded from the rate, and a reader
            # who cannot see that cannot check the arithmetic.
            "non_compliant": bucket.non_compliant,
            "conclusive": bucket.conclusive,
            "non_compliance_rate": _rate(bucket.non_compliant, bucket.conclusive),
        }
        for week, bucket in sorted(buckets.items())
    ]


def by_rule(scans: Sequence[ScanFacts]) -> list[dict[str, Any]]:
    """Q2 — and, quietly, an audit of our own rulepack.

    Section 11: *"A rule failing on 95% of products is more likely a bug in our
    regex than a national conspiracy."* That is why `checked` is reported beside
    `failed`: a raw failure count cannot distinguish a rule that fires constantly
    from one that is simply evaluated constantly, and `suspect` marks the ratio
    worth a second look before anyone cites it in an advisory.
    """
    checked: dict[str, int] = defaultdict(int)
    failed: dict[str, int] = defaultdict(int)
    refs: dict[str, str] = {}
    severities: dict[str, str] = {}
    brands: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for scan in scans:
        for verdict in scan.scored:
            if verdict.status in {"PASS", "FAIL", "REVIEW"}:
                checked[verdict.rule_id] += 1
            refs.setdefault(verdict.rule_id, verdict.rule_ref)
            severities.setdefault(verdict.rule_id, verdict.severity)
            if verdict.status == "FAIL":
                failed[verdict.rule_id] += 1
                if scan.brand:
                    brands[verdict.rule_id][scan.brand] += 1

    rows = []
    for rule_id, fails in failed.items():
        seen = checked.get(rule_id, 0)
        ratio = _rate(fails, seen)
        top = sorted(brands[rule_id].items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        rows.append(
            {
                "rule_id": rule_id,
                "rule_ref": refs.get(rule_id, ""),
                "severity": severities.get(rule_id, "medium"),
                "checked": seen,
                "failed": fails,
                "fail_rate": ratio,
                "suspect": bool(ratio is not None and ratio > 0.95 and seen >= 20),
                "top_brands": [{"brand": b, "failures": n} for b, n in top],
            }
        )
    rows.sort(key=lambda row: (-row["failed"], row["rule_id"]))
    return rows


MIN_TREND_SCANS = 6
"""Below this, a "trend" is one packet changing its mind.

Three scans either side of the midpoint is the least that can distinguish a
direction from noise, and a brand named as improving or worsening in a
departmental report on the strength of two photographs is a claim that will not
survive being questioned.
"""


def _trend(scans: Sequence[ScanFacts]) -> str | None:
    """Q7 in one word, for the brands table's `Trend` column.

    The period is split at its own midpoint and the non-compliance rate compared
    across the halves. Deliberately *not* a slope over weekly buckets: enforcement
    scanning is bursty — a district works one market on one morning — so a
    regression over calendar weeks mostly measures which weeks anyone went out.

    Returns None rather than "flat" when there is not enough to say. The three
    states a reader can act on are better, worse and *we do not know*, and
    collapsing the third into "flat" is how a brand gets left alone because a
    column said nothing was happening.
    """
    dated = sorted(scans, key=lambda s: s.captured_at)
    if len(dated) < MIN_TREND_SCANS:
        return None

    first, last = dated[0].captured_at, dated[-1].captured_at
    if first == last:
        return None
    midpoint = first + (last - first) / 2

    early = [s for s in dated if s.captured_at < midpoint]
    late = [s for s in dated if s.captured_at >= midpoint]
    early_rate = _rate(
        sum(1 for s in early if s.is_non_compliant), sum(1 for s in early if s.is_conclusive)
    )
    late_rate = _rate(
        sum(1 for s in late if s.is_non_compliant), sum(1 for s in late if s.is_conclusive)
    )
    if early_rate is None or late_rate is None:
        return None

    delta = late_rate - early_rate
    # Five points. Smaller than that, on the scan counts a district actually
    # produces, is inside the noise of which packets happened to be on the shelf.
    if delta <= -0.05:
        return "improving"
    if delta >= 0.05:
        return "worsening"
    return "flat"


def by_brand(scans: Sequence[ScanFacts]) -> list[dict[str, Any]]:
    """Q3 — sorted by high-severity count, not fail rate.

    Section 11 is explicit and the reasoning is worth keeping in the code:
    *"A small brand with two SKUs and a 100% fail rate is noise; a national brand
    at 30% across forty SKUs is a case worth opening."* Sorting by rate puts the
    noise on top of the page every single morning.

    `trend` is the column section 11's table names between `Worst rule` and
    `Last scanned`. It is computed here rather than on the client so the screen,
    the CSV export and the PDF summary cannot disagree about whether a brand is
    improving — which is the one column somebody will quote back at a hearing.
    """
    buckets = _group((s for s in scans if s.brand), lambda s: s.brand)
    parents = {s.brand: s.brand_group for s in scans if s.brand}
    by_name: dict[str, list[ScanFacts]] = defaultdict(list)
    for scan in scans:
        if scan.brand:
            by_name[scan.brand].append(scan)

    rows = [
        {
            "brand": brand,
            "parent": parents.get(brand),
            **bucket.as_row(),
            "trend": _trend(by_name[brand]),
        }
        for brand, bucket in buckets.items()
    ]
    rows.sort(key=lambda row: (-row["high_severity"], -(row["fail_rate"] or 0), row["brand"]))
    return rows


def brand_detail(scans: Sequence[ScanFacts], brand: str) -> dict[str, Any]:
    """Q7 — did behaviour change after the brand was notified?

    The timeline is returned whole, ordered, with the rules each scan failed.
    The notification marker itself is not stored here: it is a departmental
    action, not a scan fact, and the caller overlays it.
    """
    mine = [s for s in scans if s.brand == brand]
    timeline = [
        {
            "scan_id": str(s.id),
            "captured_at": s.captured_at.isoformat(),
            "sku_id": str(s.sku_id) if s.sku_id else None,
            "district": s.district,
            "non_compliant": s.is_non_compliant,
            "failed_rules": [v.rule_id for v in s.failures],
        }
        for s in sorted(mine, key=lambda s: s.captured_at)
    ]
    bucket = _Bucket()
    for scan in mine:
        bucket.add(scan)
    return {
        "brand": brand,
        "parent": next((s.brand_group for s in mine if s.brand_group), None),
        **bucket.as_row(),
        "trend": _trend(mine),
        "rules": by_rule(mine),
        "timeline": timeline,
    }


def by_category(scans: Sequence[ScanFacts]) -> list[dict[str, Any]]:
    """Q4 — and the slide that proves we implemented the right law.

    Section 11: *"A category chart showing cement and phone chargers alongside
    biscuits is proof we're implementing the right law."* Competing tools are
    food-first because they come from FSSAI; LMPC covers every commodity.
    """
    buckets = _group(scans, lambda s: s.category or UNCLASSIFIED)
    rows = [{"category": name, **bucket.as_row()} for name, bucket in buckets.items()]
    rows.sort(key=lambda row: (-(row["fail_rate"] or 0), -row["scans"], row["category"]))
    return rows


def by_district(
    scans: Sequence[ScanFacts],
    *,
    sku_population: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Q5 — which districts are dark rather than compliant.

    `coverage` is the column the view exists for. It is None unless the caller
    supplies an estimated SKU population, because a coverage figure computed
    against an unknown denominator is a guess wearing a percentage sign.
    """
    population = sku_population or {}
    buckets = _group(scans, lambda s: s.district or UNCLASSIFIED)

    rows = []
    for name, bucket in buckets.items():
        estimate = population.get(name)
        rows.append(
            {
                "district": name,
                "active_officers": len(bucket.officers),
                "coverage": (round(len(bucket.skus) / estimate, 4) if estimate else None),
                "sku_population_estimate": estimate,
                **bucket.as_row(),
            }
        )
    rows.sort(key=lambda row: (-row["scans"], row["district"]))
    return rows


def review_queue(
    scans: Sequence[ScanFacts],
    *,
    resolved: Mapping[UUID, AbstractSet[str]] | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Q6 — a worklist, not a chart.

    Section 11: it belongs on the front page because *"it's the only thing there
    representing work owed by the person looking at it"*. Oldest first: a review
    item that has waited three weeks is more urgent than this morning's.

    **`resolved` is what makes it a worklist rather than a list.** It maps a
    scan id to the rules a human has already settled on it (`ReviewStore.
    resolved_rules`), and a scan leaves the queue only when *every* rule that
    asked for a human has an answer. Partly-resolved scans stay, with the
    settled rules dropped from `rules`, because the remaining ones are still
    owed and a queue that hid them would lose the work silently.

    Passing `None` is the pre-resolution behaviour and is what the offline and
    listing paths get. It is a separate argument rather than a field on
    `ScanFacts` because a resolution is not a fact about the scan — the scan is
    immutable and its verdicts still say REVIEW — it is a fact about what
    somebody did afterwards.
    """
    settled = resolved or {}
    pending: list[tuple[ScanFacts, list[str]]] = []
    for scan in scans:
        if not scan.needs_review:
            continue
        done = settled.get(scan.id, frozenset())
        outstanding = [v.rule_id for v in scan.verdicts if v.needs_human() and v.rule_id not in done]
        if outstanding:
            pending.append((scan, outstanding))
    pending.sort(key=lambda pair: pair[0].captured_at)
    return [
        {
            "scan_id": str(s.id),
            "captured_at": s.captured_at.isoformat(),
            "brand": s.brand,
            "variant": s.variant,
            "pack_size": s.pack_size,
            "district": s.district,
            "category": s.category,
            "coverage": s.coverage,
            "degradation_tier": s.degradation_tier,
            "rules": rules,
        }
        for s, rules in pending[:limit]
    ]


def health(scans: Sequence[ScanFacts]) -> dict[str, Any]:
    """Q8 — is the tool itself working?

    Section 11: *"It shows the department the tool is working, not just that
    products are failing — and it's where you'd notice OCR quietly degrading
    after a model update."*

    Latency is split by cache hit and miss because section 4 budgets them
    separately (about 60 ms against 561 ms), and a single blended median moves
    with the cache rate rather than with performance — it would hide a genuine
    regression behind a good morning's caching.
    """
    hits = [s.latency_ms for s in scans if s.cache_hit and s.latency_ms is not None]
    misses = [s.latency_ms for s in scans if not s.cache_hit and s.latency_ms is not None]
    coverages = [s.coverage for s in scans if s.coverage is not None]
    tiers: dict[str, int] = defaultdict(int)
    for scan in scans:
        tiers[scan.degradation_tier] += 1

    return {
        "scans": len(scans),
        "median_latency_ms_cache_hit": round(statistics.median(hits)) if hits else None,
        "median_latency_ms_cache_miss": round(statistics.median(misses)) if misses else None,
        "p95_latency_ms_cache_miss": (
            round(sorted(misses)[max(0, int(len(misses) * 0.95) - 1)]) if misses else None
        ),
        "cache_hit_rate": round(sum(1 for s in scans if s.cache_hit) / len(scans), 4)
        if scans
        else None,
        "mean_coverage": round(statistics.fmean(coverages), 4) if coverages else None,
        "awaiting_sync": sum(1 for s in scans if not s.synced),
        "degradation_tiers": dict(sorted(tiers.items())),
    }


def summary(scans: Sequence[ScanFacts], *, filters: ScanFilters | None = None) -> dict[str, Any]:
    """The printable form of the dashboard. Section 13a.

    *"The summary is a straight aggregation over scan records, so it's cheap
    once the repository exists — and it's what makes the dashboard exportable
    rather than merely decorative. The dashboard is the live view; the summary
    is its printable form."*
    """
    conclusive = sum(1 for s in scans if s.is_conclusive)
    non_compliant = sum(1 for s in scans if s.is_non_compliant)
    coverages = [s.coverage for s in scans if s.coverage is not None]

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "filters": {
            key: (value.isoformat() if isinstance(value, date) else value)
            for key, value in (asdict(filters) if filters else {}).items()
            if value is not None
        },
        "scans": len(scans),
        "conclusive": conclusive,
        "inconclusive": len(scans) - conclusive,
        "non_compliant": non_compliant,
        "non_compliance_rate": _rate(non_compliant, conclusive),
        "unique_skus": len({s.sku_id for s in scans if s.sku_id}),
        "high_severity": sum(s.high_severity_failures for s in scans),
        "awaiting_review": sum(1 for s in scans if s.needs_review),
        "mean_coverage": round(statistics.fmean(coverages), 4) if coverages else None,
        "top_violations": by_rule(scans)[:TOP_RULES],
        "repeat_offenders": by_brand(scans)[:10],
        "categories": by_category(scans),
        "districts": by_district(scans),
    }


__all__ = [
    "SEVERITY_RANK",
    "TOP_RULES",
    "UNCLASSIFIED",
    "ScanFacts",
    "ScanFilters",
    "VerdictFact",
    "brand_detail",
    "by_brand",
    "by_category",
    "by_district",
    "by_rule",
    "health",
    "overview",
    "review_queue",
    "summary",
    "weekly_trend",
]
