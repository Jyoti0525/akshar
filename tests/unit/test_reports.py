"""Reports — AKSHAR.md sections 13, 13b, 13c, M8.

The report is the artefact a department actually files, so most of these tests
are about what it must **not** say:

- an advisory `250 ML` must never appear beside a missing MRP as a contravention
- a suppressed verdict must not print the same finding twice under two citations
- a clean-looking scan that read half the label must not be called compliant
- Parts B, C and D of Form A must be named and marked inapplicable, not omitted

The PDF is tested where it can render and skipped honestly where it cannot,
which on a plain Windows or macOS machine is always — WeasyPrint needs Pango and
cairo. The DOCX and HTML paths have no native dependencies and are always tested,
which is the point of the problem statement naming the editable format.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from reports import assemble, docx_writer, model, render
from rules.loader import load_rulepack

CAPTURED = datetime(2026, 9, 8, 11, 30, tzinfo=UTC)


def _scan(**overrides):
    return {
        "id": uuid4(),
        "captured_at": CAPTURED,
        "district": "Khordha",
        "category": "biscuits",
        "rulepack_version": "lmpc_2011@1.3.0",
        "degradation_tier": "L1",
        "coverage": 0.82,
        "model_versions": {"detector": "sha256:abc", "rulepack": "1.3.0"},
        "image_key": "2026/09/08/x.jpg",
        "image_sha256": "a" * 64,
        "record_sha256": "b" * 64,
        "chain_seq": 41,
        "declaration_set": {
            "declarations": [
                {"field": "manufacturer", "text": "Acme Foods Pvt Ltd, Bhubaneswar"},
                {"field": "net_quantity", "text": "100 g"},
                {"field": "mrp", "text": "MRP Rs. 10.00"},
            ]
        },
        **overrides,
    }


HEIGHT_FAIL = {
    "rule_id": "LMPC.MRP.NUMERAL_HEIGHT",
    "rule_ref": "Rule 7(2), Table I",
    "status": "FAIL",
    "severity": "high",
    "message": "MRP numerals are below the prescribed height.",
    "measured": 0.82,
    "threshold": 1.0,
    "tolerance": 0.09,
    "expected": ">= 1 mm",
    "advisory": False,
}
SYMBOL_ADVISORY = {
    "rule_id": "LMPC.UNIT.SYMBOL_CASE",
    "rule_ref": "NSR 2011, Third Schedule 7(2)",
    "status": "FAIL",
    "severity": "low",
    "message": "Unit symbol printed in upper case.",
    "found": "250 ML",
    "advisory": True,
}
SUPPRESSED = {
    "rule_id": "LMPC.LETTER.MIN_HEIGHT",
    "rule_ref": "Rule 7(3)",
    "status": "FAIL",
    "severity": "high",
    "message": "This must not be printed.",
    "suppressed_by": "LMPC.MRP.NUMERAL_HEIGHT",
}
NO_DATA = {
    "rule_id": "LMPC.NETQTY.EXCLUSION",
    "rule_ref": "Rule 8(1) proviso",
    "status": "NO_DATA",
    "severity": "medium",
    "message": "No scale was recovered (tier C); the exclusion zone was not measured.",
}
DEALER_FAIL = {
    "rule_id": "LMPC.MRP.DEFACED",
    "rule_ref": "Rule 18(5)",
    "status": "FAIL",
    "severity": "medium",
    "message": "A sticker obscures the printed retail sale price.",
    "respondent": "dealer",
}

# Real rule ids and the real pack's check types. Inventing ids here would let
# the remediation lookup pass on fixtures and fall through to the generic
# sentence in production, which is precisely what the first draft of this file
# did.
CHECKS = assemble.check_types(load_rulepack())


def _report(verdicts, **kwargs):
    return model.build(
        scan=_scan(),
        verdicts=verdicts,
        package=model.Package(brand="Parle", variant="G", pack_size="100 g"),
        officer_name="R Mohanty",
        checks=CHECKS,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# What the report must not conflate
# ---------------------------------------------------------------------------


def test_an_advisory_symbol_check_never_appears_among_the_contraventions():
    """Section 13: *a tool that reports `250 ML` at the same severity as a
    missing MRP is a tool an officer stops trusting.*"""
    report = _report([HEIGHT_FAIL, SYMBOL_ADVISORY])

    assert [f.rule_id for f in report.violations] == ["LMPC.MRP.NUMERAL_HEIGHT"]
    assert [f.rule_id for f in report.advisory] == ["LMPC.UNIT.SYMBOL_CASE"]
    assert report.headline.startswith("1 apparent contravention")


def test_a_suppressed_verdict_is_printed_nowhere():
    """One measurement, one verdict. Printing both would read as two offences."""
    report = _report([HEIGHT_FAIL, SUPPRESSED])

    everywhere = [
        f.rule_id
        for group in (
            report.violations,
            report.advisory,
            report.not_checked,
            report.passed,
            report.not_applicable,
        )
        for f in group
    ]
    assert "LMPC.LETTER.MIN_HEIGHT" not in everywhere


def test_a_scan_that_could_not_check_everything_does_not_claim_compliance():
    """Absence of findings is not a finding of compliance."""
    report = _report([NO_DATA])

    assert not report.violations
    assert "could not be carried out" in report.headline
    assert [f.rule_id for f in report.not_checked] == ["LMPC.NETQTY.EXCLUSION"]


def test_a_clean_scan_says_so_plainly():
    report = _report([{**HEIGHT_FAIL, "status": "PASS"}])
    assert report.headline == "No contravention was found in the declarations checked."


def test_a_review_is_not_asserted_as_a_contravention():
    """A measurement inside our own error must not read as a conviction."""
    report = _report([{**HEIGHT_FAIL, "status": "REVIEW"}])

    assert report.failures == ()
    assert len(report.reviews) == 1
    assert "No contravention is asserted" in report.headline


def test_a_dealers_offence_is_addressed_to_the_dealer():
    """Rule 18(5) is the retailer's offence; the notice goes to a different party."""
    report = _report([HEIGHT_FAIL, DEALER_FAIL])

    assert report.respondents == ("dealer", "manufacturer")
    dealer = next(f for f in report.violations if f.rule_id == "LMPC.MRP.DEFACED")
    assert dealer.respondent_label == "Dealer / retailer"


