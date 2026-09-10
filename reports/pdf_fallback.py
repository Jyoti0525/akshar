"""A PDF when WeasyPrint cannot run. AKSHAR.md §13, M8.

`reports/render.py` renders the HTML template to PDF with WeasyPrint, which is
the right renderer: one template feeds the HTML view and the PDF, so what an
officer reads on screen and what they file are the same document.

**WeasyPrint needs Pango, cairo and harfbuzz, and they are native.**
`docker/api.Dockerfile` installs them, so the deployed system uses WeasyPrint and
nothing here runs. A Windows or macOS machine without the GTK runtime cannot even
import it — `cannot load library 'gobject-2.0-0'` — and on that machine the PDF
route previously answered with a JSON error body which the browser then saved as
`akshar-<id>.pdf`. A file that will not open is worse than an honest refusal,
and on the morning of a demonstration it is worse than either.

So this module is the floor: pure Python, no native libraries, and it produces a
real PDF carrying the same content as the DOCX. It is deliberately plainer than
the template — this is the fallback, not a second design — and it says so on the
page, because a reader comparing two AKSHAR reports should be able to tell why
they do not look alike.

---------------------------------------------------------------------------
FONTS, AND THE ONE THING THIS CANNOT PROMISE
---------------------------------------------------------------------------
`fpdf2`'s built-in fonts are latin-1. A report on an Indian packet contains a
rupee sign at minimum and Devanagari routinely, and §13's whole bilingual claim
would be silently destroyed by a renderer that dropped it.

So a Unicode TrueType font is looked for, in order, and registered if found.
When none is available the text is transliterated to latin-1 **and the document
says so, in the document**, rather than printing boxes or dropping characters
quietly. A report that has lost the Hindi must admit it; that is the difference
between a degraded document and a wrong one.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

PAGE_W_MM = 210.0
MARGIN_MM = 14.0
BODY_W_MM = PAGE_W_MM - 2 * MARGIN_MM

FONT_CANDIDATES: tuple[tuple[str, str], ...] = (
    # Linux containers, and anywhere matplotlib is installed.
    ("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ("DejaVuSans", "/usr/share/fonts/TTF/DejaVuSans.ttf"),
    # Windows. Segoe UI carries the rupee sign; Nirmala carries Devanagari but
    # ships as a `.ttc` collection, which fpdf2 does not read.
    ("SegoeUI", "C:/Windows/Fonts/segoeui.ttf"),
    ("Arial", "C:/Windows/Fonts/arial.ttf"),
    # macOS.
    ("Helvetica", "/System/Library/Fonts/Supplemental/Arial.ttf"),
)
"""Where to look for a Unicode face, best first. Never bundled: a font file in
the repository is a licence question nobody asked, and the fallback is already
the degraded path."""

_TRANSLITERATE = {
    "\u2014": "-",
    "\u2013": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u00a0": " ",
    "\u20b9": "Rs.",
    "\u2265": ">=",
    "\u2264": "<=",
    "\u00b1": "+/-",
    "\u00d7": "x",
    "\u00b7": "-",
}
"""The characters this report actually contains, mapped to latin-1. `₹` becomes
`Rs.` rather than being dropped: the amount is the finding, and a price with no
currency in front of it is a different claim."""


class _Unicode:
    """Whether a real Unicode face was registered, and how to spell text if not."""

    def __init__(self, family: str | None) -> None:
        self.family = family

    @property
    def ok(self) -> bool:
        return self.family is not None

    def text(self, value: Any) -> str:
        raw = "" if value is None else str(value)
        if self.ok:
            return raw
        for source, target in _TRANSLITERATE.items():
            raw = raw.replace(source, target)
        # Anything still outside latin-1 is a script this build cannot set.
        # Marked rather than dropped, so a reader can see that something was
        # there -- silently deleting a Devanagari declaration would make the
        # report claim the pack did not carry it.
        return re.sub(r"[^\x00-\xff]+", "[non-Latin text omitted]", raw)


def _register_font(pdf: Any) -> _Unicode:
    for family, path in FONT_CANDIDATES:
        if not Path(path).is_file():
            continue
        try:
            pdf.add_font(family, "", path)
            pdf.add_font(family, "B", path)
            return _Unicode(family)
        except Exception:  # a face fpdf2 cannot parse is not a reason to fail
            continue
    return _Unicode(None)


class _Doc:
    """Thin wrapper so the body below reads as a document, not as an API."""

    def __init__(self) -> None:
        from fpdf import FPDF

        self.pdf = FPDF(orientation="P", unit="mm", format="A4")
        self.pdf.set_auto_page_break(auto=True, margin=MARGIN_MM)
        self.pdf.set_margins(MARGIN_MM, MARGIN_MM, MARGIN_MM)
        self.pdf.add_page()
        self.uni = _register_font(self.pdf)
        self.base = self.uni.family or "Helvetica"

    def font(self, size: float = 9.5, bold: bool = False) -> None:
        self.pdf.set_font(self.base, "B" if bold else "", size)

    def heading(self, text: str, size: float = 13.0) -> None:
        self.pdf.ln(3)
        self.font(size, bold=True)
        self.pdf.multi_cell(BODY_W_MM, size * 0.52, self.uni.text(text))
        self.pdf.ln(1)

    def para(self, text: str, size: float = 9.5, bold: bool = False) -> None:
        if not text:
            return
        self.font(size, bold=bold)
        self.pdf.multi_cell(BODY_W_MM, size * 0.48, self.uni.text(text))
        self.pdf.ln(1)

    def rows(self, pairs, widths=(58.0, 124.0), header: tuple[str, ...] | None = None) -> None:
        """A two- or three-column table drawn from primitives.

        `multi_cell` with `max_line_height` rather than fpdf2's table API: the
        table API has moved between minor versions, and this file exists to work
        on a machine where nothing else does.
        """
        if header:
            self.font(9.0, bold=True)
            for width, cell in zip(widths, header, strict=False):
                self.pdf.cell(width, 5.2, self.uni.text(cell), border="B")
            self.pdf.ln(5.2)
        self.font(9.0)
        for row in pairs:
            top = self.pdf.get_y()
            if top > 262:
                self.pdf.add_page()
                top = self.pdf.get_y()
            height = 0.0
            for index, (width, cell) in enumerate(zip(widths, row, strict=False)):
                self.pdf.set_xy(MARGIN_MM + sum(widths[:index]), top)
                self.pdf.multi_cell(width, 4.6, self.uni.text(cell), align="L")
                height = max(height, self.pdf.get_y() - top)
            self.pdf.set_y(top + max(height, 4.6) + 0.6)


def _findings(doc: _Doc, findings) -> None:
    rows = []
    for finding in findings:
        observed = []
        if finding.found:
            observed.append(f"read: {finding.found}")
        if finding.expected:
            observed.append(f"required: {finding.expected}")
        rows.append(
            (
                f"{finding.rule_ref}\n{finding.rule_id}",
                f"{finding.message}\n" + ("; ".join(observed) if observed else ""),
                f"{finding.status} ({finding.severity})",
            )
        )
    doc.rows(rows, widths=(46.0, 108.0, 28.0), header=("Provision", "Finding", "Status"))


def to_pdf(report: Any) -> bytes:
    """The per-scan report as a PDF, with no native libraries. Returns bytes."""
    doc = _Doc()

    doc.heading("Package declaration check", 15.0)
    doc.para(
        "Legal Metrology (Packaged Commodities) Rules, 2011 - form of report "
        "modelled on Rule 19(2), Seventh Schedule, Form A."
    )
    doc.para(f"Generated by AKSHAR from rulepack {report.provenance.rulepack_version}.")
    doc.para(report.headline, size=10.5, bold=True)

    doc.heading("Part A - Particulars of the package")
    doc.rows(
        [
            ("Commodity", report.package.title),
            ("Category", report.package.category or "-"),
            ("Manufacturer / packer / importer", report.package.manufacturer or "not read"),
            ("Net quantity as declared", report.package.net_quantity or "not read"),
            ("Retail sale price as declared", report.package.mrp or "not read"),
            ("Barcode", report.package.barcode or "-"),
            ("Date and time of check", report.captured_at.strftime("%d %B %Y, %H:%M")),
            ("District", report.district or "-"),
            ("Scan reference", report.scan_id),
        ]
    )

    doc.heading("Parts B, C and D - Net quantity by weight")
    doc.para(report.form_a_not_applicable_reason)
    doc.rows(
        [(part, title, "Not applicable") for part, title in report.form_a_not_applicable],
        widths=(18.0, 136.0, 28.0),
        header=("Part", "Title", "Status"),
    )

    doc.heading("Part E - Findings on the declarations")
    if report.violations:
        _findings(doc, report.violations)
    else:
        doc.para("No contravention was found in the declarations that could be checked.")
    if report.reviews:
        doc.para(
            "A finding marked REVIEW is a measurement that falls within this system's own "
            "measurement error of the prescribed limit. It is not asserted as a contravention "
            "and requires physical examination before any action is taken."
        )

    if report.not_checked:
        doc.heading("Checks that could not be carried out")
        doc.para(
            "These provisions were not evaluated. Their absence from Part E is not a "
            "finding of compliance."
        )
        doc.rows(
            [(f"{f.rule_ref}\n{f.rule_id}", f.message) for f in report.not_checked],
            widths=(52.0, 130.0),
            header=("Provision", "Reason"),
        )

    if report.advisory:
        doc.heading("Advisory - printing of unit symbols")
        doc.para(
            "These are formatting defects under the National Standards (Prescription and "
            "Verification) Rules, 2011, Third Schedule. They are reported separately from "
            "Part E and no contravention of the Packaged Commodities Rules is asserted on "
            "their basis."
        )
        _findings(doc, report.advisory)

    doc.heading("Exhibit - the label as it was read")
    if report.exhibit is not None:
        try:
            doc.pdf.image(io.BytesIO(report.exhibit.jpeg), w=BODY_W_MM)
            doc.pdf.ln(2)
        except Exception:  # a corrupt exhibit must not lose the whole report
            doc.para("The exhibit image could not be embedded.")
        doc.para(
            "The photograph flattened to the plane of the label, which is the image every "
            "measurement in Part E was taken from."
        )
        for label, meaning, _colour in report.exhibit.legend:
            doc.para(f"  - {label}: {meaning}", size=8.5)
        doc.para(f"SHA-256 {report.exhibit.sha256}", size=8.0)
    else:
        doc.para(report.exhibit_note)

    doc.heading("How this check was carried out")
    coverage = report.provenance.coverage
    doc.rows(
        [
            ("Rulepack", report.provenance.rulepack_version),
            ("Degradation tier", report.provenance.degradation_tier),
            ("Label coverage", "-" if coverage is None else f"{coverage:.0%}"),
            *[(name, version) for name, version in report.provenance.model_versions.items()],
            ("Photograph", report.provenance.image_sha256 or "not retained"),
            ("Record digest", report.provenance.record_sha256 or "-"),
            (
                "Chain position",
                "-"
                if report.provenance.chain_seq is None
                else str(report.provenance.chain_seq),
            ),
        ]
    )
    doc.para(report.provenance.evidence_note, size=8.5)

    doc.heading("Part F - Signatures")
    doc.rows(
        [
            (
                f"\n\n{report.officer_name or ''}\n{report.officer_designation}",
                "\n\nName, signature and date",
            )
        ],
        widths=(91.0, 91.0),
        header=("Authorised officer", "Manufacturer's representative"),
    )

    doc.pdf.ln(2)
    note = (
        "Rendered by AKSHAR's fallback PDF writer, which needs no native libraries. "
        "The deployed system renders the same report through WeasyPrint from the HTML "
        "template and it is laid out differently."
    )
    if not doc.uni.ok:
        note += (
            " No Unicode font was available on this host, so non-Latin text has been "
            "marked rather than printed. The DOCX and HTML formats are unaffected."
        )
    doc.para(note, size=7.5)

    return bytes(doc.pdf.output())


def summary_to_pdf(report: Any) -> bytes:
    """The violation summary as a PDF, walking `reports.summary_model.SummaryReport`.

    The same object the HTML template and the DOCX walk, so the three cannot
    report different figures for the same period. Every cell arrives already
    formatted -- an em dash for a rate that does not exist is decided in the
    model, once, because a renderer that turned None into "0%" here would report
    the districts nobody visited as fully compliant.
    """
    doc = _Doc()

    doc.heading("Violation summary", 15.0)
    doc.para(f"Legal Metrology (Packaged Commodities) Rules, 2011 - {report.scope}.")
    doc.para(
        f"Period: {report.period}. Prepared "
        f"{report.generated_at.strftime('%d %B %Y, %H:%M')}"
        + (f" - {report.office}." if report.office else ".")
    )
    doc.para(report.headline, size=10.5, bold=True)
    if report.coverage_note:
        doc.para(report.coverage_note)

    doc.rows(
        [
            ("Scans", str(report.scans)),
            ("Checked", str(report.conclusive)),
            ("Products", str(report.unique_skus)),
            ("Contravention rate", str(report.non_compliance_rate)),
            ("High severity", str(report.high_severity)),
            ("For examination", str(report.awaiting_review)),
        ],
        widths=(58.0, 124.0),
    )

    for table in report.tables:
        doc.heading(table.title, 11.5)
        if not table.rows:
            doc.para(table.empty_note)
            continue
        columns = len(table.headers)
        first = 56.0
        rest = (BODY_W_MM - first) / max(1, columns - 1)
        widths = (first, *([rest] * (columns - 1)))
        doc.rows(
            [
                (row.label + (f"\n{row.note}" if row.note else ""), *row.cells)
                for row in table.rows
            ],
            widths=widths,
            header=tuple(table.headers),
        )
        if table.footnote:
            doc.para(table.footnote, size=8.0)

    doc.heading("How these figures were counted", 11.5)
    for title, explanation in report.counting_rules:
        doc.para(f"{title}. {explanation}", size=8.5)

    doc.para(
        "Every figure above is produced by the same computation that serves the live "
        "dashboard, so this document and the screen cannot report different numbers for "
        "the same period. Mean coverage of the label text read across these scans: "
        f"{report.mean_coverage}.",
        size=8.5,
    )
    doc.para(
        "This summary reports declarations as printed on packages, checked from "
        "photographs. No package was opened, weighed or measured for net quantity, so "
        "nothing here is a finding about the quantity actually contained in a package.",
        size=8.5,
    )
    if not doc.uni.ok:
        doc.para(
            "No Unicode font was available on this host, so non-Latin text has been "
            "marked rather than printed.",
            size=7.5,
        )
    return bytes(doc.pdf.output())


__all__ = ["summary_to_pdf", "to_pdf"]
