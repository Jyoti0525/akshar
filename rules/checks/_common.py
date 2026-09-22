"""Helpers shared by the thirteen checks.

Nothing here decides anything; it only answers "what text belongs to this
field" and "did the permissive locate pattern find the declaration at all".
The locate/validate split lives here because it is the single most
consequential piece of logic in the rules layer.
"""

from __future__ import annotations

import re

from contracts import Declaration, DeclarationSet, FieldName, PackageContext
from rules.models import Pattern, Rule, Rulepack


def declarations_for(ds: DeclarationSet, fields: tuple[FieldName, ...]) -> list[Declaration]:
    """Everything read into these fields, from every photograph.

    This is the LOOKING function, and presence checks want exactly this: the
    whole point of photographing a pack from three sides is that the MRP found
    in the third one is found. Checks that MEASURE want `measured_for` below.
    """
    return [d for d in ds.declarations if d.field in fields]


_SCALE_RANK = {"A": 0, "B": 1, "C": 2}
"""A marker of known size beats a stored label dimension beats no scale at all."""


def measured_for(ds: DeclarationSet, fields: tuple[FieldName, ...]) -> list[Declaration]:
    """The declarations a check may MEASURE — one photograph per field.

    ---------------------------------------------------------------------------
    WHY THIS EXISTS
    ---------------------------------------------------------------------------
    A multi-frame scan hands the engine the same printed declaration more than
    once: the officer walked round the pack and the net quantity was legible
    from two of the angles. Every measurement check in this package iterates its
    declarations and keeps the WORST outcome — which is right on one photograph
    and badly wrong across several, because it means **an officer who takes more
    care makes the pack look worse.** Three shots give three chances for one
    poor crop, one soft focus or one scale that came out 8% short to produce a
    FAIL, and none of those is a fact about the package.

    So a measurement is taken from one photograph per field: the best-calibrated
    one, then the most confidently classified, then the earliest. A laboratory
    measures once with its best instrument; it does not measure five times and
    report the frightening number.

    **What this gives up, stated plainly.** A pack that declares the same field
    on two panels, one of them non-compliant, is judged on one of them. The
    alternative fabricates violations on compliant packs, and between a check
    that under-reports a duplicate declaration and one that convicts a lawful
    pack for being photographed twice, only the first is survivable in front of
    a manufacturer.

    A single-frame set short-circuits and is returned untouched, so nothing that
    existed before multi-frame capture can behave differently.
    """
    found = declarations_for(ds, fields)
    if not found or not ds.is_union():
        return found

    best: dict[FieldName, tuple[tuple[float, float, int], int]] = {}
    for d in found:
        rank = (
            float(_SCALE_RANK.get(d.scale_tier or "C", 3)),
            -d.field_confidence,
            d.frame_id,
        )
        current = best.get(d.field)
        if current is None or rank < current[0]:
            best[d.field] = (rank, d.frame_id)

    chosen = {field: frame for field, (_, frame) in best.items()}
    return [d for d in found if d.frame_id == chosen[d.field]]


def field_text(ds: DeclarationSet, fields: tuple[FieldName, ...]) -> str:
    """All text classified into these fields, joined."""
    return " ".join(d.text for d in declarations_for(ds, fields))


def searchable_text(ds: DeclarationSet, fields: tuple[FieldName, ...]) -> str:
    """Field text plus the raw label text.

    A locate pattern must see everything. If the classifier put the MRP in
    `other`, the declaration is still on the pack and reporting it missing
    would be a false accusation against the manufacturer.
    """
    parts = [field_text(ds, fields)]
    if ds.raw_text:
        parts.append(ds.raw_text)
    return " ".join(p for p in parts if p).strip()


def strict_text(ds: DeclarationSet, fields: tuple[FieldName, ...]) -> str:
    """Text to VALIDATE against.

    Falls back to the raw text only when the classifier produced nothing for
    the field, so a strict format check still has something to judge.
    """
    text = field_text(ds, fields)
    return text if text else (ds.raw_text or "")


ILLEGIBLE_TIERS = frozenset({"L3", "L4"})
"""Tiers at which the label was not read well enough to allege an absence.

Section 5 defines L3 as *"OCR partly failed - coverage % reported; verdicts on
what was read"*. "The MRP is not declared" is not a verdict on what was read. It
is a verdict on what was **not** read, which is precisely the inference L3 says
we are not entitled to make.

L4 issues no verdicts at all, so it never reaches here; it is in the set because
a caller that ever does reach here with L4 should get the same answer.
"""


