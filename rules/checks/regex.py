r"""`regex` — does the declaration match the form the gazette prescribes?

The single most dangerous failure this system can produce is reporting
"MRP not declared" on a pack where the MRP is printed clearly.

It nearly happened. The MRP pattern originally required `\d+(\.\d{1,2})?` for
the amount, which matches `45.00` but NOT `1,250.00`, `1,199.00` or
`2,50,000.00`. Every product priced at Rs 1,000 or above -- cosmetics,
footwear, electronics, cement, appliances -- would have been reported as having
no MRP at all, at severity `high`, on a perfectly compliant pack.

The bug was not the regex. The bug was using one pattern for two jobs.

So: locate first with a permissive pattern. If the declaration is not on the
pack, say nothing and let `on_locate_fail` report the absence. Only once we
know the declaration exists do we judge how it is written.

**Two further corrections, both measured on the field corpus 2026-09-10, where
format checks were the single largest source of FAIL: 13 `MRP.FORMAT` and 12
`DATE.FORMAT` across 52 frames.**

*Locate and validate must read the same evidence.* `locate` searches the whole
label (`searchable_text`); `strict_text` searches only the lines the classifier
put in this field, and falls back to the label ONLY when that field is empty.
So a declaration split across two detected regions -- the label in this field,
the value classified `other` -- was located on the label and then judged on the
fragment. Three corpus frames were failed for a malformed date while the date
itself sat in the label text we had already read:

    judged 'MFD*'              date on the label '06/2026'
    judged 'Mfd.& Aktd. by:'   date on the label '05-2026'
    judged 'Mfg. Month & Year' date on the label '09/2025'

That is a false accusation manufactured by our own segmentation, so the strict
pattern is now retried against the same text `locate` succeeded on before any
FAIL is returned.

*And a format verdict cannot be an accusation when the text came from OCR.*
A format rule asks how something is PRINTED -- case, spacing, separators,
ordering. Those are exactly the properties a recogniser does not preserve: the
same corpus read `Serving size` as `'Servingsize'`, `For C.A. No.` as
`'ForCA. No.'`, `MFG. BY PERFETTI VAN MELLE INDIA PVT LTD` as
`'MFG.BYPERFETI VAN MFIEINDIAPVTITDBTMT'`. Every one of those would be a
"not written in the prescribed form" finding against a compliant pack.

Per-declaration OCR confidence was tested as a gate and does not separate the
two populations -- format FAILs ran to a median of 0.84 and a maximum of 1.00,
format PASSes down to 0.75 -- which is the same result the noise frame gave for
CTC confidence, and a threshold drawn through that overlap would be a fudge.

So on a channel whose text we recognised ourselves, a format mismatch is
REVIEW: real, visible, listed with the text we read, routed to a human, amber
rather than red. It is not hidden and it is not compliant. On `listing_text`
there is no recogniser between us and the characters, so a mismatch there is
still a FAIL -- which is the wall in section 8 paying for itself.
"""

from __future__ import annotations

from contracts import DeclarationSet, FieldName, PackageContext
from rules.checks._common import (
    category_blocks,
    condition_blocks,
    field_text,
    locate,
    searchable_text,
    source_blocks,
    strict_text,
)
from rules.models import CheckOutcome, Rule, Rulepack


def _quotable(
    rule: Rule,
    pack: Rulepack,
    ds: DeclarationSet,
    fields: tuple[FieldName, ...],
    text: str,
) -> str:
    """What to put in `found` -- the declaration, never a slice of the label.

    `strict_text` falls back to the whole label when the classifier produced no
    line for the field, and `text[:120]` then quoted the first 120 characters
    of the pack. A Mattel carton's MRP finding read::

        found: '2-10\n7+\nFSC\nMX\nFSC* C161542\nBAVTRCKP\nor\nMC\n684173-A ...'

    which names nothing an officer could check and is not the declaration the
    finding is about. When we are on that fallback, the declaration's location
    is known -- `locate` just succeeded on this text -- so the finding quotes
    the neighbourhood of the label instead.
    """
    if field_text(ds, fields).strip():
        return text[:120]

    pattern = pack.pattern(rule.opt("locate_ref"))
    if pattern is not None:
        for compiled in pattern.by_script.values():
            match = compiled.search(text)
            if match is not None:
                start = max(0, match.start() - 8)
                return text[start : start + 120].strip()
    return text[:120]


def check(rule: Rule, ds: DeclarationSet, ctx: PackageContext, pack: Rulepack) -> CheckOutcome:
    for blocker in (
        category_blocks(rule, ctx),
        source_blocks(rule, ds),
        condition_blocks(rule, ctx),
    ):
        if blocker is not None:
            return CheckOutcome.not_applicable(blocker)

    fields = rule.target_fields()
    primary = fields[0] if fields else None

    # Step 1 -- LOCATE. Permissive. A miss here would be a false NOT_FOUND.
    if locate(rule, pack, ds) is False:
        return CheckOutcome.not_applicable(
            f"Declaration not located on the package; absence is reported by "
            f"{rule.on_locate_fail}, not by this rule."
        )

    # Step 2 -- VALIDATE. Strict. A miss here is a FORMAT finding, which is
    # real but much milder than a missing declaration.
    pattern = pack.pattern(rule.opt("pattern_ref"))
    if pattern is None:
        return CheckOutcome.no_data("Rule defines no validation pattern.")

    text = strict_text(ds, fields)
    if not text.strip():
        return CheckOutcome.no_data("No text was read for this field.")

    match = pattern.search(text)
    if match is not None:
        return CheckOutcome(
            status="PASS",
            found=match.group(0)[:120],
            expected=f"the form prescribed by {rule.rule_ref}",
            field_name=primary,
        )

    # The declaration may have been split across regions by our own detector,
    # leaving the value in a line the classifier called `other`. Ask the same
    # question of the same text `locate` was allowed to see, before saying the
    # manufacturer printed it wrongly. See the module docstring.
    whole = searchable_text(ds, fields)
    elsewhere = pattern.search(whole) if whole.strip() and whole != text else None
    if elsewhere is not None:
        return CheckOutcome(
            status="PASS",
            found=elsewhere.group(0)[:120],
            expected=f"the form prescribed by {rule.rule_ref}",
            detail=(
                "Matched on the label rather than on the classified declaration: "
                "the declaration was read across more than one region."
            ),
            field_name=primary,
        )

    # Not in the prescribed form anywhere we read. Whether that is the
    # printer's doing or our recogniser's is a question OCR cannot answer, so
    # on a channel we recognised ourselves this is REVIEW. See the docstring.
    return CheckOutcome(
        status="FAIL" if not ds.has_pixels() else "REVIEW",
        found=_quotable(rule, pack, ds, fields, text),
        expected=f"the form prescribed by {rule.rule_ref}",
        detail=(
            "The declaration is present but is not written in the prescribed form."
            if not ds.has_pixels()
            else "The declaration is present, but what we read of it is not in the "
            "prescribed form. Case, spacing and punctuation are not reliably "
            "recovered from a photograph, so this is referred for review rather "
            "than reported as a violation."
        ),
        field_name=primary,
    )
