"""The generic name has no caption, so it has to be found by its words.

    "We can only find a declaration by its label, so an absence here is a
     statement about our vocabulary and not about the pack."
                    -- rules/packs/lmpc_2011.yaml, LMPC.GENERIC.PRESENT

That comment was written as an admission. This module is the answer to it.

---------------------------------------------------------------------------
THE MEASUREMENT THAT FORCED IT
---------------------------------------------------------------------------
On the 38 hand-labelled declaration panels (2026-09-19, `bench/`):

    field            P       R      F1   support
    generic_name  1.00    0.04    0.07        27

One of twenty-seven. Every other field on that table sits between 0.45 and
0.85 recall, and the reason this one is an order of magnitude worse is
structural rather than a tuning failure: Rule 6(1)(b) requires the common or
generic name, and it does not require a caption. Packs print it in display
type with nothing in front of it --

    Incense Stick      LED LAMPS      Mechanical Pencil      BALL POINT PEN
    Coconut Oil        Toilet Soap    DETERGENT CAKE         BOILED RICE

-- so `generic_name_locate`, which anchors on `Name of Commodity` or
`Commodity :`, has nothing to anchor to. The pattern is not wrong. It is
looking for a caption that most packs never print.

---------------------------------------------------------------------------
WHY A WORD LIST AND NOT A MODEL
---------------------------------------------------------------------------
A vision model reads these correctly, which is how the gap was found. It is
still the wrong instrument here, for three reasons that outlast any accuracy
number:

- **A lexicon is evidence.** `generic_name = "toilet soap"` because the line
  said `Toilet Soap` and that term is in a list an officer can read. The
  reason string names the term. A model's answer cannot be cross-examined.
- **It costs nothing and needs no network.** Section 5's L1 promise is a full
  local scan with no signal, and the plan's own scoreboard asks for cost per
  scan at zero rupees in API fees.
- **It fails in the safe direction.** An unknown commodity is simply not
  matched, and `uncaptioned_form_is_lawful: true` already routes a missing
  generic name to REVIEW rather than FAIL. Widening the vocabulary can add
  true positives; it cannot manufacture a contravention.

---------------------------------------------------------------------------
PRECISION IS NOT NEGOTIABLE
---------------------------------------------------------------------------
The declaration set scores P 0.98 / R 0.63. Precision that high is the reason
an officer can act on a finding, and a word list is exactly the sort of change
that trades it away quietly -- `sugar` appears in every ingredients panel ever
printed. Five guards, each earning its place:

1. **Short, uncaptioned, non-prose, non-address lines only.** A generic name
   is a noun phrase, not a sentence, not a captioned field and not a company.
   `MAX_WORDS` rejects `Contains wheat flour, sugar, edible vegetable oil`;
   `_CAPTION` rejects `Mfd by: ... Milk`; `is_address_like` rejects the
   manufacturer whose trading name contains a commodity; `_CORPORATE` rejects
   the one whose trading name is short enough to score only one signal there.
2. **Only lines nothing else claimed.** This tier runs last and looks solely
   at `other` -- with one exception, `nutrition`, which claims `sugar`, `iron`
   and `calcium` and is overridden only where the whole line is a term.
3. **Prose markers reject the line.** A commodity term inside a sentence is
   not a declaration of the commodity.
4. **One per pack, chosen by display type.** A pack declares its commodity
   once. Where several lines match, the one set in the largest type wins --
   `cap_height_px` is already measured during OCR, and display type on the
   principal panel is precisely where 6(1)(b) expects this to be printed.
5. **Not the body of a list.** `Milk and Mustard`, `Corn, Edible Vegetable
   Oil` and `lodized Salt, Spices` pass all four guards above, because nothing
   in the line itself says what it is. What says it is where it sits: under an
   `INGREDIENTS:` heading that was named correctly. See
   `_inside_a_prose_block`, which borrows the geometry from
   `vision.classify.continuation` rather than restating it.

The brand is usually the largest text on a pack and would beat the generic
name on guard 4. It does not, because a brand is not in the lexicon: `Santoor`
and `Surf Excel` match nothing here, which is the same property that makes
`Product Name` a forbidden caption in the rulepack -- 6(1)(b) wants the
commodity, never the marque.
"""

