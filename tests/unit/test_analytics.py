"""Dashboard aggregation — AKSHAR.md section 11.

These tests are mostly about *not counting things*. A dashboard's failure mode
is not a crash; it is a plausible number that is wrong, read aloud in a meeting
and acted on. So the bulk of what follows pins down the three exclusions —
advisory verdicts, suppressed verdicts, and NO_DATA — plus the sort order of the
brands table, which section 11 argues about at length for a reason.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from api.analytics import (
    ScanFacts,
    ScanFilters,
    VerdictFact,
    brand_detail,
    by_brand,
    by_category,
    by_district,
    by_rule,
    health,
    overview,
    review_queue,
    summary,
    weekly_trend,
)

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def verdict(
    rule_id="LMPC.MRP.PRESENT",
    status="PASS",
    severity="high",
    *,
    advisory=False,
    suppressed_by=None,
) -> VerdictFact:
    return VerdictFact(
        rule_id=rule_id,
        rule_ref="Rule 6(1)(e)",
        status=status,
        severity=severity,
        advisory=advisory,
        suppressed_by=suppressed_by,
    )


def scan(
    *verdicts: VerdictFact,
    brand="Parle",
    brand_group="Parle Products",
    category="biscuits",
    district="Khordha",
    when=NOW,
    sku_id=None,
    officer_id=None,
    coverage=0.9,
    latency_ms=561,
    cache_hit=False,
    tier="L0",
    synced=True,
) -> ScanFacts:
    return ScanFacts(
        id=uuid4(),
        captured_at=when,
        district=district,
        category=category,
        brand=brand,
        brand_group=brand_group,
        officer_id=officer_id or uuid4(),
        sku_id=sku_id or uuid4(),
        coverage=coverage,
        latency_ms=latency_ms,
        cache_hit=cache_hit,
        degradation_tier=tier,
        source="photo",
        synced=synced,
        verdicts=verdicts,
    )


# ---------------------------------------------------------------------------
# The three exclusions
# ---------------------------------------------------------------------------


def test_an_advisory_failure_is_not_non_compliance():
    """Section 13 keeps the five unit-symbol checks in a separate block.

    If `250 ML` counted as a violation, the most-broken-rule chart would tell a
    department to publish an advisory about capitalisation while a missing MRP
    sat below it.
    """
    only_advisory = scan(verdict("LMPC.UNIT.ML", "FAIL", "low", advisory=True))
    assert not only_advisory.is_non_compliant
    assert only_advisory.high_severity_failures == 0
    assert by_rule([only_advisory]) == []


def test_a_suppressed_verdict_is_not_counted_twice():
    """One measurement yields one verdict.

    Both rules measured the same numeral height; the second lost. Counting both
    would double every rate on the page.
    """
    both = scan(
        verdict("LMPC.MRP.HEIGHT", "FAIL"),
        verdict("LMPC.MRP.HEIGHT_GENERIC", "FAIL", suppressed_by="LMPC.MRP.HEIGHT"),
    )
    assert len(both.failures) == 1
    assert both.high_severity_failures == 1
    assert [row["rule_id"] for row in by_rule([both])] == ["LMPC.MRP.HEIGHT"]


def test_a_scan_that_learned_nothing_is_not_counted_as_compliant():
    """NO_DATA is not a pass, and must not flatter the numbers.

    A tier-C photograph with no scale reference NO_DATAs every height rule. If
    that counted as compliant, worse photography would improve the district's
    figures — the exact incentive an enforcement tool must never create.
    """
    blind = scan(verdict("LMPC.MRP.HEIGHT", "NO_DATA"))
    assert not blind.is_conclusive
    assert not blind.is_non_compliant

    result = overview([blind])
    assert result["tiles"]["scans"]["value"] == 1
    assert result["tiles"]["non_compliance_rate"]["value"] is None


def test_the_rate_divides_by_conclusive_scans_only():
    good = scan(verdict("LMPC.MRP.PRESENT", "PASS"))
    bad = scan(verdict("LMPC.MRP.PRESENT", "FAIL"))
    blind = scan(verdict("LMPC.MRP.HEIGHT", "NO_DATA"))

    result = overview([good, bad, blind])
    # One failure out of two conclusive scans, not out of three.
    assert result["tiles"]["non_compliance_rate"]["value"] == 0.5


# ---------------------------------------------------------------------------
# Brands — Q3
# ---------------------------------------------------------------------------


def test_the_brands_table_sorts_by_high_severity_not_fail_rate():
    """Section 11's explicit instruction, and the reason it gives.

    "A small brand with two SKUs and a 100% fail rate is noise; a national brand
    at 30% across forty SKUs is a case worth opening."
    """
    tiny = [scan(verdict("LMPC.MRP.PRESENT", "FAIL"), brand="Corner Shop") for _ in range(2)]
    national = [
        scan(verdict("LMPC.MRP.PRESENT", "FAIL"), brand="National")
        if index < 12
        else scan(verdict("LMPC.MRP.PRESENT", "PASS"), brand="National")
        for index in range(40)
    ]

    rows = by_brand(tiny + national)
    assert rows[0]["brand"] == "National"
    assert rows[0]["high_severity"] == 12
    # ...even though the small brand has the worse rate.
    assert rows[1]["fail_rate"] == 1.0
    assert rows[0]["fail_rate"] == 0.3


def test_the_parent_column_carries_the_entity_a_notice_is_addressed_to():
    rows = by_brand([scan(verdict(), brand="Lay's", brand_group="PepsiCo")])
    assert rows[0]["parent"] == "PepsiCo"


def test_brand_detail_returns_an_ordered_timeline():
    """Q7 — the before-and-after view only works if it is in order."""
    days = [NOW - timedelta(days=offset) for offset in (5, 1, 3)]
    scans = [scan(verdict("LMPC.MRP.PRESENT", "FAIL"), when=day) for day in days]

    detail = brand_detail(scans, "Parle")
    stamps = [row["captured_at"] for row in detail["timeline"]]
    assert stamps == sorted(stamps)
    assert detail["scans"] == 3


# ---------------------------------------------------------------------------
# Rules — Q2, and the self-audit
# ---------------------------------------------------------------------------


def test_a_rule_that_almost_always_fails_is_flagged_as_suspect():
    """Section 11: "more likely a bug in our regex than a national conspiracy"."""
    scans = [scan(verdict("LMPC.SUSPECT", "FAIL")) for _ in range(25)]
    row = next(r for r in by_rule(scans) if r["rule_id"] == "LMPC.SUSPECT")
    assert row["fail_rate"] == 1.0
    assert row["suspect"] is True


def test_a_rule_failing_often_in_a_tiny_sample_is_not_flagged():
    """Three scans is not evidence of a broken regex."""
    scans = [scan(verdict("LMPC.RARE", "FAIL")) for _ in range(3)]
    row = next(r for r in by_rule(scans) if r["rule_id"] == "LMPC.RARE")
    assert row["fail_rate"] == 1.0
    assert row["suspect"] is False


def test_the_rules_view_reports_checked_alongside_failed():
    scans = [scan(verdict("LMPC.MRP.PRESENT", "PASS")) for _ in range(8)]
    scans += [scan(verdict("LMPC.MRP.PRESENT", "FAIL")) for _ in range(2)]
    row = by_rule(scans)[0]
    assert (row["checked"], row["failed"], row["fail_rate"]) == (10, 2, 0.2)


def test_the_rules_view_names_the_brands_failing_a_rule_most():
    scans = [scan(verdict("LMPC.MRP.HEIGHT", "FAIL"), brand="Parle") for _ in range(3)]
    scans += [scan(verdict("LMPC.MRP.HEIGHT", "FAIL"), brand="Britannia")]
    row = by_rule(scans)[0]
    assert row["top_brands"][0] == {"brand": "Parle", "failures": 3}


# ---------------------------------------------------------------------------
# Districts — Q5, the dark-district question
# ---------------------------------------------------------------------------


def test_a_district_with_no_conclusive_scans_reports_an_unknown_rate_not_zero():
    """The whole point of the districts view is to find dark districts.

    Reporting 0% non-compliance for a district nobody has scanned says the
    opposite of the truth, and is the number a controller would act on.
    """
    rows = by_district([scan(verdict("LMPC.MRP.HEIGHT", "NO_DATA"), district="Malkangiri")])
    assert rows[0]["fail_rate"] is None


def test_coverage_is_none_without_a_population_estimate():
    """A percentage over an unknown denominator is a guess wearing a % sign."""
    rows = by_district([scan(verdict())])
    assert rows[0]["coverage"] is None
    assert rows[0]["sku_population_estimate"] is None


def test_coverage_is_computed_when_a_population_is_supplied():
    sku = uuid4()
    rows = by_district(
        [scan(verdict(), district="Khordha", sku_id=sku)],
        sku_population={"Khordha": 400},
    )
    assert rows[0]["coverage"] == 0.0025


# ---------------------------------------------------------------------------
# Review queue — Q6
# ---------------------------------------------------------------------------


def test_the_review_queue_is_oldest_first():
    """A review item that has waited three weeks outranks this morning's."""
    old = scan(verdict("LMPC.MRP.HEIGHT", "REVIEW"), when=NOW - timedelta(days=21))
    new = scan(verdict("LMPC.MRP.HEIGHT", "REVIEW"), when=NOW)
    rows = review_queue([new, old])
    assert rows[0]["scan_id"] == str(old.id)