def _mandatory_fields(pack: Rulepack) -> set[FieldName]:
    """The declarations the pack requires on every package, from the pack itself.

    Read out of the rulepack rather than listed here, so the denominator below
    cannot drift from the rules being evaluated. Today it is Rule 6(1)'s six:
    mrp, net_quantity, mfg_date, manufacturer, generic_name, consumer_care.

    `conditional_present` rules are excluded on purpose. `importer` is required
    only of an imported package, so counting it would make every domestic pack
    look like a label we had half failed to read.
    """
    return {
        field
        for rule in pack.rules
        if rule.enabled and rule.check == "present"
        for field in rule.target_fields()
    }


def reading_supports_an_absence(
    ds: DeclarationSet, pack: Rulepack | None = None
) -> str | None:
    """None if we may report a declaration missing; otherwise why we may not.

    ---------------------------------------------------------------------------
    THE FALSE ACCUSATION THIS PREVENTS
    ---------------------------------------------------------------------------
    On 2026-09-09 a photograph of an ITC Dark Fantasy pack produced six
    high-severity FAILs -- no MRP, no net quantity, no manufacturer, no generic
    name, no date of packing, no consumer care -- against a pack that visibly
    declares every one of them. The recogniser had returned `'METAWEIHT: 2429'`
    for `NET WEIGHT: 242 g`, `'MARKETED BY T'`, `'wYVNOvr 9I'`, `'DCLA'`,
    `'A EA'`. Nothing was missing from the pack. The label had not been read.

    ---------------------------------------------------------------------------
    WHY THE TEST IS "HOW MANY DECLARATIONS DID WE FIND"
    ---------------------------------------------------------------------------
    Three cheaper signals were measured first, over fourteen frames, and all
    three failed:

    * **`coverage`** is the share of proposed regions the recogniser was *run
      on*, and we run it on nearly everything we propose. One frame of pure
      noise scored 1.00.
    * **Recogniser confidence** is worse than useless here: CTC scored that same
      noise frame at 0.995 median. It is confidently wrong.
    * **Word shape** -- the share of read lines carrying a letter run -- scored
      0.51 to 0.89 across good frames and bad alike, because a garbled line
      still contains three-letter fragments.

    What does separate them is the thing the check is actually about. A retail
    package carries all six of Rule 6(1)'s declarations; that is what makes them
    mandatory. So if we located **fewer than half** of them, the reading failed,
    and every one of those absences is ours rather than the manufacturer's. If
    we located most of them and one is genuinely missing, that is a finding, and
    it still fires.

    Half is a round number and it is stated rather than fitted: `data/test_split/`
    is sealed, and a threshold chosen to make a particular photograph pass is
    the exact fitting that seal exists to prevent.

    ---------------------------------------------------------------------------
    WHAT THIS DOES NOT WEAKEN
    ---------------------------------------------------------------------------
    Nothing positive. A declaration that was read and is wrongly formatted still
    fails its format rule; a height still fails its height rule; a promotional
    graphic still is not an MRP. Only the inference *from silence* is withdrawn,
    and only while the silence is ours.
    """
    if ds.degradation_tier in ILLEGIBLE_TIERS:
        return (
            f"The label was only partly read ({ds.degradation_tier}), so the absence of this "
            f"declaration from the text we recovered is not evidence that it is absent from "
            f"the package. Photograph the declaration panel again, filling the frame."
        )

    if pack is not None:
        mandatory = _mandatory_fields(pack)
        if mandatory:
            located = {d.field for d in ds.declarations} & mandatory
            # STRICTLY fewer than half. This was briefly `<=` on 2026-09-10, to
            # stop a compliant Britannia Bourbon being failed for a manufacturer
            # and a consumer care it declares but that we did not read.
            #
            # That was the wrong repair and it is reverted. Widening the guard
            # does not make the pipeline read the label; it makes the pipeline
            # stop reporting on labels it did not read, and it buys the
            # compliant pack's acquittal with the silence it also grants to a
            # pack that genuinely declares nothing. An enforcement tool that
            # says less when it sees less is not more careful, it is less
            # useful — and the honest fix for "we did not read the
            # manufacturer" is to read the manufacturer.
            #
            # See RESULTS.md, "Where the declarations were going". The cause was
            # never the threshold: it was that most of the panel was classified
            # `other` and never reached a rule at all.
            if len(located) * 2 < len(mandatory):
                return (
                    f"Only {len(located)} of the {len(mandatory)} mandatory declarations could "
                    f"be identified on this label, so it was not read well enough to say that "
                    f"any of the others is missing. Photograph the declaration panel again, "
                    f"filling the frame, with the marker card flat beside it."
                )
    return None


