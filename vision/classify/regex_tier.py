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
from vision.classify import shapes
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
    # `SPECIAL PRICE ₹99` is `docs/annotation-guide.md`'s own worked example of
    # a promotional graphic, and it matched nothing here until 2026-09-18 — it
    # landed on `other`, which is the label for text nobody could read. The
    # qualifier is what makes it promotional: a bare `PRICE` may introduce the
    # real declaration, and `special`, `sale`, `new` and `intro` do not.
    r"|\b(special|sale|new|intro(ductory)?)\s*price\b"
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
quantity. Real prices have separators or decimals and are far shorter.

**The gap between 8 and 12 is deliberate and stays open.** An Indian mobile
number is ten digits, and a consumer-care helpline printed bare is exactly the
sort of thing a widened rule would rename. Two of the five barcodes missed on
the 2026-09-18 annotated set have 10 and 11 digits and are still missed, which
is the right trade: calling a helpline a barcode would take a Rule 6(2)
declaration off the pack."""

_BARCODE_NOISE = re.compile(r'[\s"\'|।॥.\-]')
"""Marks OCR invents inside a barcode, and nothing else.

Whitespace was always stripped here. The rest are what the recogniser makes of
the bars and the guard patterns either side of an EAN — measured on real packs
as `"`, `|`, `।` and `॥`. Hyphens and full stops join them because a barcode is
sometimes printed with the country prefix set off.

Deliberately not `\\D`: stripping *every* non-digit would turn `Batch 24MRP07`
into `2407` and any alphanumeric code into a candidate."""


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
        # `(best|use)\s*(before|by)` rather than `best (before|by)|use by`: packs
        # print **Use Before** as often as Use By, and it matched nothing until
        # 2026-09-19 — the caption was read, named `other`, and Rule 6(1)(d)'s
        # date went unevaluated on a pack that declares it.
        r"(?i)\b((best|use)\s*(before|by)|expiry|exp\.?\s*date|consume\s*before)\b",
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
        # `Packed & Marketed By:` is one declaration naming one entity in two
        # roles, and it is what a great many Indian packs print instead of
        # `Packed by`. Without this it matched no packer pattern at all and fell
        # through to `mfg_date` — a Rule 6(1)(a) packer read as a date. Measured
        # on a Bangalore salt pack, 2026-09-19.
        #
        # `packer` and not `manufacturer`: Rule 6(1)(a) names three roles and the
        # pack is telling us which one it is. Where the same address also serves
        # as consumer care the pack says so separately, and rule 7 of the
        # annotation guide is explicit that these stay four fields.
        r"(?i)\bpacked\s*(&|and)\s*(marketed|mktd\.?)\s*by\b",
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

    # OCR reads the bars either side of an EAN as punctuation and drops it into
    # the middle of the number: measured 2026-09-18, `'"9048"6722'` and
    # `'8901537"024014॥'` are both barcodes that matched nothing because of a
    # quote mark. Stripping the marks OCR invents — and only those — recovers
    # the digit run without touching the length rule, which is what keeps a
    # ten-digit helpline from being called a barcode.
    # A date is not a barcode, and the length rule cannot tell: `_BARCODE_NOISE`
    # strips hyphens and full stops, so `09-08-2023` becomes `09082023` -- eight
    # digits, the length of an EAN-8. Every `DD-MM-YYYY` on every pack was
    # classified `barcode` here, and `associate` only offers lines left as
    # `other` as values, so a date named here could never reach the declaration
    # it belonged to. Asked before the length test because the shape is the
    # stronger statement: the pack said what this is.
    if not shapes.is_date(text.strip()) and _BARCODE.fullmatch(
        _BARCODE_NOISE.sub("", text.strip())
    ):
        # Named rather than left as `other` since 2026-09-18. It was always
        # recognised as a barcode here; calling it one puts that on the
        # annotated photograph instead of making an officer guess why a box on
        # the barcode says `other`. No rule targets `barcode`.
        return FieldGuess("barcode", 0.80, "a barcode-length digit run, not a price or quantity")

    # **The batch test below gets the text with its spaces, and that is load
    # bearing.** Squeezing them out turns `MRP Rs 45` into `MRPRs45`, which is
    # an alphanumeric run carrying the letters MRP — precisely the shape of the
    # batch code the guard below exists to catch — and the retail sale price
    # then disappears from the pack. That is the failure the comment under this
    # one records having already been fixed once.
    #
    # Written out rather than left implicit because it was broken here on
    # 2026-09-18 while the barcode strip above was being added: the two tests
    # want different text, and sharing one variable between them is how they
    # end up wanting the same.
    stripped = text.strip()

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

    return _non_statutory(stripped)


# ---------------------------------------------------------------------------
# Present on the panel, and not a declaration Rule 6(1) asks for.
# ---------------------------------------------------------------------------

_DECLARATION_CAPTION = re.compile(
    r"(?i)\b(m\.?r\.?p|max(imum)?\s*retail|net\s*(wt|weight|qty|quantity|content)"
    r"|manufactur\w*|marketed\s*by|packed\s*by|imported\s*by|consumer\s*care|customer\s*care"
    r"|batch|lot\s*no|best\s*before|use\s*by|mfg|mfd|pkd"
    r"|country\s*of\s*origin|made\s*in|product\s*of)\b"
)
"""A line carrying one of these belongs to the declaration patterns, full stop.

