"""The violation summary, decided once. AKSHAR.md sections 13a and 11.

    "The dashboard is the live view; the summary is its printable form."
                                                            -- section 13a

**Built over `api.analytics.summary()`, never beside it.** That function already
exists because a JSON view, a CSV export and a PDF computing their own
non-compliance rates will eventually hand a department three different numbers
for one morning. A printed summary that recomputed anything would be the fourth
chance, and the worst one — it is the version that gets tabled at a meeting,
where nobody has the dashboard open to contradict it.

So this module receives the analytics payload and does two things to it:
**phrasing and formatting**. Every count and every rate arrives already
computed.

**A null rate is printed as an em dash, never as zero, and this is the whole
reason the formatting lives here.** `_rate()` returns None when there was
nothing conclusive to divide by, and section 11 built the districts view around
exactly that distinction: *"that last column identifies districts that are dark
rather than compliant."* A template that renders None as `0%` reports perfect
compliance in the districts nobody has visited — which is the opposite of the
truth, and the single most consequential thing this document could get wrong.
`percent()` is therefore one function that both renderers call.

**The three counting rules are printed in the document itself.** Advisory
verdicts are excluded, suppressed verdicts are excluded, and scans that
concluded nothing are outside the denominator. A reader comparing this page
against a raw count of rows will otherwise conclude the report is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

DASH = "—"

COUNTING_RULES: tuple[tuple[str, str], ...] = (
    (
        "Advisory findings are excluded",
        "The unit-symbol checks under the National Standards Rules, 2011 are "
        "formatting defects. They are not contraventions of the Packaged "
        "Commodities Rules and are not counted as violations anywhere in this "
        "summary.",
    ),
    (
        "One measurement, one violation",
        "Where two rules measured the same declaration, only the rule that "
        "governs it is counted. Counting both would double every rate on this "
        "page.",
    ),
    (
        "Scans that concluded nothing are not compliant scans",
        "A photograph from which no declaration could be judged is excluded from "
        "the denominator rather than counted as a pass. Otherwise a poor "
        "photograph improves the figures, which is an incentive an enforcement "
        "tool must not create.",
    ),
)


def percent(value: float | None, *, places: int = 1) -> str:
    """A rate as text. None becomes a dash, and that distinction is load-bearing.

    None means *we do not know* — no conclusive scan to divide by. Zero means we
    checked and found nothing wrong. A district with no scans printed as "0.0%"
    is a district reported as fully compliant on the strength of never having
    been visited.
    """
    if value is None:
        return DASH
    return f"{value * 100:.{places}f}%"


def number(value: Any) -> str:
    return DASH if value is None else f"{value:,}"


@dataclass(frozen=True, slots=True)
class Row:
    """One line of a summary table, already formatted.

    Formatted here rather than in each template so the DOCX and the PDF cannot
    disagree about how a null rate prints — see the module docstring.
    """

    label: str
    cells: tuple[str, ...]
    note: str = ""


@dataclass(frozen=True, slots=True)
class Table:
    title: str
    headers: tuple[str, ...]
    rows: tuple[Row, ...]
    empty_note: str = "Nothing to report for this period."
    footnote: str = ""

    def __bool__(self) -> bool:
        return bool(self.rows)


@dataclass(frozen=True, slots=True)
class SummaryReport:
    """One drive, district or period. The whole document, before any layout."""

    generated_at: datetime
    period: str
    scope: str

    scans: int
    conclusive: int
    inconclusive: int
    non_compliant: int
    non_compliance_rate: str
    unique_skus: int
    high_severity: int
    awaiting_review: int
    mean_coverage: str

    tables: tuple[Table, ...] = ()
    filters: dict[str, str] = field(default_factory=dict)
    office: str = ""
    prepared_by: str = ""

    @property
    def counting_rules(self) -> tuple[tuple[str, str], ...]:
        return COUNTING_RULES

    @property
    def headline(self) -> str:
        """The sentence at the top, and it must not overstate either way.

        With nothing conclusive there is no rate to report — and saying "0% of
        packages were non-compliant" over a week of unreadable photographs would
        be a false clean bill of health for every manufacturer in the district.
        """
        if self.conclusive == 0:
            return (
                f"{number(self.scans)} scan(s) were recorded and none produced a "
                f"conclusive check, so no non-compliance rate is reported."
            )
        noun = "package" if self.non_compliant == 1 else "packages"
        return (
            f"{number(self.non_compliant)} {noun} of {number(self.conclusive)} "
            f"checked were found to bear an apparent contravention "
            f"({self.non_compliance_rate})."
        )

    @property
    def coverage_note(self) -> str:
        if self.inconclusive == 0:
            return ""
        return (
            f"{number(self.inconclusive)} of {number(self.scans)} scan(s) reached no "
            f"conclusion and are excluded from the rate above. They are neither "
            f"compliant nor non-compliant."
        )


def _period(filters: dict[str, Any]) -> str:
    start, end = filters.get("date_from"), filters.get("date_to")
    if start and end:
        return f"{_day(start)} to {_day(end)}"
    if start:
        return f"From {_day(start)}"
    if end:
        return f"Up to {_day(end)}"
    return "All records held"


def _day(value: Any) -> str:
    if isinstance(value, date):
        return value.strftime("%d %B %Y")
    try:
        return date.fromisoformat(str(value)).strftime("%d %B %Y")
    except ValueError:
        return str(value)


def _scope(filters: dict[str, Any]) -> str:
    """What this summary is *of*, in the order an officer would say it.

    Named rather than left to a filter chip, because a summary detached from its
    scope is the document that gets forwarded as if it covered the whole state.
    """
    parts = []
    if filters.get("district"):
        parts.append(f"{filters['district']} district")
    if filters.get("category"):
        parts.append(str(filters["category"]))
    if filters.get("brand"):
        parts.append(f"brand matching “{filters['brand']}”")
    if filters.get("severity"):
        parts.append(f"{filters['severity']} severity and above")
    if filters.get("rule_id"):
        parts.append(f"rule {filters['rule_id']}")
    return ", ".join(parts) if parts else "All districts and categories"


def _violations(rows: list[dict[str, Any]]) -> Table:
    return Table(
        title="Provisions most often contravened",
        headers=("Provision", "Failed", "Checked", "Failure rate", "Severity"),
        rows=tuple(
            Row(
                label=row["rule_ref"] or row["rule_id"],
                cells=(
                    number(row["failed"]),
                    number(row["checked"]),
                    percent(row["fail_rate"]),
                    str(row["severity"]).title(),
                ),
                # Section 11: "A rule failing on 95% of products is more likely a
                # bug in our regex than a national conspiracy." It is flagged in
                # the printed summary as well as on screen, because this is the
                # copy somebody quotes in an advisory.
                note=(
                    "Fails on almost everything checked — verify the rule before "
                    "citing this figure."
                    if row.get("suspect")
                    else row["rule_id"]
                ),
            )
            for row in rows
        ),
        empty_note="No provision was contravened in the scans covered by this summary.",
    )


def _brands(rows: list[dict[str, Any]]) -> Table:
    return Table(
        title="Brands with the most serious findings",
        headers=("Brand", "High severity", "Scans", "SKUs", "Failure rate", "Most common"),
        rows=tuple(
            Row(
                label=row["brand"],
                cells=(
                    number(row["high_severity"]),
                    number(row["scans"]),
                    number(row["skus_checked"]),
                    percent(row["fail_rate"]),
                    row["worst_rule"] or DASH,
                ),
                note=f"Parent: {row['parent']}" if row.get("parent") else "",
            )
            for row in rows
        ),
        # Section 11's ordering argument, printed so a reader does not re-sort it
        # by rate and reach the opposite conclusion.
        footnote=(
            "Ordered by the number of high-severity findings, not by failure rate. "
            "A brand with two products and a 100% rate is noise; a national brand "
            "at 30% across forty products is a case worth opening."
        ),
        empty_note="No brand was identified in the scans covered by this summary.",
    )


def _categories(rows: list[dict[str, Any]]) -> Table:
    return Table(
        title="Commodity categories",
        headers=("Category", "Scans", "SKUs", "Failure rate", "For examination"),
        rows=tuple(
            Row(
                label=str(row["category"]).replace("_", " ").title(),
                cells=(
                    number(row["scans"]),
                    number(row["skus_checked"]),
                    percent(row["fail_rate"]),
                    number(row["awaiting_review"]),
                ),
            )
            for row in rows
        ),
    )


def _districts(rows: list[dict[str, Any]]) -> Table:
    return Table(
        title="Districts",
        headers=("District", "Scans", "Officers", "SKUs", "Failure rate", "Last scanned"),
        rows=tuple(
            Row(
                label=str(row["district"]).title(),
                cells=(
                    number(row["scans"]),
                    number(row["active_officers"]),
                    number(row["skus_checked"]),
                    percent(row["fail_rate"]),
                    _day(row["last_scanned"][:10]) if row.get("last_scanned") else DASH,
                ),
                note=(
                    "No conclusive check — this district is unmeasured, not compliant."
                    if row["fail_rate"] is None
                    else ""
                ),
            )
            for row in rows
        ),
        footnote=(
            "A dash in the failure-rate column means no scan in this district "
            "produced a conclusive check. It does not mean no contraventions "
            "exist there."
        ),
    )


def build(
    payload: dict[str, Any],
    *,
    office: str = "",
    prepared_by: str = "",
) -> SummaryReport:
    """Turn `api.analytics.summary()` into the printed document.

    The payload is passed through unchanged; nothing is recounted. If a figure
    is absent here it is absent from the dashboard too, which is the property
    that makes the two impossible to contradict.
    """
    filters = payload.get("filters") or {}
    generated = payload.get("generated_at")
    return SummaryReport(
        generated_at=(
            datetime.fromisoformat(generated) if generated else datetime.now(UTC)
        ),
        period=_period(filters),
        scope=_scope(filters),
        scans=payload["scans"],
        conclusive=payload["conclusive"],
        inconclusive=payload["inconclusive"],
        non_compliant=payload["non_compliant"],
        non_compliance_rate=percent(payload["non_compliance_rate"]),
        unique_skus=payload["unique_skus"],
        high_severity=payload["high_severity"],
        awaiting_review=payload["awaiting_review"],
        mean_coverage=percent(payload.get("mean_coverage"), places=0),
        tables=(
            _violations(payload.get("top_violations") or []),
            _brands(payload.get("repeat_offenders") or []),
            _categories(payload.get("categories") or []),
            _districts(payload.get("districts") or []),
        ),
        filters={str(key): str(value) for key, value in filters.items()},
        office=office,
        prepared_by=prepared_by,
    )


__all__ = [
    "COUNTING_RULES",
    "DASH",
    "Row",
    "SummaryReport",
    "Table",
    "build",
    "number",
    "percent",
]