def test_findings_are_ordered_worst_first():
    report = _report(
        [
            {**DEALER_FAIL, "severity": "medium"},
            HEIGHT_FAIL,
            {**HEIGHT_FAIL, "rule_id": "X", "status": "REVIEW"},
        ]
    )
    assert [f.status for f in report.violations] == ["FAIL", "FAIL", "REVIEW"]
    assert report.violations[0].severity == "high"


def test_a_measurement_is_printed_with_the_error_bar_that_decided_it():
    """The tolerance chose FAIL over REVIEW; hiding it hides the reasoning."""
    report = _report([HEIGHT_FAIL])
    assert report.violations[0].measurement == "0.82 ± 0.09 mm, required ≥ 1 mm"


def test_every_check_type_has_a_remediation_line():
    """Thirteen check types, thirteen remedies — and the engine has no fourteenth."""
    from rules.models import ALLOWED_CHECKS

    missing = set(ALLOWED_CHECKS) - set(model._REMEDIATION_BY_CHECK)
    assert not missing, f"no remediation sentence for {sorted(missing)}"


# ---------------------------------------------------------------------------
# Form A
# ---------------------------------------------------------------------------


def test_the_weight_checking_parts_are_named_and_marked_inapplicable():
    """Section 13b: *it makes the omission of weight checking explicit rather
    than hidden.* Leaving B, C and D out would imply they were done."""
    html = render.to_html(_report([HEIGHT_FAIL]))

    for part in ("Part B", "Part C", "Part D"):
        assert part in html
    assert "No package was opened, weighed or measured" in html
    for part in ("Part A", "Part E", "Part F"):
        assert part in html


def test_the_html_keeps_the_advisory_block_below_and_apart_from_part_e():
    html = render.to_html(_report([HEIGHT_FAIL, SYMBOL_ADVISORY]))

    assert html.index("Part E") < html.index("Advisory")
    assert "no contravention of the Packaged Commodities\n    Rules is asserted" in html or (
        "no contravention of the Packaged Commodities" in html
    )


def test_ocr_text_cannot_break_out_of_the_document():
    """Every string here is OCR output from a photograph. Autoescaping is not
    a web-security nicety; it is what stops an ingredient list ending the page."""
    hostile = {**HEIGHT_FAIL, "message": "<script>alert(1)</script> & <b>bold"}
    html = render.to_html(_report([hostile]))

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# The three renderings
# ---------------------------------------------------------------------------


