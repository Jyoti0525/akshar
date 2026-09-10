"""Typed view of the rulepack — AKSHAR.md section 13.

The YAML is authoritative; these classes only give it a shape the engine can
rely on. Unknown keys are preserved in ``raw`` so a rulepack written for a
newer engine still loads instead of exploding — the plan's whole argument is
that a new notification is a data edit, not a release.

No I/O here and no cv2. See docs/spec-deltas.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from contracts import FieldName, Severity, VerdictStatus

CheckType = Literal[
    "present",
    "regex",
    "regex_absent",
    "min_height_mm",
    "min_width_ratio",
    "same_panel",
    "clear_space",
    "min_contrast",
    "no_duplicate_field",
    "conditional_present",
    "in_table",
    "symbol_case",
    "value_in_range",
]
"""The thirteen check types. Section 13: "Build these and no more."

`ratio_min` was deliberately dropped, and with it the `usp` field name. Both
existed only for a "Unit Sale Price must be half the MRP height" rule that came
from a vendor blog and is not in the 2011 Rules.
"""

ALLOWED_CHECKS: frozenset[str] = frozenset(
    [
        "present",
        "regex",
        "regex_absent",
        "min_height_mm",
        "min_width_ratio",
        "same_panel",
        "clear_space",
        "min_contrast",
        "no_duplicate_field",
        "conditional_present",
        "in_table",
        "symbol_case",
        "value_in_range",
    ]
)


# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Pattern:
    """A named pattern with one compiled regex per script.

    Both scripts are always tried. A Hindi-only label is lawful (LMPC permits
    Hindi or English) and reporting "MRP not found" on one would be the worst
    failure this system can produce.
    """

    name: str
    by_script: dict[str, re.Pattern[str]]

    def search(self, text: str) -> re.Match[str] | None:
        for compiled in self.by_script.values():
            m = compiled.search(text)
            if m:
                return m
        return None

    def matches(self, text: str) -> bool:
        return self.search(text) is not None

    def findall(self, text: str) -> list[str]:
        out: list[str] = []
        for compiled in self.by_script.values():
            out.extend(m.group(0) for m in compiled.finditer(text))
        return out


@dataclass(frozen=True, slots=True)
class Rule:
    """One rule from the pack."""

    id: str
    rule_ref: str
    check: str
    severity: Severity
    message: str
    raw: dict[str, Any] = field(default_factory=dict)

    # -- targeting ----------------------------------------------------------
    field_name: FieldName | None = None
    fields: tuple[FieldName, ...] = ()

    enabled: bool = True
    advisory: bool = False
    scale_free: bool = False
    requires: tuple[str, ...] = ()

    respondent: Literal["manufacturer", "packer", "importer", "dealer"] = "manufacturer"
    suppresses: str | None = None
    on_locate_fail: str | None = None

    def target_fields(self) -> tuple[FieldName, ...]:
        """A rule names either one `field:` or a list of `fields:`."""
        if self.fields:
            return self.fields
        if self.field_name is not None:
            return (self.field_name,)
        return ()

    def opt(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)


@dataclass(frozen=True, slots=True)
class Rulepack:
    """The loaded pack. Passed to the engine; the engine never reads a file."""

    pack_id: str
    version: str
    authority: str
    rules: tuple[Rule, ...]
    extension_rules: tuple[Rule, ...]
    patterns: dict[str, Pattern]
    tables: dict[str, Any]
    applicability: dict[str, Any]
    meta: dict[str, Any]

    def all_rules(self, include_extensions: bool = True) -> tuple[Rule, ...]:
        return self.rules + self.extension_rules if include_extensions else self.rules

    def pattern(self, name: str | None) -> Pattern | None:
        return self.patterns.get(name) if name else None

    def table(self, name: str | None) -> Any:
        return self.tables.get(name) if name else None

    @property
    def version_string(self) -> str:
        """Stamped onto every scan so a disputed finding can be re-run exactly."""
        return f"{self.pack_id}@{self.version}"

    def claims_currency(self) -> bool:
        """False while any amendment's effect is unverified (section 13a).

        The version string must never claim an amendment the source register
        cannot evidence.

        **This reads `amendments_unverified`, not `amendments_checked`**, and
        the distinction is the whole point of the 13a rewrite. A *checked*
        amendment has had its effect confirmed — GSR 128(E) and GSR 312(E) are
        platform obligations, GSR 734(E) expired, GSR 748(E) is already
        reflected in the principal text — so none of them blocks a currency
        claim. An *unverified* one is a claim from a secondary source that
        nobody has put a gazette behind, and it blocks.

        The predicate previously read `amendments_known_missing`, a key the
        2026-09-07 meta rewrite removed. `dict.get` on a missing key returns
        `None`, so it began answering **True** — the pack quietly started
        claiming to be current, which is the exact failure this function
        exists to prevent. Hence the test.
        """
        return not self.meta.get("amendments_unverified")


# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    """What a check function returns. The engine turns this into a `Verdict`.

    A check reports what it measured; it does not compose the officer-facing
    sentence. That keeps the legal wording in the YAML where it can be reviewed
    by someone who is not a programmer.
    """

    status: VerdictStatus
    found: str | None = None
    expected: str | None = None
    measured: float | None = None
    threshold: float | None = None
    tolerance: float | None = None
    detail: str | None = None
    field_name: FieldName | None = None

    @classmethod
    def no_data(cls, why: str) -> CheckOutcome:
        """Absence of evidence is not evidence of a violation."""
        return cls(status="NO_DATA", detail=why)

    @classmethod
    def not_applicable(cls, why: str) -> CheckOutcome:
        return cls(status="NOT_APPLICABLE", detail=why)


__all__ = [
    "ALLOWED_CHECKS",
    "CheckOutcome",
    "CheckType",
    "Pattern",
    "Rule",
    "Rulepack",
]