from __future__ import annotations

import re
import unicodedata

from vision.classify import continuation
from vision.classify.regex_tier import FieldGuess, is_address_like, is_panel_heading
from vision.types import OcrLine

CONFIDENCE = 0.55
"""Below a captioned match (0.80-0.88) and above `MIN_EMIT_CONFIDENCE`.

A caption is the pack telling us what a line is. This tier is us recognising a
word, which is weaker evidence and is scored as such -- the number travels into
the report, so an officer sorting by confidence sees these below the fields
that named themselves."""

MAX_WORDS = 6
"""`HIMALAYAN ROCK SALT / SENDHA NAMAK` is five. `SUPREME HARVEST CRYSTAL
SUGAR` is four. Ingredient sentences start at seven and run to forty."""

MIN_TERM_CHARS = 3
"""`tea` and `pen` are real commodities and the shortest Latin term that may
match. Two letters would put `ml`, `gm` and `kg` into play."""

MIN_DEVANAGARI_CHARS = 2
"""Devanagari is an abugida: one character carries a whole consonant-vowel
syllable, so `घी` -- ghee -- is a complete word in two.

Applying the Latin minimum across both scripts made that entry unreachable:
the term sat in the lexicon, the loop skipped it every time, and a pack
declaring its commodity only in Devanagari was missed with nothing to show
why. A length rule written for one script is not a length rule."""

_CAPTION_SPLIT = re.compile("[:" + chr(0xFF1A) + "]")
"""Both colons, ASCII and fullwidth.

The fullwidth form is built by code point rather than typed, because the two
are indistinguishable in a monospaced diff and a reader cannot tell which is
which. A recogniser does emit it: it is in the character set the detection
head was trained on, and a pack photographed at an angle produces it."""

_PRODUCT_CAPTION = re.compile(
    r"(?i)^[\W_]*((the\s*)?(produc\w*|item|commodity|contents?|variant|type"
    r"|description|name(\s*of\s*(the\s*)?(product|item|commodity))?))[\W_]*$"
)
"""Captions after which the *commodity* may legitimately be printed.

A colon means the pack has said what this line is, and the honest response is
to believe it. Two lines, measured 2026-09-19:

    'PRODUCT: METAL PENCIL BOX'            <- pencilbox.webp, a real declaration
    'Met:-dby: GujaratCo-operatve Milk'    <- ghee.jpg, the manufacturer

Both carry a commodity word. The first is captioned `PRODUCT`; the second is
what the recogniser made of `Manufactured by`, too mangled for
`manufacturer_locate` to claim, which is how it reached this tier at all. So
the caption is the discriminator: an unrecognised caption means the line
belongs to a field we failed to read, and one word inside it is not a licence
to call it the commodity.

**This is not the `Product Name` the rulepack refuses.** `generic_name_locate`
excludes that caption deliberately, because whatever follows it is as often the
brand -- `Dark Fantasy Yumfills` -- and a locate pattern that accepts a brand
turns a real contravention into a pass. The difference here is that this tier
never accepts what follows a caption on the caption's word. It requires the tail
to *be* a commodity term from the lexicon. `Dark Fantasy Yumfills` matches
nothing and is refused; `METAL PENCIL BOX` matches `pencil box`. The caption
only decides whether the tail is eligible to be read at all."""