def test_an_advisory_review_does_not_enter_the_queue():
    quiet = scan(verdict("LMPC.UNIT.ML", "REVIEW", "low", advisory=True))
    assert review_queue([quiet]) == []


# ---------------------------------------------------------------------------
# Health — Q8
# ---------------------------------------------------------------------------


def test_latency_is_reported_separately_for_cache_hits_and_misses():
    """A blended median moves with the cache rate, not with performance.

    Section 4 budgets roughly 60 ms against 561 ms; averaging them would hide a
    real regression behind a morning of good caching.
    """
    hits = [scan(verdict(), latency_ms=60, cache_hit=True) for _ in range(5)]
    misses = [scan(verdict(), latency_ms=560, cache_hit=False) for _ in range(5)]

    report = health(hits + misses)
    assert report["median_latency_ms_cache_hit"] == 60
    assert report["median_latency_ms_cache_miss"] == 560
    assert report["cache_hit_rate"] == 0.5


def test_health_counts_scans_awaiting_sync():
    report = health([scan(verdict(), synced=False), scan(verdict(), synced=True)])
    assert report["awaiting_sync"] == 1


def test_health_is_empty_rather_than_zero_with_no_scans():
    report = health([])
    assert report["scans"] == 0
    assert report["cache_hit_rate"] is None
    assert report["median_latency_ms_cache_miss"] is None


