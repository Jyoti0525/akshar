"""The violation summary, printed — AKSHAR.md sections 13a and 11.

    "The dashboard is the live view; the summary is its printable form."

This is the document that gets tabled at a meeting, where nobody has the
dashboard open to contradict it. So the tests here are mostly about the two ways
a printed aggregate lies:

- **a rate that does not exist printed as zero.** `_rate()` returns None when
  nothing conclusive was scanned, and section 11 built the districts view around
  that exact distinction — *"that last column identifies districts that are dark
  rather than compliant."* Rendering None as `0%` reports perfect compliance in
  the districts nobody has visited.
- **a second computation.** Every figure must come out of `api.analytics`, so
  the page and the screen cannot disagree. A summary that recounted anything
  would be a fourth implementation of "non-compliance rate".
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from api.analytics import ScanFacts, ScanFilters, VerdictFact, summary
from reports import render, summary_model

CAPTURED = datetime(2026, 9, 8, 11, 30, tzinfo=UTC)


def _verdict(status="FAIL", **overrides):
    payload = {
        "rule_id": "LMPC.MRP.NUMERAL_HEIGHT",
        "rule_ref": "Rule 7(2), Table I",
        "status": status,
        "severity": "high",
    }
    payload.update(overrides)
    return VerdictFact(**payload)


def _scan(*, district="Khordha", brand="Parle", verdicts=(), **overrides):
    payload = {
        "id": uuid4(),
        "captured_at": CAPTURED,
        "district": district,
        "category": "biscuits",
        "brand": brand,
        "brand_group": None,
        "officer_id": uuid4(),
        "sku_id": uuid4(),
        "coverage": 0.82,
        "latency_ms": 480,
        "cache_hit": False,
        "degradation_tier": "L1",
        "source": "photo",
        "synced": True,
        "verdicts": tuple(verdicts),
    }
    payload.update(overrides)
    return ScanFacts(**payload)


def _built(scans, filters=None):
    return summary_model.build(summary(scans, filters=filters))


# ---------------------------------------------------------------------------
# The rate that does not exist
# ---------------------------------------------------------------------------


def test_an_unknown_rate_prints_as_a_dash_not_as_zero():
    assert summary_model.percent(None) == summary_model.DASH
    assert summary_model.percent(0.0) == "0.0%"


def test_a_district_with_no_conclusive_scan_is_named_as_unmeasured():
    """Section 11: dark, not compliant.

    Every scan here reached NO_DATA — a shelf photographed at tier C, where no
    height could be measured. The district must not appear at 0%.
    """
    dark = _scan(district="Kandhamal", verdicts=[_verdict("NO_DATA")])

    report = _built([dark])
    districts = next(t for t in report.tables if t.title == "Districts")
    row = next(r for r in districts.rows if r.label == "Kandhamal")

    assert summary_model.DASH in row.cells
    assert "unmeasured, not compliant" in row.note


def test_a_period_that_concluded_nothing_reports_no_rate_at_all():
    """A week of unreadable photographs is not a clean bill of health."""
    report = _built([_scan(verdicts=[_verdict("NO_DATA")])])

    assert report.non_compliance_rate == summary_model.DASH
    assert "none produced a conclusive check" in report.headline
    assert "no non-compliance rate is reported" in report.headline


def test_inconclusive_scans_are_named_and_kept_out_of_the_rate():
    scans = [
        _scan(verdicts=[_verdict("FAIL")]),
        _scan(verdicts=[_verdict("PASS")]),
        _scan(verdicts=[_verdict("NO_DATA")]),
    ]

    report = _built(scans)

    assert report.scans == 3
    assert report.conclusive == 2
    assert report.inconclusive == 1
    assert report.non_compliance_rate == "50.0%"
    assert "excluded from the rate" in report.coverage_note


# ---------------------------------------------------------------------------
# The three counting rules, in print
# ---------------------------------------------------------------------------


def test_an_advisory_finding_is_not_counted_as_a_violation():
    """A `250 ML` must not appear in the summary's headline figure."""
    advisory_only = _scan(
        verdicts=[_verdict("FAIL", rule_id="LMPC.UNIT.SYMBOL_CASE", advisory=True)]
    )

    report = _built([advisory_only])

    assert report.non_compliant == 0
    assert not next(
        t for t in report.tables if t.title == "Provisions most often contravened"
    ).rows


def test_a_suppressed_verdict_does_not_double_the_count():
    scan = _scan(
        verdicts=[
            _verdict("FAIL"),
            _verdict(
                "FAIL",
                rule_id="LMPC.LETTER.MIN_HEIGHT",
                suppressed_by="LMPC.MRP.NUMERAL_HEIGHT",
            ),
        ]
    )

    report = _built([scan])
    violations = next(
        t for t in report.tables if t.title == "Provisions most often contravened"
    )

    assert report.non_compliant == 1
    assert len(violations.rows) == 1


def test_the_document_states_how_it_counted():
    """A reader comparing this page against a raw row count will otherwise
    conclude the report is wrong."""
    report = _built([_scan(verdicts=[_verdict()])])
    html = render.to_html(report, template="summary.html")

    assert len(report.counting_rules) == 3
    for title, _explanation in report.counting_rules:
        assert title in html


