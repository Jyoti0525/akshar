"""What a report says, decided once. AKSHAR.md sections 13, 13b, 13c, M8.

**Three renderings, one model.** The plan asks for a PDF and an editable DOCX,
and the dashboard already showed what happens when the same question is answered
in two places: `api/analytics.py` exists because a JSON view, a CSV export and a
PDF summary computing their own non-compliance rates will eventually disagree,
in public. The same argument applies inside one document. So the *shape* of the
report — which findings are violations, which are advisory, which were never
checked — is settled here, and the renderers only lay it out.

That is not a stylistic preference. Section 13 requires the five unit-symbol
checks in a **separate advisory block**, and if that separation is a filter
inside a Jinja template then the DOCX writer can simply forget it. Here it is
three different fields, and a renderer that forgets one produces a visibly empty
section rather than a document that quietly reports `250 ML` as a violation
beside a missing MRP.

**The section nobody asks for is the one that protects us.** A report that lists
findings and stops implies everything else was checked and passed. It was not:
a scan at tier C cannot measure a millimetre, and a declaration the OCR never
read cannot be judged. `not_checked` carries those with their reasons, because
a document that overstates its own coverage is the kind of thing that collapses
under cross-examination — and it is the same `NO_DATA` discipline the rules
engine and the dashboard already keep.

**Nothing here decides compliance.** Every status arrives from `rules.engine`.
This module groups, orders and phrases.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from evidence.annotate import LEGEND as EXHIBIT_LEGEND

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
STATUS_ORDER = {"FAIL": 0, "REVIEW": 1, "NO_DATA": 2, "PASS": 3, "NOT_APPLICABLE": 4}

RESPONDENT_LABEL = {
    "manufacturer": "Manufacturer / packer",
    "packer": "Packer",
    "importer": "Importer",
    "dealer": "Dealer / retailer",
}

# Section 13b: Rule 18(5) is the RETAILER's offence, not the manufacturer's, so
# the notice is addressed to a different person. A report that lumps every
# finding under "manufacturer" sends a dealer's offence to the wrong party.
_REMEDIATION_BY_CHECK: dict[str, str] = {
    "present": "Print this declaration on the principal display panel.",
    "conditional_present": (
        "Print this declaration; the condition that makes it mandatory is met."
    ),
    "min_height_mm": "Reprint at or above the required height.",
    "min_width_ratio": "Widen the characters — Rule 7(3) requires at least one third of the height.",
    "min_contrast": "Print in a colour that contrasts with the background, and do not obscure it.",
    "clear_space": "Move other printing clear of the space reserved around this declaration.",
    "same_panel": "Group this declaration with the others on the principal display panel.",
    "regex": "Correct the wording so it matches the form the gazette prescribes.",
    "regex_absent": "Remove this word or expression from the label.",
    "no_duplicate_field": "Remove the second declaration; only one may appear.",
    "in_table": "Use a commodity and unit permitted by the Schedule for this product.",
    "symbol_case": "Print the unit symbol in lower case, as prescribed.",
    "value_in_range": (
        "Choose the multiple or sub-multiple so the numeral falls between 0.1 and 1000."
    ),
}
"""One line per check type, keyed on the *check*, not the rule.

Thirteen check types and thirteen entries — `tests/test_boundaries.py` already
asserts there is no fourteenth, so this cannot silently fall behind the engine.

