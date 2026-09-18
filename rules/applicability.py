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
from datetime import UTC, datetime
from typing import Any

from contracts import DeclarationSet, FieldName, PackageContext
from rules import checks
from rules.models import Rulepack
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


# ---------------------------------------------------------------------------
# B5 — what is worth reading, decided before anything is read.


_NOTHING_READ_YET = DeclarationSet(source="photo", captured_at=datetime.min.replace(tzinfo=UTC))
"""The label as it stands before OCR: no declarations, no geometry.

A sentinel, not a record. It exists so `plan_evidence` can run the *same*
`evaluate_applicability` the engine runs rather than a second pre-OCR copy of
the gate that could drift out of step with the first, and the gate reads exactly
one thing from it — `ds.first("net_quantity")`, which is correctly absent.

`source` and `captured_at` are required by the contract and are never read here;
the timestamp is a fixed sentinel rather than `now()` so that this module stays
pure and two calls a millisecond apart cannot differ. This object never leaves
the function and is never written to a record.
"""


@dataclass(frozen=True, slots=True)
class EvidencePlan:
    """What this package's rules will actually ask for. AKSHAR.md section 5, B5.

    The pipeline's default is to read everything on the label and then let the
    engine decide what mattered. For two kinds of package that is wasted work,
    and one of them is wasted work with a wrong answer at the end of it:

      - **Rule 24, wholesale.** A wholesale carton must declare three things,
        not six. Reading it for six and evaluating all six manufactures four
        violations on every scan, which is the failure mode section 13 opens
        with.
      - **Rule 26, exempt.** A package outside the scope of these rules has no
        declaration duty at all, so the full pipeline — detect, rectify,
        segment, OCR, classify — produces evidence for a question nobody is
        entitled to ask.

    `need` is derived from the loaded rulepack, never restated here. A rule
    added to the pack tomorrow asks for its own evidence without this file being
    touched; a list written out by hand would silently stop requesting it, and
    the symptom would be a NO_DATA on a rule that used to work.

    ---------------------------------------------------------------------------
    **`need` IS NOT A LICENCE TO SKIP OCR.**

    It says which *classified fields* some rule will ask for. It does not say
    which text may go unread, and the two are not the same thing: `present`
    checks find a declaration with `locate()`, which searches the label's text
    rather than the classifier's output. `LMPC.MFR.PRESENT` targets the single
    field `manufacturer` and finds it through a pattern that also matches
    `Packed by` and `Marketed by` — which is why no rule in the pack targets
    `packer` at all, and why dropping `packer` from a field list would not show
    up here but would show up as a manufacturer nobody could find.

    So the safe uses are: stop entirely when `out_of_scope` is set; skip *scale*
    work when `need_geometry` is empty; skip panel segmentation when
    `need_pdp_polygon` is false; and order the classifier's work by `need`.
    Narrowing the text extraction itself is not one of them.
    """

    need: frozenset[FieldName]
    """Fields some enabled, applicable rule will read. Empty means: nothing on
    this label is being judged."""

    need_geometry: frozenset[FieldName]
    """The subset of `need` whose *character height* is measured, not just its
    text. These are the fields that make a marker card or a ruler worth having;
    if this is empty the scan does not need scale at all."""

    need_pdp_polygon: bool
    """Whether any surviving rule needs the principal display panel segmented."""

    must_declare: frozenset[str] | None = None
    """Rule 24: the fields whose *absence* is itself a violation, when the pack
    narrows them. `None` means the ordinary Rule 6(1) set applies.

    Distinct from `need`, and the distinction is the whole of Rule 24. A
    wholesale carton `must_declare` three things — but `need` still contains
    `mrp`, because `LMPC.CHAR.WIDTH_RATIO` and `LMPC.CONTRAST.NUMERALS` govern
    an MRP *if one is printed*, and a carton is not licensed to print an
    unreadable price merely because it was not obliged to print one at all.
    Requiring a declaration and reading a declaration are different questions;
    conflating them is how a wholesale scan grows four false violations."""

    out_of_scope: Applicability | None = None
    """Non-None when the gate could decide *without reading the label*. The
    caller should stop and emit NOT_APPLICABLE for every rule, quoting
    `.reason`.

    It is None far more often than the exemption is absent, and the difference
    matters. Rule 26(a) exempts a 10 g sachet — but the quantity is normally
    printed on the pack, which is precisely what has not been read yet. The gate
    can only end a scan early when the quantity arrived from somewhere other
    than the pixels: a listing's structured field, or an officer who typed it.
    Otherwise the honest answer is "read it and we will see", and this stays
    None. **Guessing the other way would clear a package by assuming a fact
    about it**, which is the one error this project treats as worse than missing
    a violation.
    """


def plan_evidence(
    ctx: PackageContext,
    pack: Rulepack,
    *,
    include_extensions: bool = True,
) -> EvidencePlan:
    """Decide what to look for, before looking. Pure; no I/O and no pixels.

    Runs the *same* gate the engine runs, against an empty `DeclarationSet` —
    rather than a second, pre-OCR copy of the rules that could drift out of step
    with the first. That works because every gate clause declines on a missing
    quantity: `compare_to_limit` returns None rather than a verdict when there
    is nothing to compare, so an unknown quantity can never exempt a package.
    """
    gate = evaluate_applicability(_NOTHING_READ_YET, ctx, pack.applicability)
    if not gate.in_scope:
        return EvidencePlan(
            need=frozenset(),
            need_geometry=frozenset(),
            need_pdp_polygon=False,
            out_of_scope=gate,
        )

    need: set[FieldName] = set()
    need_geometry: set[FieldName] = set()
    need_pdp = False

    for rule in pack.all_rules(include_extensions):
        if not rule.enabled:
            continue
        targets = rule.target_fields()
        if gate.blocks(targets) is not None:
            continue

        need.update(targets)

        # A rule may read a field it does not target — a cross-check naming two
        # declarations targets one of them. `requires` is where it says so.
        for requirement in rule.requires:
            if requirement.startswith("declarations."):
                need.add(requirement.split(".", 1)[1])  # type: ignore[arg-type]
            elif requirement == "geometry.pdp_polygon":
                need_pdp = True

        if rule.check in checks.REQUIRES_MILLIMETRES:
            need_geometry.update(targets)

    return EvidencePlan(
        need=frozenset(need),
        need_geometry=frozenset(need_geometry),
        need_pdp_polygon=need_pdp,
        must_declare=gate.allowed_fields,
        out_of_scope=None,
    )


__all__ = ["Applicability", "EvidencePlan", "evaluate_applicability", "plan_evidence"]