MIN_MENDABLE_WORD = 5
"""Shortest label word a single character may be forgiven in.

`mrp`, `net` and `qty` are left alone: at three characters, one edit reaches
`mrs`, `map`, `nut` and `sty`, and a locate pattern that loose would find a
declaration on a pack that makes none. At five characters and above the
neighbourhood is sparse enough that a near-miss is overwhelmingly our
recogniser rather than a coincidence.
"""


def _pattern_vocabulary(pattern: Pattern) -> frozenset[str]:
    """The words a locate pattern spells out, with the regex syntax removed.

    Derived from the pattern rather than listed beside it, because a second
    copy of "what an MRP label looks like" is exactly the divergence this
    codebase has already paid for once.
    """
    words: set[str] = set()
    for compiled in pattern.by_script.values():
        bare = re.sub(r"\\[sdwbSDWB]|\\.|[\[\](){}?*+^$|]|\d+,?\d*", " ", compiled.pattern)
        bare = bare.replace("(?i)", " ")
        words |= {w.lower() for w in re.findall(rf"[A-Za-z]{{{MIN_MENDABLE_WORD},}}", bare)}
    return frozenset(words)


def _within_one_edit(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) <= 1
    short, long = (a, b) if len(a) < len(b) else (b, a)
    return any(long[:i] + long[i + 1 :] == short for i in range(len(long)))


def mend_label_noise(text: str, pattern: Pattern) -> str:
    """Repair words the recogniser dropped or added a character in.

    ---------------------------------------------------------------------------
    THE FALSE ACCUSATION THIS PREVENTS
    ---------------------------------------------------------------------------
    A Mattel carton prints `Maximum Retail Price: ₹ 149.00 (inclusive of all
    taxes)`. The recogniser read it, at 0.93 confidence, as::

        'Maximum Retai Price: {149.00'

    One `l`. `mrp_locate` spells `retail`, `Retai` is not `retail`, and Rule
    6(1)(e) was reported undeclared against a pack that declares its price in
    the largest type on the panel. The same single character cost
    `NET QOUANTITY 100g`, `CONSUME CARE`, `Maketed By:` -- one insertion and two
    deletions, each of them a mandatory declaration reported absent.

    ---------------------------------------------------------------------------
    WHY THIS AND NOT A WIDER PATTERN
    ---------------------------------------------------------------------------
    Widening the regex one observed misreading at a time is what produced the
    nine unmatched phrasings of 2026-09-10, and it cannot anticipate the next
    dropped character. Tolerating *one edit inside a word the pattern already
    spells* is a statement about the recogniser instead of about the language,
    and it is bounded: only whole words, only words of `MIN_MENDABLE_WORD`
    characters or more, only against the vocabulary of the pattern being run.

    ---------------------------------------------------------------------------
    WHERE IT DOES NOT APPLY
    ---------------------------------------------------------------------------
    Presence only, and pixels only. `listing_text` has no recogniser between us
    and the characters, so there is nothing to forgive and `locate` does not
    call this. Format rules do not call it either: a format finding is *about*
    the characters, and mending them first would be judging text we invented.

    Measured over 122 photographs: 8 declarations recovered, all of them
    mandatory and all of them genuinely printed on the pack.
    """
    vocabulary = _pattern_vocabulary(pattern)
    if not vocabulary:
        return text

    def mend(match: re.Match[str]) -> str:
        word = match.group(0)
        lowered = word.lower()
        if len(lowered) < MIN_MENDABLE_WORD or lowered in vocabulary:
            return word
        for candidate in vocabulary:
            if _within_one_edit(lowered, candidate):
                return candidate
        return word

    return re.sub(r"[A-Za-z]+", mend, text)