Phrased as an instruction to a manufacturer rather than a restatement of the
rule, because the rule is printed directly above it. "Reprint at or above the
required height" is what the reader does next; "the height is below the
threshold" is what they already read.
"""


@dataclass(frozen=True, slots=True)
class Finding:
    """One rule's outcome, in the words the report prints."""

    rule_id: str
    rule_ref: str
    status: str
    severity: str
    message: str
    field: str | None = None
    found: str | None = None
    expected: str | None = None
    measured: float | None = None
    threshold: float | None = None
    tolerance: float | None = None
    respondent: str = "manufacturer"
    check: str = ""

    @property
    def respondent_label(self) -> str:
        return RESPONDENT_LABEL.get(self.respondent, self.respondent.title())

    @property
    def remediation(self) -> str:
        return _REMEDIATION_BY_CHECK.get(self.check, "Correct the declaration.")

    @property
    def measurement(self) -> str | None:
        """The millimetre finding with its error bar, or None.

        **The tolerance is printed, never dropped.** A report saying "0.94 mm,
        required 1 mm" invites the question it cannot answer — how sure are you
        — and `rules/checks/min_height_mm.py` has already used that same number
        to decide between FAIL and REVIEW. Printing the decision without the
        quantity it rested on would hide the reasoning at exactly the point
        somebody wants to check it.
        """
        if self.measured is None:
            return None
        tolerance = f" ± {self.tolerance:.2f}" if self.tolerance is not None else ""
        threshold = f", required ≥ {self.threshold:g} mm" if self.threshold is not None else ""
        return f"{self.measured:.2f}{tolerance} mm{threshold}"

    @property
    def sort_key(self) -> tuple[int, int, str]:
        return (
            STATUS_ORDER.get(self.status, 9),
            SEVERITY_ORDER.get(self.severity, 9),
            self.rule_id,
        )


@dataclass(frozen=True, slots=True)
class Package:
    """Form A, Part A — particulars of the package.

    Every field is optional because a scan that matched no SKU still produces a
    report, and section 11's whole categories argument turns on unmatched scans
    being real. A blank line in Part A is honest; inventing a brand is not.
    """

    brand: str | None = None
    variant: str | None = None
    pack_size: str | None = None
    category: str | None = None
    barcode: str | None = None
    manufacturer: str | None = None
    net_quantity: str | None = None
    mrp: str | None = None

    @property
    def title(self) -> str:
        parts = [p for p in (self.brand, self.variant, self.pack_size) if p]
        return " ".join(parts) if parts else "Unidentified package"


@dataclass(frozen=True, slots=True)
class Provenance:
    """What section 14 requires in order to reproduce this finding later.

    *"A finding you cannot reproduce is a finding you cannot defend."* Six months
    on, a manufacturer disputes a 1.8 mm measurement. Re-running it needs the
    rulepack version, the model digests, the photograph and the proof that the
    photograph and the record are the ones that produced it. All six live here
    and all six print.
    """

    rulepack_version: str = ""
    model_versions: dict[str, str] = field(default_factory=dict)
    degradation_tier: str = "L0"
    scale_tier: str | None = None
    coverage: float | None = None
    latency_ms: int | None = None
    image_key: str | None = None
    image_sha256: str | None = None
    record_sha256: str | None = None
    chain_seq: int | None = None

    @property
    def evidence_note(self) -> str:
        if self.image_sha256:
            return (
                "The photograph is stored under a write-once retention lock and its "
                "SHA-256 is inside this record's hash, so a later substitution is "
                "detectable."
            )
        return (
            "No photograph is retained for this scan. The record, its time and its "
            "verdicts are unaffected."
        )


# Section 13b: Rule 19(2) and the Seventh Schedule prescribe Form A. We mirror
# Parts A, E and F and mark the weight-checking parts inapplicable **by name**,
# rather than omitting them.
#
# "That single decision is worth more than any feature. An officer receives a
#  document already shaped like the one they are required to file, and it makes
#  the omission of weight checking explicit rather than hidden."
FORM_A_NOT_APPLICABLE = (
    ("Part B", "Details of the sample drawn"),
    ("Part C", "Checking of net quantity by weight"),
    ("Part D", "Computation of errors and permissible limits"),
)

FORM_A_NOT_APPLICABLE_REASON = (
    "Not applicable — this is a declaration check carried out from a photograph. "
    "No package was opened, weighed or measured for net quantity, so Rule 19(2)'s "
    "weight-checking parts are not completed. Nothing in this report is a finding "
    "about the quantity actually contained in the package."
)


