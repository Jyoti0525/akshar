"""The rules engine — AKSHAR.md sections 3, 9 and 13.

A pure function from (DeclarationSet, PackageContext, Rulepack) to a list of
Verdicts. No I/O, no image, no database session, no network.

    from rules.engine import evaluate
    verdicts = evaluate(declaration_set, package_context, rulepack)

This module MUST NOT import cv2, PaddleOCR, or the database.
`tests/test_boundaries.py` enforces that, and the reason is concrete rather
than aesthetic: the problem statement names three inputs and one of them is
pure text from an e-commerce listing. If OCR were wired straight into the
rules, that third channel would be a rewrite instead of an afternoon's work.

Rules decide, models never. A neural network may extract a fact; only this
file, driven by YAML, issues a verdict — because a rule can be read aloud in
court and a confidence score cannot.
"""

from __future__ import annotations

from contracts import DeclarationSet, PackageContext, Verdict
from rules import checks
from rules.applicability import Applicability, evaluate_applicability
from rules.models import CheckOutcome, Rule, Rulepack

_STATUS_RANK = {"FAIL": 0, "REVIEW": 1, "NO_DATA": 2, "NOT_APPLICABLE": 3, "PASS": 4}


def _requires_met(rule: Rule, ds: DeclarationSet) -> str | None:
    """Are this rule's declared inputs actually present?

    Returns the reason they are not, or None when the rule may run.

    When a `requires` key is missing the engine returns NO_DATA, never FAIL.
    Absence of evidence is not evidence of a violation — that is the difference
    between a tool an officer can rely on and one that generates false
    accusations.
    """
    for requirement in rule.requires:
        if requirement == "geometry.mm_per_px":
            # `has_scale`, not the bare scalar: on a multi-frame union the
            # set-level `mm_per_px` describes one nominated photograph, and a
            # declaration read from a different one carries a height in
            # millimetres of its own. Identical on a single frame, which is
            # every scan that existed before the union did.
            if not ds.has_scale():
                return "No scale was recovered (tier C), so height in millimetres is unknown."
        elif requirement == "geometry.pdp_polygon":
            if not ds.geometry.pdp_polygon:
                return "The principal display panel was not segmented."
        elif requirement.startswith("declarations."):
            field = requirement.split(".", 1)[1]
            if not ds.by_field(field):  # type: ignore[arg-type]
                return f"No {field.replace('_', ' ')} declaration was read."
        else:  # pragma: no cover - guarded by rulepack review
            return f"Unknown requirement '{requirement}'."
    return None


# What a verdict says when the check gave no detail of its own, keyed by status.
#
# **`rule.message` is the VIOLATION text**, and it may only appear on a verdict
# that alleges one. Falling back to it unconditionally produced rows reading
# "PASS - Net quantity not declared." and "PASS - Consumer care must declare
# name, address and telephone number." on a compliant pack. On screen that is
# merely confusing; in a report handed to a manufacturer under section 14 it is a
# document that states an offence and a clearance in the same line, and the
# manufacturer is right to ask which one the department means.
_DEFAULT_MESSAGE: dict[str, str] = {
    "PASS": "Requirement satisfied.",
    "NO_DATA": "Not evaluated: the inputs this rule needs were not read.",
    "NOT_APPLICABLE": "This rule does not apply to this package.",
}


def _to_verdict(rule: Rule, outcome: CheckOutcome) -> Verdict:
    return Verdict(
        rule_id=rule.id,
        rule_ref=rule.rule_ref,
        status=outcome.status,
        severity=rule.severity,
        field=outcome.field_name or rule.field_name,
        found=outcome.found,
        expected=outcome.expected or rule.message,
        message=outcome.detail or _DEFAULT_MESSAGE.get(outcome.status) or rule.message,
        measured=outcome.measured,
        threshold=outcome.threshold,
        tolerance=outcome.tolerance,
        unit=outcome.unit,
        respondent=rule.respondent,
        advisory=rule.advisory,
    )


def _apply_suppression(verdicts: list[Verdict], pack: Rulepack) -> list[Verdict]:
    """One measurement yields one verdict.

    `LMPC.MRP.DEFACED` (Rule 18(5), the dealer's offence) suppresses
    `LMPC.CONTRAST.NUMERALS` (Rule 9(1)(b), the manufacturer's), because they
    measure the same pixels and naming both would put two different people on
    one notice for one defect.

    Suppression only takes effect when the suppressing rule actually fired.
    """
    fired = {v.rule_id for v in verdicts if v.status in ("FAIL", "REVIEW")}
    suppressed: dict[str, str] = {}
    for rule in pack.all_rules():
        if rule.suppresses and rule.id in fired:
            suppressed[rule.suppresses] = rule.id

    if not suppressed:
        return verdicts

    out: list[Verdict] = []
    for v in verdicts:
        if v.rule_id in suppressed and v.status in ("FAIL", "REVIEW"):
            out.append(
                v.model_copy(
                    update={
                        "status": "NOT_APPLICABLE",
                        "suppressed_by": suppressed[v.rule_id],
                        "message": (
                            f"Reported under {suppressed[v.rule_id]}; one measurement "
                            f"yields one verdict."
                        ),
                    }
                )
            )
        else:
            out.append(v)
    return out


