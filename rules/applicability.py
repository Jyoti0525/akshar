"""The applicability gate — AKSHAR.md sections 13 and 13b.

Runs BEFORE any rule. If the package is out of scope, every rule returns
NOT_APPLICABLE rather than being evaluated.

This exists because applying a rule to a package the rule does not govern
produces a false violation, and a false violation is worse than a missed one.
The wholesale gate (Rule 24) is the one most teams miss: a wholesale carton
needs only three declarations, and running retail rules against it manufactures
four violations on every single scan.

Pure. No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from contracts import DeclarationSet, FieldName, PackageContext
from rules.quantity import compare_to_limit, parse_quantity, within_limit


@dataclass(frozen=True, slots=True)
class Applicability:
    """Outcome of the gate."""

    in_scope: bool
    reason: str | None = None
    """Officer-facing explanation when out of scope, quoting the rule."""

    allowed_fields: frozenset[str] | None = None
    """Rule 24: when set, only these fields carry mandatory declarations.
    A rule targeting any other field returns NOT_APPLICABLE."""

    waived_fields: frozenset[str] = field(default_factory=frozenset)
    """Commodity carve-outs — bidis need no date, LPG at administered price
    needs no MRP."""

    height_rules_disapplied: bool = False
    """Rule 7(4): another statute mandates the same information, so the height
    rules of these rules do not apply to it."""

    def blocks(self, fields: tuple[FieldName, ...]) -> str | None:
        """Why this rule may not be applied, or None if it may."""
        if not self.in_scope:
            return self.reason or "Package is outside the scope of these rules."
        if not fields:
            return None
        if self.allowed_fields is not None and not (set(fields) & self.allowed_fields):
            return (
                "Rule 24: a wholesale package need only declare the manufacturer, "
                "the identity of the commodity, and the net quantity."
            )
        if fields and set(fields) <= self.waived_fields:
            return "This commodity is carved out of the declaration requirement."
        return None


# ---------------------------------------------------------------------------


def _resolve_quantity(ds: DeclarationSet, ctx: PackageContext) -> Any:
    """Prefer an explicitly supplied quantity; otherwise parse the declaration.

    The listing_text channel can supply a parsed quantity directly, because it
    has structured fields and no pixels to measure.
    """
    if ctx.net_quantity is not None:
        return ctx.net_quantity
    decl = ds.first("net_quantity")
    if decl is None:
        return None
    match = parse_quantity(decl.text)
    return match.to_parsed() if match else None


def evaluate_applicability(
    ds: DeclarationSet,
    ctx: PackageContext,
    applicability_spec: dict[str, Any],
) -> Applicability:
    """Run the six gates in the order the plan lists them.

    Size (3(a)) -> buyer (3(b)) -> small pack (26(a)) -> category (26(b)(c)(d))
    -> package type (24) -> other law (7(4)).
    """
    qty = _resolve_quantity(ds, ctx)

    # -- gates 1, 3 and 4: the declarative exclude_if list -------------------
    for clause in applicability_spec.get("exclude_if", []) or []:
        reason = clause.get("reason", "Package is outside the scope of these rules.")

        # Rule 3(b) / 26(b)(c): membership tests.
        if "consumer_type_in" in clause and ctx.consumer_type in clause["consumer_type_in"]:
            return Applicability(in_scope=False, reason=reason)

        category_hit = "category_in" in clause and ctx.category in clause["category_in"]
        if category_hit and "net_quantity_gt" not in clause:
            return Applicability(in_scope=False, reason=reason)

        # Rule 3(a) / 26(d): upper size limits.
        if "net_quantity_gt" in clause:
            limit = clause["net_quantity_gt"]
            if "category_in" in clause and not category_hit:
                continue
            exempted = clause.get("except_categories", []) or []
            if ctx.category in exempted:
                # cement and fertiliser stay in scope up to 50 kg
                over = compare_to_limit(qty, 50, limit["unit"])
            else:
                over = compare_to_limit(qty, limit["value"], limit["unit"])
            if over:
                return Applicability(in_scope=False, reason=reason)

        # Rule 26(a): small packages, 10 g or 10 ml and under.
        if "net_quantity_lte" in clause:
            limit = clause["net_quantity_lte"]
            under = within_limit(qty, limit["value"], limit["unit"])
            if under:
                return Applicability(in_scope=False, reason=reason)

    # -- gate 5: package type, Rule 24 --------------------------------------
    allowed: frozenset[str] | None = None
    if ctx.is_wholesale():
        spec = applicability_spec.get("package_type_rules", {}) or {}
        only = spec.get("wholesale_requires_only")
        if only:
            allowed = frozenset(only)

    # -- commodity carve-outs, Rule 6(1) provisos ---------------------------
    carveouts = applicability_spec.get("commodity_carveouts", {}) or {}
    waived: set[str] = set()
    if ctx.category in (carveouts.get("no_date_required") or []):
        waived.add("mfg_date")
    if ctx.category in (carveouts.get("no_mrp_required") or []):
        waived.add("mrp")

    # -- gate 6: other law, Rule 7(4) ---------------------------------------
    disapplied = bool(ctx.other_law_mandates)

    return Applicability(
        in_scope=True,
        allowed_fields=allowed,
        waived_fields=frozenset(waived),
        height_rules_disapplied=disapplied,
    )


__all__ = ["Applicability", "evaluate_applicability"]
