"""`conditional_present` — required only when another fact holds.

Rule 6(1)(a): an imported package must declare the name and address of the
importer. Also carries the section 13b extensions (Rule 9(2), Rule 9(3),
Rule 31(1)-(2)).

Two condition forms are supported, plus one override:
    when: {field: country_of_origin, present: true} -> another declaration exists
    when: {context: outer_wrapper_transparent, equals: false}
    also_when_context: is_imported                  -> force the condition true

The override exists because a label can be silent about a fact the officer
knows. An imported pack may declare no country of origin at all -- that is
itself unremarkable, since nothing in the 2011 rules requires one on the pack --
and the importer is still mandatory. Naming the context flag in the rulepack
keeps the check generic; an earlier version hardcoded the field name `importer`
here, which meant reversing the rule's direction silently changed the check's
behaviour too.
"""

from __future__ import annotations

from contracts import DeclarationSet, PackageContext
from rules.checks._common import (
    category_blocks,
    declarations_for,
    field_text,
    locate,
    reading_supports_an_absence,
    source_blocks,
)
from rules.models import CheckOutcome, Rule, Rulepack


def check(rule: Rule, ds: DeclarationSet, ctx: PackageContext, pack: Rulepack) -> CheckOutcome:
    for blocker in (category_blocks(rule, ctx), source_blocks(rule, ds)):
        if blocker is not None:
            return CheckOutcome.not_applicable(blocker)

    when = rule.opt("when") or {}
    triggered: bool | None = None
    excluded_by: str | None = None

    if "field" in when:
        others = declarations_for(ds, (when["field"],))
        triggered = bool(others) == bool(when.get("present", True))

        # A declaration can be present and still not raise the condition.
        #
        # `LMPC.IMPORTER.PRESENT` triggered on *any* country of origin, so
        # `PRODUCT OF INDIA` and `Made in India` -- printed by four of the seven
        # packs it accused -- were read as evidence that the package was
        # imported, and a high-severity finding was raised against an Indian
        # manufacturer for not naming an importer. Declaring where a thing was
        # made is not a declaration that it was brought in.
        exclude = when.get("text_excludes_ref")
        if triggered and exclude:
            counter_pattern = pack.pattern(exclude)
            if counter_pattern is not None and counter_pattern.matches(
                " ".join(d.text for d in others)
            ):
                # Untriggered, not decided. `also_when_context` below still has
                # to be able to override it: a pack can be imported and print a
                # domestic-looking origin, and the officer standing in front of
                # it knows more than the label does. Returning here instead
                # made the flag unreachable.
                triggered = False
                excluded_by = (
                    f"{rule.rule_ref} is conditioned on an imported package; "
                    f"the declared origin is not one."
                )

    elif "context" in when:
        attr = getattr(ctx, when["context"], None)
        if attr is None:
            return CheckOutcome.no_data(f"Package context does not record '{when['context']}'.")
        triggered = attr == when.get("equals", True)

    # A context flag may force the condition true even when the label is silent.
    override = rule.opt("also_when_context")
    if override and getattr(ctx, override, False):
        triggered = True

    if triggered is None:
        return CheckOutcome.no_data("The condition for this rule could not be evaluated.")

    if rule.opt("negate"):
        triggered = not triggered

    if not triggered:
        return CheckOutcome.not_applicable(
            excluded_by or "The condition for this rule does not arise."
        )

    fields = rule.target_fields()
    primary = fields[0] if fields else None

    found = locate(rule, pack, ds)
    if found is None:
        found = bool(declarations_for(ds, fields))

    if found:
        return CheckOutcome(
            status="PASS",
            found=field_text(ds, fields)[:120] or None,
            expected="declared",
            field_name=primary,
        )
    # The other of the two checks that may report an absence, and it carries the
    # same guard for the same reason. See `reading_supports_an_absence`.
    if (why := reading_supports_an_absence(ds, pack)) is not None:
        return CheckOutcome.no_data(why)
    return CheckOutcome(
        status="FAIL",
        found=None,
        expected=f"{(primary or 'declaration').replace('_', ' ')} declared",
        field_name=primary,
    )
