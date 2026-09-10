"""M5, tier one — which declaration is this line?

    "Regex handles MRP, dates, net quantity, batch and country of origin in
     both scripts — these have strong lexical shape, and a pattern is more
     explainable than a model."                           -- section 14

    "Regex tier first, and measure before building the model. If patterns
     separate the fields adequately on the corpus, ship without a classifier —
     fewer parts, more explainable, nothing to overfit."   -- section 15b

**The locate patterns come from the rulepack, not from this file.** The
rulebook already defines, for every field, a permissive pattern whose only job
is *"is this declaration on the pack?"* — which is precisely the classification
question. Defining a second set here would mean the extractor and the rules
could disagree about what an MRP looks like, and that disagreement would
surface as a rule reporting a declaration missing while the report displays it.
One definition, in the gazette-cited file, used by both.

`rules/` is a pure layer with no OpenCV in it, so importing the loader here
does not breach the wall. The wall runs the other way: `rules/` must never
import `vision/`.

**The hard negatives are this file's own work, though.** They are extraction
concerns, not legal ones — the law has nothing to say about `Rs. 20 OFF`, and
the rulepack should not carry a pattern for it. Section 14 names six of them,
and each is handled below *before* the generic patterns get a chance, because
every one is designed to look exactly like the field it is not:

    Rs. 20 OFF                      price-shaped, but marketing
    Drained wt. 350 g               quantity-shaped, but not the net quantity
    24MRP07                         contains the literal string MRP
    Best before 9 months from mfg   date-shaped, not a date
    manufacturer vs consumer care   identical shape, different legal role
    barcode digits                  a long numeric string

`24MRP07` is the one worth remembering: *"a model that has never seen 24MRP07
will label it an MRP the first time it appears — possibly on stage."*
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from contracts import FieldName
from rules.loader import load_rulepack
from vision.types import OcrLine, Script


@dataclass(frozen=True, slots=True)
class FieldGuess:
    field: FieldName
    confidence: float
    reason: str
    """Which pattern fired, verbatim. Shown in the annotation tool and in the
    correction UI, so an officer disputing a label sees *why* it was assigned
    rather than a bare probability."""


# ---------------------------------------------------------------------------
# Hard negatives — section 14. Checked first, deliberately.
# ---------------------------------------------------------------------------

_PROMOTIONAL = re.compile(
    r"(?i)(\b\d+\s*%\s*(off|extra|free)\b"
    r"|\b(rs\.?|₹)\s*\d+\s*off\b"
    r"|\b(save|combo|offer|discount|buy\s*\d+\s*get)\b"
    r"|\bfree\s+(gift|inside|sample|pack|\d+\s*(mg|g|kg|ml|l)\b)"
    r"|\bextra\s+\d"
    # A COMPARISON is a claim about somebody else's price, never this pack's.
    # `'#As compared with Nabati Wafers 12g of MRP Rs.5'` is set in 5 pt at the
    # foot of a wafer pack; the classifier read the `MRP Rs.5` inside it, called
    # the line the price declaration, and Rule 9(1)(b) then failed the pack for
    # printing its MRP at 2.37:1 contrast — against marketing small print the
    # rule was never aimed at. The pack's own price was declared properly in the
    # table above it.
    #
    # `comp[ar]\w{0,4}` rather than `compared`, because the recogniser returned
    # `'#Ascompred with Nabati Wafers 12g of MRP Rs.5'` -- a dropped letter and a
    # lost space, in 5 pt type. Requiring `a` or `r` as the fifth character
    # admits `compared`, `compare`, `compred`, `comparison` and refuses
    # `comply with`, which appears on packs in `in compliance with`.
    # The second alternative carries the `as` because the recogniser also lost
    # the space -- `Ascompred` has no word boundary in front of `comp`.
    r"|\bcomp[ar]\w{0,4}\s*(with|to)\b"
    r"|\bas\s*comp[ar]\w{0,4}\s*(with|to)\b"
    r"|\bvs\.?\s|\bearlier\s*(price|mrp)\b|\bwas\s*(rs\.?|₹)\s*\d"
    r"|\bमुफ़्त\b|\bछूट\b)"
)
r"""`Rs. 20 OFF` is price-shaped and would otherwise satisfy any MRP amount
pattern. Attaching a promotional price to a legal notice as the maximum retail
price would be a serious and very visible error.