_PROSE = re.compile(
    r"(?i)\b(contains?|ingredients?|allergen|made|prepared|keep|store|storage"
    r"|refrigerat\w*|shake|wash|apply|avoid|dispose|caution|warning"
    r"|direction|instruction|best\s*before|use\s*(by|before|within)"
    r"|our|your|explore|enjoy|discover)\b"
)
"""A commodity term inside an instruction is not a declaration of commodity.

`ALWAYS KEEP UNDER REFRIGERATION` is the line `associate.py` records joining
itself to a net-quantity label on `cheese.jpg`, and storage copy is where
commodity nouns most often appear as ordinary words.

**Only strong markers.** The first draft also listed `after`, `for`, `with`,
`from`, `not`, `may` and a bare `use` -- function words that say nothing in a
line already capped at six words. One of them made `after shave` unmatchable:
the term sat in the lexicon and this guard rejected every line that could have
contained it. A guard that silently deletes an entry from the list it protects
is worse than no guard, because the list then claims a coverage it does not
have. `tests/unit/test_commodity.py` asserts every term is reachable."""


# ---------------------------------------------------------------------------
# The vocabulary
#
# Written from Indian retail packaging, not from the evaluation set's answers.
# Terms are generic commodity nouns -- what Rule 6(1)(b) calls the common or
# generic name -- and never brands, never marketing categories.
#
# Grouped only for reading. Nothing downstream uses the grouping, and the
# category names are not commodity classifications for any legal purpose --
# `unit_by_commodity` in the rulepack is the gazette-verified table and this
# is not it.
#
# Multi-word terms are listed before their heads would be reached: matching
# prefers the longest term, so `toilet soap` wins over `soap` and the reason
# string carries the specific one.
# ---------------------------------------------------------------------------