Checked first and it is the whole safety of this block. Everything below names
something that is NOT a declaration, and a name assigned here is assigned
*before* any declaration pattern is tried — so a rule that fired on a line
carrying `Net Wt. 500 g` would take the net quantity out of the engine's reach
entirely. Nothing gets a non-statutory name while a declaration caption is on
the line with it."""

_USP_CAPTION = re.compile(
    r"(?i)(\bunit\s*(sale\s*)?price|\busp\b"
    r"|price\s*per\s*(g|gm|kg|ml|l|n|pc|piece|number|pad|unit))"
)
_USP_RATE = re.compile(
    r"(?i)(rs\.?|₹|र)\s*\d+(?:[.,]\d{1,3})?\s*(/|per)\s*"
    r"(g|gm|kg|ml|l|n|pc|piece|number|pad|unit)\b"
)
_BARE_PRICE = re.compile(
    r"(?i)(rs\.?|₹|र)\s*\d+(?:[.,]\d{1,2})?(?![\d.,])"
    r"(?!\s*(/|per)\s*(g|gm|kg|ml|l|n|pc|piece|number|pad|unit))"
)
"""A price that is NOT a rate, and the reason the two are separated.

`*₹ 10 @ ₹0.22/g` is santoor1's coded price line: the retail sale price and the
unit sale price printed together with no caption between them. Claiming it for
the unit price would cost the pack its MRP, so a line carrying any non-rate
price falls through to the declaration patterns.

`(?![\\d.,])` matters and was not obvious. Without it `Rs. 0.17 per g` matches:
the engine backtracks the amount to `0.1`, the rate lookahead then sees `7 per
g` instead of ` per g`, and a unit rate is read as a bare price."""

_NUTRITION = re.compile(
    r"(?i)\b(nutrition\w*|nutritive|energy|protein|carbohydrate|sugars?|"
    r"total\s*fat|saturated|trans\s*fat|monounsaturat\w*|polyunsaturat\w*|"
    r"cholesterol|sodium|potassium|calcium|iron|phosphorus|vitamin|"
    r"serving\s*size|servings?\s*per|kcal|\brda\b|dietary\s*allowance|"
    r"per\s*100\s*(g|ml)|amount\s*per)\b"
)
"""Vocabulary that belongs to a nutrition panel.

**A nutrient name with no figure beside it is still a nutrition row, and
requiring one cost 192 of them.** That was tried on 2026-09-19 and measured the
same day: packs set the nutrition table in two columns and the detector returns
each column as its own region, so `ENERGY`, `PROTEIN`, `CARBOHYDRATE`, `TOTAL
SUGARS` and `TRANS FAT` arrive as bare labels with their figures in a separate
box. It is the same column split `vision.ocr.split` un-welds from the other
side.

What that attempt was trying to fix is real and is fixed elsewhere: `CRYSTAL
SUGAR` is the generic name on `sugar.jpg` and `sugars?` claims it. A nutrient
word is reclaimed by `vision.classify.commodity` when the whole line is a
commodity term exactly, which `TOTAL SUGARS` and `ENERGY` are not."""


def _is_nutrition(text: str) -> bool:
    return bool(_NUTRITION.search(text))


_PANEL_HEADING = re.compile(
    r"(?i)\b(ingredients?|nutrition\w*|nutritive|amount\s*per|per\s*100\s*(g|ml)"
    r"|serving\s*size|servings?\s*per|allergen)\b"
)


def is_panel_heading(text: str) -> bool:
    """Does this line *introduce* an ingredients or nutrition panel?

    Narrower than `_NUTRITION` and `_INGREDIENTS`, and the two questions are
    genuinely different. Those ask what a line belongs to, which is what puts
    the right name on the exhibit. This asks whether a line is the *top* of a
    block, which is what `vision.classify.commodity` needs before it will let a
    line cast a shadow over everything printed beneath it.

    Measured on `rocksalt.jpg`: the pack sets its nutrition table with each
    nutrient on its own line, so `Energy`, `Sodium`, `Potassium`, `Calcium` and
    `Carbohydrate` were each named `nutrition` -- correctly -- and each then
    anchored a block walk of its own. One of those walks ran down the panel and
    swallowed `Mt (Sondha Namak)`, which is the pack's generic name. A table row
    is not a heading, and only a heading may claim what is under it.
    """
    return bool(_PANEL_HEADING.search(text))
_INGREDIENTS = re.compile(
    r"(?i)\b(ingredients?|emulsifier|preservative|antioxidant|raising\s*agent|"
    r"acidity\s*regulat\w*|stabili[sz]er|anticaking|humectant|"
    r"artificial\s*(flavour|colour)|nature\s*identical|\bins\s*\d{3}|"
    r"contains\s+(wheat|milk|soy|nuts)|allergen)\b"
)
_STORAGE_USE = re.compile(
    r"(?i)\b(store\s+(in|under|at|away)|storage\s*(condition|instruction)?s?\b|"
    r"keep\s+(in|away|under|refrigerat\w*|out\s*of\s*reach)|refrigerat\w*|"
    r"directions?\s*for\s*use|how\s*to\s*use|recommended\s*usage|shake\s*well|"
    r"once\s*opened|airtight|away\s*from\s*(sun|direct|heat)|do\s*not\s*freeze)\b"
)
_FSSAI = re.compile(
    r"(?i)(\bf?ssai"
    r"|lic(?:en[cs]e)?[.,]?\s*n[o0][.,:;\-\s]*\d"
    r"|\b\d{14}\b)"
)
"""An FSSAI licence number, and the two ways this pattern used to invent one.