**`free` and `extra` are no longer promotional on their own**, and the word
that paid for it is `TOLL FREE`. Rule 6(2) makes a consumer-care contact
mandatory, and the overwhelmingly common way an Indian pack prints one is a
toll-free number -- so a bare `\bfree\b` sent `TOLL FREE 1800-103-1644` and
`TOLL FREE NO.1800 121 0511 OR E-MAIL` to `marketing_text`. This is a *hard
negative*, tested before any field pattern, so nothing downstream could recover
the declaration and the pack was reported as naming no consumer care at all.
The same word sits in `SUGAR FREE`, `GLUTEN FREE`, `GUILT FREE` and
`PRESERVATIVE FREE`; `extra` sits in `EXTRA VIRGIN`.

Promotion is now recognised by the forms that are actually promotional -- a
percentage, a `buy N get`, a free *thing*, `extra` before a number -- which
still catches `50% EXTRA FREE` and `BUY 1 GET 1 FREE` and leaves the helpline
alone."""

_DRAINED_OR_SECONDARY_WEIGHT = re.compile(
    r"(?i)\b(drained|dry|gross|approx\w*|serving|per\s*serve)\s*(wt|weight|qty|quantity)\b"
)
"""A can of chickpeas declares `Net wt. 500 g` and `Drained wt. 350 g`. Only
the first is the net quantity; judging the second against Rule 7(2) would flag
a compliant tin and would also select the wrong Table I height band."""

_BATCH_CODE = re.compile(r"(?i)\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{5,14}\b")
"""Alphanumeric run containing both digits and letters. `24MRP07` matches, and
because this is tested before the MRP pattern it never reaches it."""

_BATCH_LABEL = re.compile(r"(?i)\b(batch|b\.?\s*no|lot\s*(no)?|code)\b|बैच")

_DATE_OF_PHRASE = re.compile(
    r"(?i)(?<![A-Za-z0-9])("
    r"(date|month|year)s?\s*(and|&|/)?\s*(year|month)?\s*of\s*"
    r"(mfg|mfd|manufactur\w*|pack\w*|import\w*)"
    r"|(pack(ing|aging)|manufacturing|mfg|mfd)\s*date"
    r")(?![A-Za-z0-9])"
)
r"""`Date of Manufacture` names a DATE; `Manufactured by` names a PERSON.

`_PRIORITY` puts `manufacturer` above `mfg_date` for a good reason -- the
rulepack's `mfg_date_locate` contains `manufactur\w*`, so without that order
"Manufactured by: Acme Foods" classifies as a manufacturing date. But the same
order sent `Month & Year of Manufacture: 07/2026` to `manufacturer`, because
`manufacturer_locate` matches `Manufacture:`.

Ordering cannot settle both, because the deciding word falls *before* the
shared stem in one and *after* it in the other. So the "date of" framing is
recognised on its own, ahead of the priority list. It requires the literal
date/month/year lead-in, which leaves `Manufactured by` and `Imported by`
untouched."""

_MANUFACTURED_AND_PACKED = re.compile(
    r"(?i)(?<![A-Za-z0-9])manufactur\w*\s*(and|&|,|\+)?\s*pack\w*\s*(by|:)"
)
"""`Manufactured & Packed by` names one entity that is both.