_GROUPS: dict[str, tuple[str, ...]] = {
    "grain and flour": (
        "rice", "boiled rice", "basmati rice", "wheat", "wheat flour", "atta",
        "maida", "suji", "sooji", "rava", "semolina", "besan", "gram flour",
        "poha", "flattened rice", "dal", "dhal", "pulses", "gram", "lentils",
        "millet", "ragi", "oats", "corn flour", "custard powder", "sabudana",
    ),
    "bakery and snacks": (
        "biscuits", "biscuit", "sandwich biscuits", "cream biscuits", "cookies",
        "rusk", "bread", "bun", "cake", "pastry", "wafers", "wafer",
        "namkeen", "bhujia", "mixture", "chips", "potato chips", "snack",
        "snacks", "papad", "appalam", "noodles", "instant noodles", "pasta",
        "macaroni", "vermicelli", "sewai",
    ),
    "dairy": (
        "milk", "toned milk", "milk powder", "curd", "dahi", "yoghurt",
        "yogurt", "paneer", "cheese", "processed cheese", "butter", "ghee",
        "cream", "fresh cream", "ice cream", "frozen dessert", "khoa",
        "condensed milk", "dairy whitener", "coconut milk",
    ),
    "staples and condiments": (
        "sugar", "crystal sugar", "jaggery", "gur", "salt", "rock salt",
        "sendha namak", "iodised salt", "honey", "jam", "ketchup", "tomato ketchup", "sauce",
        "pickle", "achar", "chutney", "vinegar", "baking powder",
        "masala", "spices", "spice", "turmeric", "turmeric powder",
        "chilli powder", "coriander powder", "cumin", "jeera", "garam masala",
        "asafoetida", "hing", "tea", "green tea", "coffee", "instant coffee",
        "chicory",
    ),
    "oils and fats": (
        "edible oil", "coconut oil", "mustard oil", "sunflower oil",
        "groundnut oil", "sesame oil", "rice bran oil", "soyabean oil",
        "soybean oil", "palm oil", "refined oil", "vegetable oil", "vanaspati",
        "cooking medium",
    ),
    "beverages and confectionery": (
        "juice", "fruit juice", "beverage", "soft drink", "drinking water",
        "packaged drinking water", "mineral water", "squash", "syrup",
        "health drink", "malt beverage", "malted food", "chocolate",
        "candy", "toffee", "lollipop", "sweets", "mithai", "energy drink",
    ),
    "personal care": (
        "soap", "toilet soap", "bathing bar", "bathing soap", "shampoo",
        "conditioner", "hair oil", "hair cream", "hair colour", "face cream",
        "cold cream", "face wash", "face pack", "moisturiser", "moisturizer",
        "lotion", "body lotion", "talc", "talcum powder", "deodorant",
        "perfume", "lip balm", "lipstick", "nail polish", "kajal", "kohl",
        "sunscreen", "toothpaste", "tooth powder", "mouthwash", "shaving cream",
        "shaving gel", "after shave", "razor", "razors", "blade", "hair remover",
    ),
    "hygiene and paper": (
        "sanitary pads", "sanitary napkins", "sanitary napkin", "panty liner",
        "diapers", "diaper", "baby wipes", "wet wipes", "tissue",
        "facial tissue", "toilet paper", "toilet roll", "kitchen towel",
        "cotton", "cotton wool", "ear buds",
    ),
    "home care": (
        "detergent", "detergent cake", "detergent powder", "detergent bar",
        "washing powder", "liquid detergent", "laundry detergent",
        "liquid laundry detergent", "fabric conditioner", "fabric whitener",
        "dishwash", "dish wash", "dishwashing liquid", "utensil cleaner",
        "handwash", "hand wash", "sanitizer", "sanitiser", "floor cleaner",
        "toilet cleaner", "glass cleaner", "phenyl", "bleach", "naphthalene balls",
        "air freshener", "room freshener", "mosquito repellent", "insecticide",
        "pesticide", "shoe polish",
    ),
    "household goods": (
        "incense stick", "incense sticks", "agarbatti", "agarbathi", "dhoop",
        "camphor", "safety match", "safety matches", "safety match boxes",
        "match box", "matchbox", "matches", "candle", "candles",
        "aluminium foil", "cling film", "garbage bag", "broom", "mop",
    ),
    "electrical": (
        "led lamp", "led lamps", "led bulb", "bulb", "lamp", "tube light",
        "battery", "batteries", "dry cell", "torch", "extension cord",
        "electric wire", "electric cable", "switch", "plug", "adaptor",
        "adapter",
    ),
    "stationery": (
        "pen", "ball point pen", "ball pen", "gel pen", "fountain pen",
        "brush pen", "sketch pen", "marker", "highlighter", "pencil",
        "mechanical pencil", "colour pencil", "color pencil", "crayon",
        "crayons", "eraser", "sharpener", "scale", "ruler", "geometry box",
        "pencil box", "notebook", "note book", "exercise book", "register",
        "file", "folder", "glue", "gum", "adhesive", "stapler", "tape",
        "drawing book", "graph book",
    ),
    "other commodities": (
        "footwear", "chappal", "slipper", "slippers", "shoe", "shoes",
        "garment", "shirt", "saree", "towel", "bedsheet", "blanket",
        "cement", "paint", "primer", "putty", "distemper", "adhesive cement",
        "fertiliser", "fertilizer", "seeds", "tyre", "tube", "toy", "toys",
        "agarbatti stand", "plastic container", "water bottle",
    ),
}

_DEVANAGARI: tuple[str, ...] = (
    "फेस क्रीम", "क्रीम", "साबुन", "नहाने का साबुन", "शैम्पू", "तेल",
    "नारियल तेल", "सरसों तेल", "चाय", "चीनी", "नमक", "आटा", "मैदा", "चावल",
    "दाल", "बिस्किट", "नमकीन", "पापड़", "दूध", "दही", "घी", "मक्खन", "शहद",
    "अगरबत्ती", "माचिस", "मोमबत्ती", "डिटर्जेंट", "वाशिंग पाउडर", "टूथपेस्ट",
    "पेन", "पेंसिल", "कॉपी", "बैटरी", "बल्ब",
)
"""Devanagari is a first-class script here, not a fallback.

Section 15b's `client-ocr` line calls for explicit Hindi support, and a pack
that prints its commodity only in Devanagari is as compliant as one that does
not. Short deliberately: these are the forms seen on retail panels, and a term
added here has to be a commodity noun on the same terms as the Latin list."""