@dataclass(frozen=True, slots=True)
class Exhibit:
    """The annotated label, ready to be laid into a document. Section 13.

    Carried as bytes rather than as a URL. A report is a file an officer emails,
    files or prints; a picture that resolves over the network would be missing
    from every one of those, and `reports/render.py` deliberately gives
    WeasyPrint no `base_url` for the same reason.

    The digest is printed under the exhibit. It costs a line and it means two
    copies of a report can be shown to be illustrated by the same image — the
    question a manufacturer asks when they dispute what a box is drawn around.
    """

    jpeg: bytes
    boxes: int = 0
    note: str = ""

    @property
    def data_uri(self) -> str:
        return "data:image/jpeg;base64," + base64.b64encode(self.jpeg).decode("ascii")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.jpeg).hexdigest()

    @property
    def legend(self) -> tuple[tuple[str, str, str], ...]:
        return EXHIBIT_LEGEND


@dataclass(frozen=True, slots=True)
class ProductReport:
    """One package, one report. The whole document, before any layout."""

    scan_id: str
    captured_at: datetime
    package: Package
    provenance: Provenance

    officer_name: str | None = None
    officer_designation: str = "Legal Metrology Officer"
    district: str | None = None
    place: str | None = None

    violations: tuple[Finding, ...] = ()
    """FAIL and REVIEW, excluding advisory. What a notice would be based on."""

    advisory: tuple[Finding, ...] = ()
    """The five section 13c symbol checks. Formatting defects, reported apart."""

    not_checked: tuple[Finding, ...] = ()
    """NO_DATA. What we could not judge, and why."""

    passed: tuple[Finding, ...] = ()
    not_applicable: tuple[Finding, ...] = ()

    exhibit: Exhibit | None = None
    """The annotated label, when one was stored for this scan."""

    exhibit_note: str = ""
    """Why there is no exhibit, when there is not one.

    Printed. A report that simply omits the picture leaves a reader to guess
    whether the system failed, the officer's photograph was of a repeat SKU
    already on file, or privacy redaction stopped it — three answers with very
    different weight. `api/scanning.py` produces the sentence at the moment the
    decision is made, which is the only place it is actually known.
    """

    @property
    def failures(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.violations if f.status == "FAIL")

    @property
    def reviews(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.violations if f.status == "REVIEW")

    @property
    def high_severity(self) -> int:
        return sum(1 for f in self.failures if f.severity == "high")

    @property
    def respondents(self) -> tuple[str, ...]:
        """Who this report is addressed to. Usually one party; sometimes two.

        Rule 18(5) is the retailer's offence. A report carrying both a
        manufacturer's labelling failure and a dealer's is two notices to two
        people, and saying so here is what stops it becoming one notice to the
        wrong one.
        """
        seen = {f.respondent for f in self.failures}
        return tuple(sorted(seen))

    @property
    def headline(self) -> str:
        """The single sentence at the top, and it must not overstate.

        A clean scan that read half the label is not "compliant" — it is
        "nothing found in what we could read", and the difference is the whole
        `not_checked` section below it.
        """
        if self.failures:
            count = len(self.failures)
            noun, verb = ("contravention", "was") if count == 1 else ("contraventions", "were")
            return f"{count} apparent {noun} of the Rules {verb} found."
        if self.reviews:
            return (
                f"No contravention is asserted. {len(self.reviews)} measurement(s) fell "
                f"within the measurement error and require examination."
            )
        if not self.not_checked:
            return "No contravention was found in the declarations checked."
        return (
            f"No contravention was found in the declarations checked. "
            f"{len(self.not_checked)} check(s) could not be carried out — see below."
        )

    @property
    def form_a_not_applicable(self) -> tuple[tuple[str, str], ...]:
        return FORM_A_NOT_APPLICABLE

    @property
    def form_a_not_applicable_reason(self) -> str:
        return FORM_A_NOT_APPLICABLE_REASON


