"""`present` — Rule 6(1) mandatory declarations, Rule 6(2) consumer care.

One of only two checks permitted to report that a declaration is MISSING.
Every format rule defers here through `on_locate_fail`, so a question about how
a declaration is written can never escalate into an accusation that it is
absent. That escalation would be a false accusation against a manufacturer,
and one instance of it in front of a judge ends the demo.

**And the same is true of a declaration we simply failed to read.** That was not
guarded, and on 2026-09-09 it produced six such accusations against one pack in a
single scan. `reading_supports_an_absence` is the guard: at L3 the reading is
known to be partial, and section 5 confines that tier to *"verdicts on what was
read"*. A missing declaration is a verdict on what was not.
"""

from __future__ import annotations

from contracts import DeclarationSet, PackageContext
from rules.checks._common import (
    category_blocks,
    declarations_for,
    field_text,
    locate,
    reading_supports_an_absence,
    searchable_text,
)
from rules.models import CheckOutcome, Rule, Rulepack


def check(rule: Rule, ds: DeclarationSet, ctx: PackageContext, pack: Rulepack) -> CheckOutcome:
    if (blocked := category_blocks(rule, ctx)) is not None:
        return CheckOutcome.not_applicable(blocked)

    fields = rule.target_fields()
    primary = fields[0] if fields else None

    found = locate(rule, pack, ds)
    if found is None:
        # No locate pattern defined; fall back to the classifier's opinion.
        found = bool(declarations_for(ds, fields))

    if not found:
        # Section 5, L3: verdicts cover what was read. An absence from a label
        # we could not read is our failure, not the manufacturer's.
        if (why := reading_supports_an_absence(ds, pack)) is not None:
            return CheckOutcome.no_data(why)

        # One of Rule 6(1)'s declarations is habitually printed with no label
        # on it, and we can only find a declaration by its label.
        #
        # Rule 6(1)(b) requires the common or generic name of the commodity; it
        # does not require the word "Commodity" anywhere. A besan pack prints
        # `Chana Besan`, a battery card prints `AA 1015 R6P BATTERIES`, a
        # namkeen prints `Crunchy Spicy Potato Noodles` -- the generic name in
        # substance, in display type, with no caption. Nothing available here
        # separates an uncaptioned generic name from marketing copy, so
        # "not declared" is a verdict about our own vocabulary rather than
        # about the pack, and section 5 does not allow it. Referred instead,
        # with the reason on it, so an officer decides what an officer can see
        # at a glance.
        #
        # Only where a caption is genuinely optional, and only on a channel we
        # had to read ourselves: on `listing_text` the field is either in the
        # listing or it is not.
        if rule.opt("uncaptioned_form_is_lawful") and ds.has_pixels():
            return CheckOutcome(
                status="REVIEW",
                found=None,
                expected=f"{(primary or 'declaration').replace('_', ' ')} declared on the package",
                detail=(
                    f"No labelled {(primary or 'declaration').replace('_', ' ')} was found. "
                    f"{rule.rule_ref} does not require this declaration to carry a caption, "
                    f"and an uncaptioned one cannot be told apart from marketing copy here, "
                    f"so it is referred for review rather than reported as a violation."
                ),
                field_name=primary,
            )

        return CheckOutcome(
            status="FAIL",
            found=None,
            expected=f"{(primary or 'declaration').replace('_', ' ')} declared on the package",
            field_name=primary,
        )

    # Rule 6(2): consumer care must declare name, address AND telephone.
    # A name-and-address-only check would pass packs that fail.
    required = rule.opt("requires_subfields") or []
    if "telephone" in required:
        phone = pack.pattern(rule.opt("phone_ref"))
        if phone is not None and not phone.matches(searchable_text(ds, fields)):
            return CheckOutcome(
                status="FAIL",
                found=field_text(ds, fields)[:120] or None,
                expected="name, address and telephone number",
                detail="Rule 6(2) makes the telephone number mandatory; e-mail only if available.",
                field_name=primary,
            )

    return CheckOutcome(
        status="PASS",
        found=field_text(ds, fields)[:120] or None,
        expected="declared",
        field_name=primary,
    )