TERMS: tuple[str, ...] = tuple(
    sorted(
        {term for group in _GROUPS.values() for term in group} | set(_DEVANAGARI),
        key=lambda term: (-len(term), term),
    )
)
"""Every term, longest first, so the most specific match is found first."""


_DEVANAGARI_RANGE = re.compile(r"[ऀ-ॿ]")

_CORPORATE = re.compile(
    r"(?i)(?<![a-z])(p\.?\s?v\.?\s?t|private|l\.?\s?t\.?\s?d|l[iu]?mited|llp"
    r"|inc|incorporated|corporation|company|industries|enterprises?)(?![a-z])"
)
"""A word that names a kind of legal entity, and therefore not a commodity.

`is_address_like` wants two signals before it calls a line an address, which is
right for what it gates -- nutrition rows and ingredient lists carry a company
word each and must not all be read as addresses. But this tier needs a weaker
test, because it is asking a narrower question: measured on the corpus,
`HALDIRAM SNACKS FOOD PRIVATE UMITED` scored one signal, fell through as an
ordinary line, and was declared the pack's generic name on the strength of the
word `snacks`.

`l[iu]?mited` takes `LIMITED`, `UMITED` and `LMITED`. No generic name contains
any of these words, so there is nothing to trade away."""


def _minimum_length(term: str) -> int:
    """How short this term is allowed to be, in its own script."""
    return MIN_DEVANAGARI_CHARS if _DEVANAGARI_RANGE.search(term) else MIN_TERM_CHARS


def _after_caption(text: str) -> str | None:
    """The part of the line the commodity could be in, or `None` if it is not
    ours to read.

    An uncaptioned line is returned whole -- that is the 6(1)(b) case this tier
    exists for. A captioned line is returned only from the last caption onward,
    and only when every caption on it names a product; otherwise the line
    belongs to the field its caption names.
    """
    if not _CAPTION_SPLIT.search(text):
        return text
    *captions, tail = _CAPTION_SPLIT.split(text)
    if not all(_PRODUCT_CAPTION.match(part) for part in captions):
        return None
    return tail.strip() or None


def _normalise(text: str) -> str:
    """Fold to a comparable form without destroying Devanagari.

    NFKC first: recognisers emit composed and decomposed forms of the same
    Devanagari cluster depending on the engine, and `vision/ocr/` mixes two.
    Casefold handles Latin; punctuation becomes space so `(100%)` and `GR. 3`
    do not weld themselves onto the word beside them.
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.sub(r"[^\wऀ-ॿ]+", " ", folded).split())


def _word_bounded(haystack: str, needle: str) -> bool:
    """`pen` matches `BALL POINT PEN` and never `OPEN` or `PENCIL`.

    Both strings are already normalised to space-separated tokens, so a token
    boundary is a space boundary and no regex is needed.
    """
    padded = f" {haystack} "
    return f" {needle} " in padded


# ---------------------------------------------------------------------------
# Matching what the recogniser returns, not what the printer set
# ---------------------------------------------------------------------------
#
# **The vocabulary was never the problem.** Of the eight labelled panels whose
# generic name went unfound on 2026-09-19, six had the name read correctly
# enough for a person to see it, and `lip balm`, `sanitary pads`, `rock salt`,
# `brush pen`, `safety match boxes` and `detergent cake` were all already in
# the lexicon. What stood between them was this:
#
#     LIP BALM             read  'LIPBALM'                  the space is gone
#     SANITARY PADS        read  'SCENTED SANTARYPADS'       space gone, I gone
#     SENDHA NAMAK         read  'Mt (Sondha Namak)'         one letter wrong
#     Product: Brush Pen   read  'Producd: Brush Pen ...'    one letter wrong
#
# A word gap is a guess the recogniser makes from pixel spacing, and display
# type on a principal panel is exactly where it guesses wrong -- tight
# letter-spacing at 40 px reads as one word. So the word boundary this lexicon
# was built on is not a boundary the input reliably has.

_TOLERANCE: tuple[tuple[int, int], ...] = ((12, 2), (6, 1))
"""Letters that may differ, by the length of the term with its spaces removed.