# ---------------------------------------------------------------------------
# One computation, three layouts
# ---------------------------------------------------------------------------


def test_every_figure_comes_from_the_analytics_payload():
    """Nothing is recounted here. Change the payload, change the document.

    If this ever fails because the summary computed its own total, that is the
    bug this test exists for — the fourth implementation of a rate that three
    other surfaces already report.
    """
    payload = summary([_scan(verdicts=[_verdict()])])
    payload["scans"] = 999
    payload["non_compliance_rate"] = 0.5

    report = summary_model.build(payload)

    assert report.scans == 999
    assert report.non_compliance_rate == "50.0%"


def test_the_docx_and_the_html_carry_the_same_headline():
    pytest.importorskip("docx")
    from reports.docx_writer import summary_to_docx

    report = _built([_scan(verdicts=[_verdict()]), _scan(verdicts=[_verdict("PASS")])])

    html = render.to_html(report, template="summary.html")
    with zipfile.ZipFile(io.BytesIO(summary_to_docx(report))) as archive:
        docx_text = archive.read("word/document.xml").decode("utf-8")

    assert report.headline in html
    assert report.headline in docx_text


def test_the_docx_carries_every_table_the_html_does():
    pytest.importorskip("docx")
    from reports.docx_writer import summary_to_docx

    report = _built([_scan(verdicts=[_verdict()])])

    with zipfile.ZipFile(io.BytesIO(summary_to_docx(report))) as archive:
        docx_text = archive.read("word/document.xml").decode("utf-8")

    for table in report.tables:
        assert table.title in docx_text


def test_the_brand_ordering_argument_is_printed_not_just_applied():
    """Section 11 sorts brands by high-severity count rather than failure rate.

    A reader who re-sorts the printed table by rate reaches the opposite
    conclusion, so the reason travels with the table.
    """
    report = _built([_scan(verdicts=[_verdict()])])
    brands = next(t for t in report.tables if t.title.startswith("Brands"))

    assert "not by failure rate" in brands.footnote


def test_a_rule_failing_on_everything_is_flagged_in_the_printed_copy():
    """*"A rule failing on 95% of products is more likely a bug in our regex
    than a national conspiracy."* This is the copy somebody quotes."""
    scans = [_scan(verdicts=[_verdict()]) for _ in range(25)]

    report = _built(scans)
    violations = next(
        t for t in report.tables if t.title == "Provisions most often contravened"
    )

    assert any("verify the rule before citing" in row.note for row in violations.rows)


# ---------------------------------------------------------------------------
# Scope — what this document is *of*
# ---------------------------------------------------------------------------


def test_the_scope_and_period_are_named_on_the_page():
    """A summary detached from its scope is the document that gets forwarded as
    though it covered the whole state."""
    filters = ScanFilters(
        date_from=date(2026, 9, 1), date_to=date(2026, 9, 7), district="Khordha"
    )
    report = _built([_scan(verdicts=[_verdict()])], filters)
    html = render.to_html(report, template="summary.html")

    assert "Khordha district" in report.scope
    assert report.period == "01 September 2026 to 07 September 2026"
    assert report.scope in html
    assert report.period in html


def test_an_unfiltered_summary_says_it_covers_everything():
    report = _built([_scan(verdicts=[_verdict()])])

    assert report.period == "All records held"
    assert report.scope == "All districts and categories"


def test_the_summary_never_claims_a_package_was_weighed():
    """Same disclaimer Form A's Parts B, C and D carry in the per-product
    report. An aggregate of declaration checks is not an aggregate of weight
    checks."""
    report = _built([_scan(verdicts=[_verdict()])])
    html = render.to_html(report, template="summary.html")

    assert "No package was opened, weighed or measured" in html


def test_ocr_text_cannot_break_out_of_the_summary():
    """Brand names reach this document from OCR of a photograph."""
    scan = _scan(brand="<script>alert(1)</script>", verdicts=[_verdict()])

    html = render.to_html(_built([scan]), template="summary.html")

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_an_empty_period_produces_a_document_rather_than_an_error():
    """A district that recorded nothing this week still gets a summary saying
    so — which is itself the finding section 11's districts view exists for."""
    report = _built([])
    html = render.to_html(report, template="summary.html")

    assert report.scans == 0
    assert report.non_compliance_rate == summary_model.DASH
    assert "Violation summary" in html

# The routes that serve this document live in `test_dashboard_api.py`, beside
# the fixtures that build a populated store and the role table they have to
# honour. Splitting them across two files would mean a second set of stubs and
# a second chance for the two to drift.


def test_the_summary_pdf_is_always_a_pdf():
    """The dashboard's export link has the same shape as the per-scan one, and
    had the same bug: on a host without WeasyPrint's native libraries it
    answered 503 with a JSON body, which the browser saved as
    `violation-summary.pdf` and no viewer would open.

    `reports.render.to_pdf` now falls back to `reports.pdf_fallback`, which is
    pure Python. A plainer summary is a worse document; a file that will not
    open is not a document.
    """
    payload = render.to_pdf(_built([_scan()]), template="summary.html")
    assert payload[:5] == b"%PDF-", "the export route must never hand a browser a non-PDF"
    assert payload[-6:].strip().endswith(b"%%EOF"), "truncated PDFs open as corrupt"
    assert len(payload) > 1000