def locate(rule: Rule, pack: Rulepack, ds: DeclarationSet) -> bool | None:
    """Is the declaration present on the pack at all?

    Returns True/False when a locate pattern exists, and None when the rule
    does not define one (the caller then relies on classified declarations).

    Deliberately permissive. A miss here generates a false NOT_FOUND; a miss on
    the strict pattern only generates a much milder FORMAT finding.
    """
    pattern: Pattern | None = pack.pattern(rule.opt("locate_ref"))
    if pattern is None:
        return None
    fields = rule.target_fields()
    if declarations_for(ds, fields):
        return True

    text = searchable_text(ds, fields)
    if pattern.matches(text):
        return True

    # Nothing matched. Before reporting a declaration absent, allow the label
    # one mis-read character -- but only where a recogniser stood between us
    # and the print. See `mend_label_noise`.
    if ds.has_pixels():
        return pattern.matches(mend_label_noise(text, pattern))
    return False


def has_declaration(ds: DeclarationSet, fields: tuple[FieldName, ...]) -> bool:
    return bool(declarations_for(ds, fields))


def category_blocks(rule: Rule, ctx: PackageContext) -> str | None:
    """Per-rule category gates, over and above the global applicability gate."""
    skip = rule.opt("skip_if_category_in") or []
    if ctx.category in skip:
        return f"Commodity '{ctx.category}' is carved out of {rule.rule_ref}."

    unless = rule.opt("unless_category_in") or []
    if unless and ctx.category in unless:
        return f"Permitted for '{ctx.category}' under {rule.rule_ref}."

    only = rule.opt("only_if_category_in") or []
    if only and ctx.category not in only:
        return f"{rule.rule_ref} applies only to {', '.join(only)}."

    return None


def source_blocks(rule: Rule, ds: DeclarationSet) -> str | None:
    """Some rules only make sense on one input channel (e.g. Rule 31 on listings)."""
    only = rule.opt("only_if_source_in") or []
    if only and ds.source not in only:
        return f"{rule.rule_ref} applies only to the {', '.join(only)} channel."
    return None


def condition_blocks(rule: Rule, ctx: PackageContext) -> str | None:
    """`only_if:` clauses that read a package-context flag."""
    only_if = rule.opt("only_if") or {}
    for key, expected in only_if.items():
        actual = getattr(ctx, key, None)
        if actual != expected:
            return f"{rule.rule_ref} applies only when {key} is {expected}."
    return None


def bilingual_group(
    declarations: list[Declaration], mode: str | None
) -> list[list[Declaration]]:
    """Group declarations of one field so a bilingual pack is judged fairly.

    Rule 9(4): on a bilingual pack the same declaration appears twice, in two
    scripts, often at different sizes. The requirement is satisfied if EITHER
    instance meets it — so with `bilingual: max` we return one group per field
    and the check takes the best member, rather than flagging the smaller one.

    **Per field, and that word was doing nothing until 2026-09-22.** This
    returned a single group holding every declaration the rule had gathered,
    which is the same thing only while a rule names one field. Two of the three
    `min_height_mm` rules do; `LMPC.LETTER.MIN_HEIGHT` names four — manufacturer,
    consumer care, generic name and manufacturing date — and collapsing them let
    the tallest declaration on the pack excuse all the others. Rule 7(3) asks
    that every declaration's letters clear 1 mm, not that the biggest does.

    Measured over the 40 ruler frames, splitting them moves two: a consumer-care
    line at 0.90 mm that a 1.48 mm date had been covering becomes REVIEW, and a
    `Marketed By:` line at 0.54 mm becomes FAIL. It is deliberately still
    lenient *within* a field, because that is what Rule 9(4) grants — the same
    declaration set twice in two scripts, judged on the larger.
    """
    if not declarations:
        return []
    if mode == "max":
        grouped: dict[str, list[Declaration]] = {}
        for declaration in declarations:
            grouped.setdefault(declaration.field, []).append(declaration)
        return list(grouped.values())
    return [[d] for d in declarations]


__all__ = [
    "bilingual_group",
    "category_blocks",
    "condition_blocks",
    "declarations_for",
    "field_text",
    "has_declaration",
    "locate",
    "measured_for",
    "searchable_text",
    "source_blocks",
    "strict_text",
]