Nothing under six characters gets any tolerance at all, and that is where the
precision risk lives: `salt`, `soap`, `ghee`, `tea`, `pen` are four letters or
fewer and one edit from a dozen ordinary words each. `sugar` is five. Every
term short enough to be dangerous is matched exactly, and the tolerance only
reaches words long enough that being one letter out is evidence of a misread
rather than a different word."""


def _within(a: str, b: str, limit: int) -> bool:
    """Is `a` within `limit` single-character edits of `b`?

    Levenshtein, banded by the length difference so the early return does most
    of the work. Both strings are one squeezed word, so this is a dozen
    characters against a dozen.
    """
    if abs(len(a) - len(b)) > limit:
        return False
    if limit == 0:
        return a == b
    previous = list(range(len(b) + 1))
    for i, ch in enumerate(a, start=1):
        current = [i]
        for j, other in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (ch != other),
                )
            )
        if min(current) > limit:
            return False
        previous = current
    return previous[-1] <= limit


def _tolerance_for(folded: str) -> int:
    """How far a term may be misread. Devanagari is always matched exactly.

    An abugida packs a consonant and its vowel into one character, so a single
    edit there is a whole syllable -- the Latin intuition that one wrong letter
    is a typo does not carry across, and the terms are short enough in
    characters that any tolerance would be reckless.
    """
    if _DEVANAGARI_RANGE.search(folded):
        return 0
    squeezed = folded.replace(" ", "")
    for length, allowed in _TOLERANCE:
        if len(squeezed) >= length:
            return allowed
    return 0


def _run_matching(tokens: list[str], folded: str, limit: int) -> tuple[int, int] | None:
    """Where in `tokens` this term is printed, as a half-open token range.

    A term is matched against every run of *whole* tokens joined together,
    which is what lets `sanitary pads` find `SANTARYPADS` and still refuses to
    find `pen` inside `OPEN`. Joining only whole tokens is the boundary rule
    restated in a form that survives a lost word gap: the run may weld words
    together, but it can never start or end in the middle of one.
    """
    squeezed = folded.replace(" ", "")
    for start in range(len(tokens)):
        run = ""
        for end in range(start, len(tokens)):
            run += tokens[end]
            if len(run) > len(squeezed) + limit:
                break
            if _within(run, squeezed, limit):
                return start, end + 1
    return None


def match(text: str) -> str | None:
    """The most specific commodity term this line declares, or `None`.

    Guards 1 and 3 live here so that a caller testing a single string gets the
    same answer the pipeline would give it.
    """
    stripped = text.strip()
    if not stripped or len(stripped.split()) > MAX_WORDS:
        return None
    if is_address_like(stripped) or _CORPORATE.search(stripped):
        # Manufacturer, packer, importer and consumer care are all addresses,
        # and a dairy, an oil mill or a match works carries the commodity in
        # its own name. `Gujarat Co-operative Milk` is a company, not a
        # declaration that the pack contains milk.
        return None

    stripped = _after_caption(stripped)
    if stripped is None:
        return None

    normalised = _normalise(stripped)
    if not normalised:
        return None
    tokens = normalised.split()

    # Exactly matched terms are tried first, all of them, before any term is
    # allowed to match approximately. `toffee` and `coffee` are both commodities
    # and one edit apart; a single pass in term-length order would let the
    # longer of the two claim a line that spelled the shorter one perfectly.
    for tolerant in (False, True):
        for term in TERMS:  # longest first
            if len(term) < _minimum_length(term):
                continue
            folded = _normalise(term)
            limit = _tolerance_for(folded) if tolerant else 0
            if tolerant and limit == 0:
                continue  # already tried exactly, and nothing was allowed
            found = _run_matching(tokens, folded, limit)
            if found is None:
                continue
            # Prose is judged on what is left once the term is taken out. The
            # marker has to be words *around* the commodity -- `KEEP SOAP DRY`
            # -- because a term is allowed to contain one of them itself.
            # Checking the whole line instead made `dish wash` and `after
            # shave` unmatchable: `wash` and `after` were prose markers, so
            # every line that could have carried those commodities was rejected
            # before the lexicon was read.
            start, end = found
            residue = " ".join(tokens[:start] + tokens[end:])
            if _PROSE.search(f" {residue} "):
                return None
            return term
    return None


_BLOCK_FIELDS: frozenset[str] = frozenset({"ingredients", "nutrition"})

MAX_BLOCK_TYPE_RATIO = 1.15
"""How much larger than its heading a line may be set and still belong to it.