def _finding(row: dict[str, Any], checks: dict[str, str]) -> Finding:
    return Finding(
        rule_id=row["rule_id"],
        rule_ref=row.get("rule_ref", ""),
        status=row["status"],
        severity=row.get("severity", "medium"),
        message=row.get("message", ""),
        field=row.get("field"),
        found=row.get("found"),
        expected=row.get("expected"),
        measured=_as_float(row.get("measured")),
        threshold=_as_float(row.get("threshold")),
        tolerance=_as_float(row.get("tolerance")),
        respondent=row.get("respondent") or "manufacturer",
        check=checks.get(row["rule_id"], ""),
    )


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def build(
    *,
    scan: dict[str, Any],
    verdicts: list[dict[str, Any]],
    package: Package | None = None,
    officer_name: str | None = None,
    checks: dict[str, str] | None = None,
    exhibit: Exhibit | None = None,
    exhibit_note: str = "",
) -> ProductReport:
    """Assemble the report from a stored scan and its verdicts.

    Takes rows rather than objects so it works identically against the in-memory
    store and Postgres, and so a report can be re-rendered years later from the
    database alone — which is the point of storing the declaration set and the
    model versions in the first place.

    **Suppressed verdicts do not appear at all.** One measurement yields one
    verdict; printing both the suppressed rule and the rule that suppressed it
    would show the same finding twice under two citations, which reads as two
    contraventions to anyone counting.
    """
    checks = checks or {}
    # Row and finding stay paired. An earlier version filtered `verdicts` into
    # `findings` and then zipped the two lists back together to recover the
    # advisory flag — but the filter had removed the suppressed rows from one
    # side only, so every flag after the first suppressed verdict belonged to
    # the wrong rule. Keeping the tuple is both shorter and impossible to
    # misalign.
    pairs = [
        (row, _finding(row, checks)) for row in verdicts if not row.get("suppressed_by")
    ]

    def ordered(items: list[Finding]) -> tuple[Finding, ...]:
        return tuple(sorted(items, key=lambda f: f.sort_key))

    def adverse(*, advisory: bool) -> list[Finding]:
        return [
            finding
            for row, finding in pairs
            if bool(row.get("advisory")) is advisory and finding.status in {"FAIL", "REVIEW"}
        ]

    return ProductReport(
        scan_id=str(scan["id"]),
        captured_at=scan["captured_at"],
        package=package or Package(),
        officer_name=officer_name,
        district=scan.get("district"),
        provenance=Provenance(
            rulepack_version=scan.get("rulepack_version", ""),
            model_versions=scan.get("model_versions") or {},
            degradation_tier=scan.get("degradation_tier", "L0"),
            coverage=_as_float(scan.get("coverage")),
            latency_ms=scan.get("latency_ms"),
            image_key=scan.get("image_key"),
            image_sha256=scan.get("image_sha256"),
            record_sha256=scan.get("record_sha256"),
            chain_seq=scan.get("chain_seq"),
        ),
        exhibit=exhibit,
        exhibit_note=exhibit_note,
        violations=ordered(adverse(advisory=False)),
        advisory=ordered(adverse(advisory=True)),
        not_checked=ordered([f for _, f in pairs if f.status == "NO_DATA"]),
        passed=ordered([f for _, f in pairs if f.status == "PASS"]),
        not_applicable=ordered([f for _, f in pairs if f.status == "NOT_APPLICABLE"]),
    )


__all__ = [
    "EXHIBIT_LEGEND",
    "FORM_A_NOT_APPLICABLE",
    "FORM_A_NOT_APPLICABLE_REASON",
    "Exhibit",
    "Finding",
    "Package",
    "ProductReport",
    "Provenance",
    "build",
]