def test_the_docx_is_a_real_editable_document():
    """Not a picture of a report. The problem statement asks for editable."""
    payload = docx_writer.to_docx(_report([HEIGHT_FAIL, SYMBOL_ADVISORY, NO_DATA]))

    assert payload[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        assert "word/document.xml" in names
        text = archive.read("word/document.xml").decode("utf-8")

    assert "Part A" in text and "Part E" in text and "Part F" in text
    assert "Advisory" in text
    assert "could not be carried out" in text


def test_the_docx_and_the_html_agree_about_what_is_a_contravention():
    """One model, three renderings — the reason `reports/model.py` exists.

    If the advisory split were a filter inside the Jinja template, this is the
    test that would fail, because the DOCX writer would have had to remember it
    separately.
    """
    report = _report([HEIGHT_FAIL, SYMBOL_ADVISORY])
    html = render.to_html(report)
    with zipfile.ZipFile(io.BytesIO(docx_writer.to_docx(report))) as archive:
        docx_text = archive.read("word/document.xml").decode("utf-8")

    for text in (html, docx_text):
        assert "LMPC.MRP.NUMERAL_HEIGHT" in text
        assert "LMPC.UNIT.SYMBOL_CASE" in text
        assert text.index("LMPC.MRP.NUMERAL_HEIGHT") < text.index("LMPC.UNIT.SYMBOL_CASE")


def test_a_missing_pdf_renderer_is_reported_not_raised_as_an_import_error():
    """WeasyPrint raises OSError from cffi, not ImportError, when Pango is absent.

    The first version of `pdf_available` caught only `ImportError` and let that
    escape — which is exactly the failure the function exists to contain.
    """
    ok, reason = render.pdf_available()
    assert isinstance(ok, bool)
    if not ok:
        assert "Pango" in reason or "weasyprint" in reason
        assert "DOCX and HTML are unaffected" in reason
        # `allow_fallback=False` is the only way to still see the refusal, and
        # it exists so this assertion means something on a host with no GTK.
        with pytest.raises(render.RendererUnavailableError):
            render.to_pdf(_report([HEIGHT_FAIL]), allow_fallback=False)


def test_a_pdf_is_produced_even_where_weasyprint_cannot_run():
    """The report route hands this to a browser following a `download` link.

    A browser saves whatever comes back under the name on the link, whatever its
    status or content type. So on 2026-09-09 a host with no GTK runtime answered
    the PDF route with `202 {"status": "rendering"}` and the officer received
    thirty bytes of JSON called `scan-<id>.pdf`, which no viewer would open.

    `to_pdf` therefore always returns a PDF: WeasyPrint where its native
    libraries exist, `reports.pdf_fallback` where they do not. A plainer
    document is a worse report; a file that will not open is not a report.
    """
    payload = render.to_pdf(_report([HEIGHT_FAIL, SYMBOL_ADVISORY]))
    assert payload[:5] == b"%PDF-", "the route must never hand a browser a non-PDF"
    assert payload[-6:].strip().endswith(b"%%EOF"), "truncated PDFs open as corrupt"
    assert len(payload) > 1000


@pytest.mark.skipif(not render.pdf_available()[0], reason=render.pdf_available()[1])
def test_the_pdf_renders_where_the_native_libraries_exist():
    payload = render.to_pdf(_report([HEIGHT_FAIL, SYMBOL_ADVISORY]))
    assert payload[:5] == b"%PDF-"
    assert len(payload) > 1000


# ---------------------------------------------------------------------------
# Assembly from stored rows
# ---------------------------------------------------------------------------


def test_part_a_quotes_the_label_that_was_photographed():
    """Not the SKU row as it stands today.

    A manufacturer reprints, or a SKU row is corrected. The package in front of
    the officer is the one the report is about, and section 10 stores the
    declaration set so it stays recoverable.
    """
    class Sku:
        brand, variant, pack_size, category, barcode = "Parle", "G", "100 g", "biscuits", "890"

    report = assemble.from_scan(
        scan=_scan(), verdicts=[HEIGHT_FAIL], pack=load_rulepack(), sku=Sku(), officer_name="R M"
    )

    assert report.package.manufacturer == "Acme Foods Pvt Ltd, Bhubaneswar"
    assert report.package.net_quantity == "100 g"
    assert report.package.mrp == "MRP Rs. 10.00"
    assert report.package.title == "Parle G 100 g"


def test_an_unmatched_scan_still_produces_a_report():
    """A scan that matched no SKU is a real scan. Blank particulars are honest;
    an invented brand is not."""
    report = assemble.from_scan(
        scan=_scan(), verdicts=[HEIGHT_FAIL], pack=load_rulepack(), sku=None
    )

    assert report.package.title == "Unidentified package"
    assert report.package.category == "biscuits"  # from the scan, per D16
    assert render.to_html(report)


def test_the_remediation_comes_from_the_rulepacks_check_type():
    checks = assemble.check_types(load_rulepack())

    assert checks["LMPC.MFR.PRESENT"] == "present"
    report = model.build(scan=_scan(), verdicts=[HEIGHT_FAIL], checks=checks)
    assert report.violations[0].remediation == "Reprint at or above the required height."


def test_a_rule_no_longer_in_the_pack_still_renders():
    """An old case file must print, not raise, after a rulepack upgrade."""
    report = model.build(
        scan=_scan(),
        verdicts=[{**HEIGHT_FAIL, "rule_id": "LMPC.RETIRED.RULE"}],
        checks={},
    )
    assert report.violations[0].remediation == "Correct the declaration."
    assert render.to_html(report)