**A list is never set larger than the words introducing it.** On
`coconut_oil.jpg` the first line read is `INGREDIENT:` at 11 px and the line
directly under it is `Coconut Oil` at 14 px -- which is both the pack's sole
ingredient and its generic name, printed in display type on the principal
panel. Geometry alone cannot tell those apart and called it list body, and the
pack lost the only declaration it had: the scan then reported
`no_declaration_panel` on a photograph of the declaration panel.

Type size can tell them apart, and it is the same evidence guard 4 already
trusts to pick the generic name in the first place. Fifteen per cent is past
ordinary measurement noise between two lines of one block and well short of
the step from body copy to display type.

Where either line has no measured cap height the test is skipped and the line
is **not** shadowed. Suppression is the destructive move here, so an
unmeasurable line keeps its chance."""

MAX_BLOCK_LINES = 12
"""How far below an ingredients heading its list is still assumed to run.

Longer than `continuation.MAX_LINES`, and for the opposite reason. That limit
stops a declaration *claiming* lines, so overrunning would put someone else's
text inside a declaration; this one only stops a line being claimed, so
overrunning costs at worst a generic name printed underneath an ingredients
panel -- which is not where Rule 6(1)(b) expects one. Ingredient lists on the
corpus routinely run past eight lines."""


def _whole_line_term(text: str) -> str | None:
    """The term this line is, rather than the term this line contains.

    Exact and unabbreviated: no tolerance, no substring. It is the strictest
    form of the match, used in the one place a line already carries another
    name and has to earn the right to lose it.
    """
    normalised = _normalise(text)
    if not normalised:
        return None
    for term in TERMS:  # longest first; only one can equal the whole line
        if _normalise(term) == normalised:
            return term
    return None


def _set_larger_than(line: OcrLine, heading: OcrLine) -> bool:
    """Is this line in visibly bigger type than the heading it sits under?"""
    body, head = line.cap_height_px, heading.cap_height_px
    if not body or not head:
        return False
    return body > head * MAX_BLOCK_TYPE_RATIO


def _inside_a_prose_block(lines: list[OcrLine], guesses: list[FieldGuess]) -> set[int]:
    """Lines that are the body of an ingredients or nutrition panel.

    **The measurement that put this here.** Across the corpus and the labelled
    panels, lines like `Milk and Mustard`, `lodized Salt, Spices`, `Corn,
    Edible Vegetable Oil` and `Vegetable Oil (Palmolein), Cashew, Clarified
    Butter` were being declared the pack's generic name. Every one is a
    fragment of an ingredients list: short enough, no caption, not an address,
    no prose marker -- nothing in the line *itself* says what it is.

    What says it is where the line sits. `INGREDIENTS:` is named correctly and
    is directly above them, and the same geometry `vision.classify.continuation`
    uses to walk an address down the panel walks these too. The predicate is
    imported from there rather than restated, because two definitions of "the
    next line of this block" would drift apart.

    Only lines left as `other` are returned -- a line the classifier has
    already named is not in question. Lines named `ingredients` or `nutrition`
    do not end the walk, because a long list names itself again every few
    lines: `emulsifier`, `antioxidant`, `raising agent` each match.
    """
    order = sorted(range(len(lines)), key=lambda i: (lines[i].box.y, lines[i].box.x))
    inside: set[int] = set()

    for anchor in order:
        if guesses[anchor].field not in _BLOCK_FIELDS:
            continue
        if not is_panel_heading(lines[anchor].text):
            continue  # a table row is not a heading and claims nothing below it
        cursor = lines[anchor].box
        taken = 0
        for index in order:
            if taken >= MAX_BLOCK_LINES:
                break
            if index == anchor or index in inside:
                continue
            if lines[index].box.y <= cursor.y:
                continue
            if lines[index].rotation_k != lines[anchor].rotation_k:
                continue
            if not continuation.continues(cursor, lines[index].box):
                continue

            field = guesses[index].field
            if field in _BLOCK_FIELDS:
                cursor = lines[index].box  # still the same panel; keep walking
                taken += 1
                continue
            if field != "other":
                break  # the next declaration has started
            if _set_larger_than(lines[index], lines[anchor]):
                break  # display type: the panel has ended and something else began
            inside.add(index)
            cursor = lines[index].box
            taken += 1

    return inside


def identify(
    lines: list[OcrLine],
    guesses: list[FieldGuess],
) -> tuple[int, str] | None:
    """The one line on this pack that declares its commodity, or `None`.

    Guards 2, 4 and 5. Returns the index rather than mutating, so the caller
    owns the decision and a test can ask what this tier *would* have said
    without running the classifier.
    """
    shadowed = _inside_a_prose_block(lines, guesses)
    candidates: list[tuple[float, int, str]] = []
    for index, (line, guess) in enumerate(zip(lines, guesses, strict=True)):
        if index in shadowed:
            continue
        if guess.field == "nutrition":
            # `sugar`, `iron` and `calcium` are nutrients and they are also
            # commodities packs are sold as. On `sugar.jpg` the generic name is
            # printed `CRYSTAL SUGAR` in the largest type on the panel and
            # `_NUTRITION` claimed it, so a sugar packet declared no commodity.
            #
            # Reclaimed only where the whole line IS a term. `TOTAL SUGARS`,
            # `ADDED SUGARS` and `ENERGY` are not terms and stay where they
            # are; `CRYSTAL SUGAR` is one. Nothing is lost if this is wrong --
            # no rule targets `nutrition` either.
            term = _whole_line_term(line.text)
            if term is None:
                continue
            candidates.append((line.cap_height_px or 0.0, index, term))
            continue
        if guess.field != "other":
            continue
        term = match(line.text)
        if term is None:
            continue
        # `cap_height_px` is None where the crop gave no clean baseline. Such a
        # line is still a candidate -- it simply cannot win on display type, so
        # it sorts below every measured one rather than being dropped.
        candidates.append((line.cap_height_px or 0.0, index, term))

    if not candidates:
        return None

    # Largest type wins; the longer term breaks a tie, and the earlier line
    # breaks that, so the result does not depend on dictionary ordering.
    _height, index, term = max(candidates, key=lambda c: (c[0], len(c[2]), -c[1]))
    return index, term


def guess(term: str) -> FieldGuess:
    """The `FieldGuess` a matched term produces, reason string and all."""
    return FieldGuess(
        field="generic_name",
        confidence=CONFIDENCE,
        reason=f"names the commodity '{term}', printed without a caption",
    )


__all__ = [
    "CONFIDENCE",
    "MAX_WORDS",
    "MIN_DEVANAGARI_CHARS",
    "MIN_TERM_CHARS",
    "TERMS",
    "guess",
    "identify",
    "match",
]