**A licence caption with no licence number is not a licence.** The phrase alone
was enough before, so `'License No., pleas'` -- four words clipped out of
`ghee.jpg`'s *"quote the Batch No. and License No., please"*, a consumer-care
sentence -- was named an FSSAI licence on the officer's exhibit. Requiring a
digit after the caption costs nothing real: every genuine licence line in the
38-panel set carries its number on the same line, and one that truly carries
the caption alone still matches on the word `fssai` printed beside it.

**The digit is what does the work, so the word boundary can go.** `PUBLIC
NOTICE` contains `lic no` and was the reason for a leading `\\b` -- but it is
not followed by a number, so the digit already refuses it, and the boundary was
refusing real licences instead. Across the 469-frame corpus it cost three:
`OLIC NO 1012013`, `ANLIC. NO.10104` and `ssaiLicense No.1001404700153`, each
one a licence whose first letters OCR welded to the word before.

`f?ssai` and the run of punctuation are the same concession to what the
recogniser returns: `LIC. NO.: 10U12U1200066` and `LIC. No.-1001404700042` are
both licences printed plainly and both have two marks where the pattern allowed
one. The bare 14-digit run stays -- that is the licence's own shape, and on
`udadpapad.jpg` it is the only thing left after the caption is read as
`/ssCIf Lic, No.`"""


def _non_statutory(text: str) -> FieldGuess | None:
    """Name what the panel carries that is not a Rule 6(1) declaration.

    **No rule targets any of these and none of them can change a verdict.** A
    rule reaches its subject through the rulepack's `field:`/`fields:` keys, so
    a name that appears in no rulepack entry is invisible to the engine. What it
    changes is the annotated photograph, and that is worth changing on its own:
    measured on `rocksalt.jpg`, 37 boxes read `other` and 17 of them are the
    nutrition table, the storage note and the FSSAI licence. An officer looking
    at a panel of `other` cannot tell *"we saw this and it is not a
    declaration"* from *"we could not read this"*, and those are opposite
    statements about the same pack.

    Order is deliberate. The USP caption is decisive and comes before the
    bare-price guard, because `UNIT SALE PRICE : ₹ 75.00` says what it is. The
    bare-price guard then protects every uncaptioned price line. Only after
    both does an uncaptioned rate get claimed.

    **The nutrition panel is settled before any of that, and it has to be.**
    `_BARE_PRICE` looks for `rs` with no letter boundary in front of it, which
    is deliberate -- OCR welds the caption onto the figure often enough that
    `MRPRS.750` and `M p alatRS.750` are both real lines off real packs, and
    refusing them would cost a pack its price. But `Sugars 13.5g` ends in those
    same two letters, so seventeen lines across the corpus -- `Total Sugars
    46g`, `OF WHICH SUGARS 24.8g`, `-added sugars 0.0g` -- were read as
    carrying a price and dropped straight through to the declaration patterns,
    which is how a nutrition row came to be shown to an officer as `other`.

    Asking about nutrition first costs the price guards nothing, because
    `_DECLARATION_CAPTION` above has already returned for every line carrying
    `MRP`, `maximum retail` or a net-quantity caption. What is left for the
    nutrition test to see is a line with a nutrient name, a figure, and no
    declaration caption anywhere on it.
    """
    if _DECLARATION_CAPTION.search(text):
        return None

    if _is_nutrition(text):
        return FieldGuess("nutrition", 0.85, "nutritional information, not a declaration")
    if _INGREDIENTS.search(text):
        return FieldGuess("ingredients", 0.85, "ingredient list, not a declaration")

    if _USP_CAPTION.search(text):
        return FieldGuess("unit_sale_price", 0.85, "unit sale price, captioned as such")

    if _BARE_PRICE.search(text):
        return None  # a price that is not a rate; the declaration patterns decide

    if _USP_RATE.search(text):
        return FieldGuess("unit_sale_price", 0.80, "a price expressed per unit of quantity")

    if _STORAGE_USE.search(text):
        return FieldGuess("storage_use", 0.85, "storage or usage instruction, not a declaration")
    if _FSSAI.search(text):
        return FieldGuess("fssai_licence", 0.85, "an FSSAI licence number, not a declaration")

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


_ADDRESS_COMPANY = re.compile(
    r"(?i)\b(pvt|ltd|limited|llp|inc|industries|foods?|company|co\.|corp\w*|enterprises?"
    r"|pharma\w*|mills?|works|agro|dairy|beverages?|products?|traders?|packers?|exports?)\b"
)
_ADDRESS_PIN = re.compile(r"(?i)(\b\d{6}\b|\bpin\s*[:\-]?\s*\d{3}\s?\d{3}\b|\b\d{3}\s\d{3}\b)")
"""An Indian PIN, including the `PIN-700 154` spelling with a space in it."""

_ADDRESS_PLACE = re.compile(
    r"(?i)\b(road|rd\.|street|st\.|nagar|marg|dist|district|state|india|taluka|tehsil"
    r"|village|phase|plot|sector|floor|building|estate|industrial|bypass|highway|lane"
    r"|colony|chowk|bazar|bazaar|cross|layout|park|complex|premises|opp\.|near|behind"
    r"|p\.?\s?o\.?\b|p\.?\s?s\.?\b|po\s*box|post\s*box|regd|registered\s*off\w*|off\w*\s*:)\b"
)
_ADDRESS_STATE = re.compile(
    r"(?i)\b(west\s*bengal|maharashtra|gujarat|karnataka|tamil\s*nadu|kerala|punjab|haryana"
    r"|rajasthan|odisha|orissa|bihar|assam|telangana|andhra|madhya\s*pradesh|uttar\s*pradesh"
    r"|uttarakhand|jharkhand|chhattisgarh|goa|himachal|delhi|mumbai|pune|kolkata|chennai"
    r"|bengaluru|bangalore|hyderabad|ahmedabad|nagpur|indore|jaipur|lucknow|kanpur|surat"
    r"|noida|gurgaon|gurugram|thane|nashik|howrah|singapore|nepal|bhutan)\b"
)


def is_address_like(text: str) -> bool:
    r"""Does this look like an address, and therefore need the model tier?

    Manufacturer, packer, importer and consumer care are all addresses. When
    one is *labelled* — `Manufactured by:` — regex settles it. When it is not,
    only position and context distinguish them, which is exactly and only what
    the 2M-parameter head is for.

    Widened 2026-09-18 after measuring it against the corpus. The three
    original signals were written for a whole address and were applied to a
    single printed *line*, which is not the same string. An address on a pack
    runs down four or five lines, and the middle ones carry no company suffix
    and no city:

        'DIST.: 24 PARGANAS (SOUTH), P.S. SONARPUR,'
        'PIN-700 154, WEST BENGAL.'
        'KANDUAH FOOD PARK, PHASE-I, WBIDC, P.O. SANKRAIL'

    All three are addresses and all three scored 1. Measured over 80 random
    corpus photographs, 61 of 76 continuation lines belonging to a *captioned*
    manufacturer were rejected here — and since this function gates the
    candidate list, those lines were never offered to the head at all. A
    perfectly trained classifier could not have recovered them.

    Two specific failures are worth naming. `\b\d{6}\b` misses `PIN-700 154`,
    because packs print the PIN with a space in the middle. And two place words
    on one line counted once, so a line saying both `DIST.` and `P.S.` scored
    the same as a line saying neither.

    Distinct place tokens are therefore counted, up to two. The threshold stays
    at two signals: it is what keeps nutrition rows, ingredient lists and
    storage instructions out, which was verified against twelve such lines
    before this was widened.
    """
    places = {match.group(0).lower() for match in _ADDRESS_PLACE.finditer(text)}
    score = sum(
        1
        for signal in (
            _ADDRESS_COMPANY.search(text),
            _ADDRESS_PIN.search(text),
            _ADDRESS_STATE.search(text),
        )
        if signal
    )
    return score + min(len(places), 2) >= 2


__all__ = [
    "FieldGuess",
    "classify_line",
    "classify_text",
    "is_address_like",
    "is_panel_heading",
]