def evaluate(
    ds: DeclarationSet,
    ctx: PackageContext | None = None,
    pack: Rulepack | None = None,
    *,
    include_extensions: bool = True,
) -> list[Verdict]:
    """Judge one package.

    Ordering of the returned list is deterministic: worst status first, then
    high severity first, then rulepack order — so a report and a dashboard row
    always agree, and a golden-file test is stable.
    """
    if pack is None:  # pragma: no cover - convenience for callers outside the API
        from rules.loader import cached_rulepack

        pack = cached_rulepack()
    context = ctx or PackageContext()

    gate: Applicability = evaluate_applicability(ds, context, pack.applicability)

    verdicts: list[Verdict] = []
    for index, rule in enumerate(pack.all_rules(include_extensions)):
        if not rule.enabled:
            # LMPC.UNIT.LITRE_SYMBOL ships disabled: the gazette gives `l` but
            # BIPM accepts `L` and every Indian beverage label uses it.
            continue

        # 1 — the applicability gate, before anything else.
        if (blocked := gate.blocks(rule.target_fields())) is not None:
            verdicts.append(_to_verdict(rule, CheckOutcome.not_applicable(blocked)))
            continue

        # 2 — Rule 7(4): height rules disapplied where another statute governs.
        if gate.height_rules_disapplied and rule.check in checks.REQUIRES_MILLIMETRES:
            targets = set(rule.target_fields())
            if targets and targets <= set(context.other_law_mandates):
                verdicts.append(
                    _to_verdict(
                        rule,
                        CheckOutcome.not_applicable(
                            "Rule 7(4): another statute mandates this information."
                        ),
                    )
                )
                continue

        # 3 — declared inputs present? If not, NO_DATA, never FAIL.
        if (missing := _requires_met(rule, ds)) is not None:
            verdicts.append(_to_verdict(rule, CheckOutcome.no_data(missing)))
            continue

        # 4 — run the check.
        outcome = checks.get(rule.check)(rule, ds, context, pack)
        verdicts.append(_to_verdict(rule, outcome))

        del index  # ordering is applied below, not here

    verdicts = _apply_suppression(verdicts, pack)

    order = {r.id: i for i, r in enumerate(pack.all_rules(include_extensions))}
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    verdicts.sort(
        key=lambda v: (
            _STATUS_RANK.get(v.status, 9),
            severity_rank.get(v.severity, 9),
            order.get(v.rule_id, 999),
        )
    )
    return verdicts


def summarise(verdicts: list[Verdict]) -> dict[str, int]:
    """Counts by status, for the scan screen and the dashboard tiles."""
    out: dict[str, int] = {
        "PASS": 0,
        "FAIL": 0,
        "REVIEW": 0,
        "NO_DATA": 0,
        "NOT_APPLICABLE": 0,
    }
    for v in verdicts:
        out[v.status] = out.get(v.status, 0) + 1
    return out


def is_compliant(verdicts: list[Verdict]) -> bool:
    """A package is compliant when no countable rule failed.

    REVIEW is deliberately NOT compliant and NOT a violation — it is work owed
    to a human, and the scan screen renders it amber rather than red.

    **Advisory failures do not make a package non-compliant.** The five
    unit-symbol rules and the numeration rule ship `advisory: true` precisely
    so that `250 ML` is not reported at the weight of a missing MRP —
    `rules/checks/symbol_case.py` says so, and `api/analytics.py` already
    excludes them from every violation count it publishes. This function did
    not, so a pack whose only defect was a lower-case `l` earned the same red
    "Non-compliant" headline as a pack with no price on it, and the dashboard
    then disagreed with the scan screen about the same scan.

    Measured on 52 corpus frames the day this changed: no frame was carried
    into non-compliance by advisory findings alone, so this corrects a
    disagreement between two layers rather than moving a number. It would have
    started moving numbers on the first clean pack.
    """
    return not any(v.status == "FAIL" and not v.advisory for v in verdicts)


__all__ = ["evaluate", "is_compliant", "summarise"]