`packer` sits above `manufacturer` in `_PRIORITY` so that `Packed by` is read
as a packer rather than as a packing date, and that ordering claimed this line
for `packer` too. Rule 6(1)(a) is satisfied by either, but the manufacturer is
the stronger claim and the one an officer expects to see named."""

_BARCODE = re.compile(r"\b\d{8}\b|\b\d{12,14}\b")
"""A bare run of 8 or 12-14 digits is an EAN/UPC, not a price and not a
quantity. Real prices have separators or decimals and are far shorter."""


# ---------------------------------------------------------------------------
# Field-specific patterns that the rulepack does not carry, because they are
# extraction concerns rather than legal tests.
# ---------------------------------------------------------------------------

_LOCAL_PATTERNS: dict[FieldName, tuple[str, ...]] = {
    "expiry_date": (
        # `UBD` is Use By Date and is printed as a bare initialism on a great
        # many Indian packs -- measured 2026-09-10, `'UBD: 13 APR 2027'`
        # classified as `other`. Anchored to a following separator and digit
        # so it cannot fire on the letters appearing inside a word.
        r"(?i)\b(best\s*(before|by)|use\s*by|expiry|exp\.?\s*date|consume\s*before)\b",
        r"(?i)\bu\.?b\.?d\.?\s*[:\-]?\s*\d",
        r"(सर्वोत्तम|उपयोग|समाप्ति)\s*(से\s*पहले|तिथि)",
    ),
    "country_of_origin": (
        # Two separate faults, both measured on real packs 2026-09-10.
        #
        # `made\s*in\b` required a word boundary the OCR often destroys:
        # `'MADEININDIA'` was read twice and matched nothing, because the spaces
        # the boundary anchored on were gone.
        #
        # Widening it to `made\s*in\s*[a-z]` then broke `'MADE IN INDIA'`, which
        # had worked: the single `[a-z]` consumed one letter and the trailing
        # `\b` landed *inside* the country name. `[a-z]+` takes the whole word,
        # so the boundary falls where a boundary exists.
        r"(?i)\b(country\s*of\s*origin|made\s*in\s*[a-z]+|product\s*of|origin)\b",
        r"(मूल\s*देश|निर्मित\s*में)",
    ),
    "mfg_date": (
        # Was checked ahead of the priority list; it is now one `mfg_date`
        # pattern among several and wins on position. See `classify_text`.
        _DATE_OF_PHRASE.pattern,
    ),
    "packer": (
        r"(?i)\bpacked\s*by\b",
        r"पैकर|पैक\s*किया",
    ),
    "batch": (
        r"(?i)\b(batch|b\.?\s*no\.?|lot\s*(no\.?)?|code)\s*[:\-]?\s*[A-Z0-9]",
        # The same label with its value in another detected region. `B.NO.:`
        # was read as a line of its own on a Keventer pack and classified
        # `other`, so Rule 6(1)(c) had nothing to attach to. Anchored to the
        # ends of the string so it fires only on a label standing alone; a line
        # that carries its value still goes through the stricter pattern above.
        r"(?i)^\s*(batch\s*(no\.?)?|b\.?\s*no\.?|lot\s*(no\.?)?)\s*[:\-]?\s*$",
        r"बैच",
    ),
}

_RULEPACK_LOCATE: dict[FieldName, str] = {
    "mrp": "mrp_locate",
    "net_quantity": "net_quantity_locate",
    "mfg_date": "mfg_date_locate",
    "consumer_care": "consumer_care_locate",
    "manufacturer": "manufacturer_locate",
    # Added when `LMPC.ORIGIN.IMPORTED` became `LMPC.IMPORTER.PRESENT`. The rule
    # now turns on whether an importer is declared, so the extractor and the
    # engine have to agree on what one looks like -- which is this delta's whole
    # point. Note it is NOT `manufacturer_locate`: that also matches
    # "Manufactured by", and reusing it would let a pack naming a manufacturer
    # and no importer satisfy an import check.
    "importer": "importer_locate",
    # Was a local copy reading `(common|generic)\s*name` while the pack
    # had grown `Name of Commodity`. The two definitions disagreed, which is
    # precisely what the module docstring says must not happen: the engine
    # reported the generic name present and the extractor classified the line
    # `other`, so the report showed no such declaration.
    "generic_name": "generic_name_locate",
}
"""Fields whose "is it on the pack?" pattern already lives in the rulepack."""

# Order is the resolution rule. Every entry earlier in this list wins against
# every entry later, so the specific beats the general: `Packed by` is a packer
# before `packed` can be read as a packing date, and `Imported by` is an
# importer before `manufacturer_locate` claims it.
_PRIORITY: tuple[FieldName, ...] = (
    "importer",
    "packer",
    "consumer_care",
    "expiry_date",
    "country_of_origin",
    "generic_name",
    "mrp",
    "net_quantity",
    # `batch` sits BELOW the two mandatory declarations. Packaging routinely
    # prints an MRP and a batch code on one line — `MRP Rs. 45.00 Batch
    # 24MRP07` — and with `batch` above them the batch pattern claimed the
    # line and the MRP vanished from the pack. A batch code is required by
    # Rule 6(1)(c) but is never the more significant thing on a line that also
    # carries a price or a quantity. A batch code standing ALONE is still
    # caught earlier, by `_hard_negative`, before the priority list is reached.
    "batch",
    # `manufacturer` MUST precede `mfg_date`. The rulepack's `mfg_date_locate`
    # is permissive and contains `manufactur\w*`, so with the other order
    # "Manufactured by: Acme Foods Pvt Ltd, Bhubaneswar" classifies as a
    # manufacturing DATE — the name and address of the manufacturer, which
    # Rule 6(1)(a) makes mandatory, silently reported as a date declaration.
    # `manufacturer_locate` requires a following "by" or ":", so
    # "Manufactured on 03/2026" still falls through to `mfg_date` correctly.
    "manufacturer",
    "mfg_date",
)


@lru_cache(maxsize=1)
def _patterns() -> dict[FieldName, tuple[re.Pattern[str], ...]]:
    """The rulepack's locate patterns, plus the local ones, already compiled.

    The rulepack stores one regex per script and always tries both, because a
    Hindi-only label is lawful. That property is inherited here rather than
    reimplemented: every script variant becomes its own entry, so a Devanagari
    line is classified by the Devanagari pattern without anyone having to
    decide in advance which language the pack is in.
    """
    pack = load_rulepack()
    compiled: dict[FieldName, list[re.Pattern[str]]] = {}

    for field, pattern_name in _RULEPACK_LOCATE.items():
        entry = pack.pattern(pattern_name)
        if entry is None:
            raise RuntimeError(
                f"rulepack has no pattern {pattern_name!r}; classification and the "
                f"rules engine would disagree about what a {field} looks like"
            )
        compiled.setdefault(field, []).extend(entry.by_script.values())

    for field, sources in _LOCAL_PATTERNS.items():
        compiled.setdefault(field, []).extend(re.compile(source) for source in sources)

    return {field: tuple(patterns) for field, patterns in compiled.items()}


def _declares_a_real_field(text: str) -> bool:
    """Does this line genuinely declare an MRP or a net quantity?

    Asked with the rulepack's own locate patterns, so "genuinely declares"
    means exactly what the rules engine means by it — see the module docstring
    on why there is only one definition of these.
    """
    patterns = _patterns()
    return any(
        pattern.search(text)
        for field in ("mrp", "net_quantity")
        for pattern in patterns.get(field, ())
    )


def _hard_negative(text: str) -> FieldGuess | None:
    """Catch the six look-alikes before any field pattern is tried."""
    if _PROMOTIONAL.search(text):
        return FieldGuess("marketing_text", 0.90, "promotional price or offer, not an MRP")

    if _DRAINED_OR_SECONDARY_WEIGHT.search(text):
        return FieldGuess("other", 0.85, "a secondary weight, not the net quantity declaration")

    stripped = text.strip()
    if _BARCODE.fullmatch(stripped.replace(" ", "")):
        return FieldGuess("other", 0.80, "a barcode-length digit run, not a price or quantity")

    # A batch code containing the literal string MRP.
    #
    # The guard uses the rulepack's own locate patterns rather than a
    # hand-written copy. An earlier version spelled out "maximum retail" but
    # not the abbreviation, so `MRP Rs. 45.00 Batch 24MRP07` — one line
    # carrying both — was classified as a batch code and the MRP disappeared
    # from the pack entirely. The rulepack patterns are word-bounded, so they
    # match a standalone `MRP` and correctly do *not* match the `MRP` buried
    # inside `24MRP07`, which is precisely the distinction needed here.
    candidate = _BATCH_CODE.search(stripped)
    if (
        candidate is not None
        and not _declares_a_real_field(stripped)
        and (_BATCH_LABEL.search(stripped) or "MRP" in candidate.group(0).upper())
    ):
        return FieldGuess(
            "batch",
            0.85,
            f"alphanumeric batch code {candidate.group(0)!r}; "
            f"the line declares no price or quantity of its own",
        )

    return None


def classify_text(text: str, *, script: Script = "latin") -> FieldGuess:
    """Assign a field to one line of text. Never raises; falls back to `other`."""
    if not text or not text.strip():
        return FieldGuess("other", 0.0, "empty")

    negative = _hard_negative(text)
    if negative is not None:
        return negative

    # `_DATE_OF_PHRASE` no longer short-circuits here; it is an `mfg_date`
    # pattern like any other and competes on where it matched. It was written
    # to beat `manufacturer`, and under leftmost resolution it does so exactly
    # when the "date of" lead-in comes first -- which is the only time it
    # should. Checked ahead of everything, it instead beat `consumer_care` on
    # a line whose subject was a complaints address.
    if _MANUFACTURED_AND_PACKED.search(text):
        return FieldGuess("manufacturer", 0.88, "manufactured and packed by one entity")

    patterns = _patterns()

    # Resolution is leftmost-match, with `_PRIORITY` only breaking a tie.
    #
    # `_PRIORITY` alone answered a different question than the one packaging
    # asks. A pack prints combined labels -- `BATCH No., MFD. & USE BY : SEE
    # BELOW`, `Batch No., Mfd. & Use By Date:` -- which declare three fields on
    # one line, and rank alone handed both to `expiry_date` because that entry
    # sits higher, so Rule 6(1)(c)'s batch number was reported undeclared on a
    # pack whose first printed word is BATCH. It also let a hint buried deep in
    # a sentence outrank the label the sentence opens with: `For Consumer
    # complaints, Write (indicating Batch No. and Mfg date)` is Rule 6(2)'s
    # consumer-care declaration, and it classified as a manufacturing date on
    # the strength of its last two words.
    #
    # Where a line is set, a declaration is introduced by its own label and the
    # label comes first. So position decides, and rank decides only when two
    # patterns start at the same character -- which is where every reason
    # written into `_PRIORITY` still applies untouched: `Packed by` is a packer
    # and not a packing date, `Imported by` is an importer and not a
    # manufacturer, both resolved at offset zero exactly as before.
    best: tuple[int, int] | None = None
    chosen: tuple[FieldName, str] | None = None
    for rank, field in enumerate(_PRIORITY):
        for pattern in patterns.get(field, ()):
            match = pattern.search(text)
            if match is None:
                continue
            key = (match.start(), rank)
            if best is None or key < best:
                best, chosen = key, (field, match.group(0))

    if chosen is not None:
        field, matched = chosen
        return FieldGuess(
            field,
            0.88,
            f"matched {field} locate pattern on {matched[:40]!r}",
        )

    return FieldGuess(
        "other",
        0.30,
        "no field pattern matched; an unlabelled address is resolved by the model tier",
    )


def classify_line(line: OcrLine) -> FieldGuess:
    guess = classify_text(line.text, script=line.script)
    # An uncertain reading cannot produce a certain label. Multiplying keeps a
    # half-read line from being asserted as a confidently identified MRP.
    return FieldGuess(
        guess.field,
        guess.confidence * max(line.confidence, 0.1),
        guess.reason,
    )


def is_address_like(text: str) -> bool:
    """Does this look like an address, and therefore need the model tier?

    Manufacturer, packer, importer and consumer care are all addresses. When
    one is *labelled* — `Manufactured by:` — regex settles it. When it is not,
    only position and context distinguish them, which is exactly and only what
    the 2M-parameter head is for.
    """
    signals = (
        re.search(r"(?i)\b(pvt|ltd|limited|llp|inc|industries|foods|company|co\.)\b", text),
        re.search(r"\b\d{6}\b", text),  # Indian PIN code
        re.search(r"(?i)\b(road|street|nagar|marg|dist|district|state|india)\b", text),
    )
    return sum(1 for signal in signals if signal) >= 2


__all__ = ["FieldGuess", "classify_line", "classify_text", "is_address_like"]