# ---------------------------------------------------------------------------
# Trend — Q1
# ---------------------------------------------------------------------------


def test_a_week_with_no_scans_is_a_gap_not_a_smoothed_line():
    """A quiet fortnight must not look like a trend that never happened."""
    scans = [scan(verdict("LMPC.MRP.PRESENT", "FAIL"), when=NOW - timedelta(weeks=4))]
    scans += [scan(verdict("LMPC.MRP.PRESENT", "PASS"), when=NOW)]

    points = weekly_trend(scans, weeks=6)
    assert len(points) == 6
    empty = [p for p in points if p["scans"] == 0]
    assert empty
    assert all(p["non_compliance_rate"] is None for p in empty)


def test_the_trend_is_chronological():
    points = weekly_trend([scan(verdict())], weeks=4)
    assert [p["week"] for p in points] == sorted(p["week"] for p in points)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def test_the_severity_filter_matches_on_failures_not_on_passes():
    """Filtering to high severity must not return a pack that PASSED a high rule."""
    passed_high = scan(verdict("LMPC.MRP.PRESENT", "PASS", "high"))
    failed_low = scan(verdict("LMPC.UNIT.G", "FAIL", "low"))
    failed_high = scan(verdict("LMPC.MRP.PRESENT", "FAIL", "high"))

    high = ScanFilters(severity="high")
    assert not high.matches(passed_high)
    assert not high.matches(failed_low)
    assert high.matches(failed_high)


def test_the_status_filter_treats_no_data_as_neither_pass_nor_fail():
    blind = scan(verdict("LMPC.MRP.HEIGHT", "NO_DATA"))
    assert not ScanFilters(status="PASS").matches(blind)
    assert not ScanFilters(status="FAIL").matches(blind)


def test_the_previous_period_is_the_same_span_immediately_before():
    from datetime import date

    window = ScanFilters(date_from=date(2026, 9, 1), date_to=date(2026, 9, 7))
    prior = window.previous_period()
    assert prior is not None
    assert (prior.date_from, prior.date_to) == (date(2026, 8, 25), date(2026, 8, 31))


def test_an_unbounded_window_has_no_previous_period():
    assert ScanFilters().previous_period() is None


def test_a_global_filter_carries_into_the_previous_period():
    """Otherwise the comparison silently changes what it is comparing."""
    from datetime import date

    window = ScanFilters(
        date_from=date(2026, 9, 1), date_to=date(2026, 9, 7), district="Khordha"
    )
    assert window.previous_period().district == "Khordha"


# ---------------------------------------------------------------------------
# Summary — section 13a
# ---------------------------------------------------------------------------


def test_the_summary_separates_inconclusive_scans_from_compliant_ones():
    scans = [
        scan(verdict("LMPC.MRP.PRESENT", "PASS")),
        scan(verdict("LMPC.MRP.PRESENT", "FAIL")),
        scan(verdict("LMPC.MRP.HEIGHT", "NO_DATA")),
    ]
    report = summary(scans)
    assert report["scans"] == 3
    assert report["conclusive"] == 2
    assert report["inconclusive"] == 1
    assert report["non_compliant"] == 1
    assert report["non_compliance_rate"] == 0.5


def test_the_summary_records_the_filters_it_was_produced_under():
    """A summary without its window is a number nobody can reproduce."""
    from datetime import date

    filters = ScanFilters(date_from=date(2026, 9, 1), district="Khordha")
    report = summary([scan(verdict())], filters=filters)
    assert report["filters"] == {"date_from": "2026-09-01", "district": "Khordha"}


@pytest.mark.parametrize(
    "function", [by_brand, by_category, by_district, by_rule, review_queue, weekly_trend]
)
def test_every_view_survives_an_empty_corpus(function):
    """Day one of a deployment has no scans, and must not be a 500."""
    assert function([]) == []


def test_the_categories_view_covers_more_than_food():
    """Section 11: the chart is the proof we implemented LMPC, not FSSAI."""
    scans = [
        scan(verdict("LMPC.MRP.PRESENT", "FAIL"), category="cement"),
        scan(verdict("LMPC.MRP.PRESENT", "PASS"), category="electronics"),
        scan(verdict("LMPC.MRP.PRESENT", "PASS"), category="biscuits"),
    ]
    names = {row["category"] for row in by_category(scans)}
    assert names == {"cement", "electronics", "biscuits"}
