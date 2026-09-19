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
printed. Four guards, each earning its place:

1. **Short, uncaptioned, non-prose, non-address lines only.** A generic name
   is a noun phrase, not a sentence, not a captioned field and not a company.
   `MAX_WORDS` rejects `Contains wheat flour, sugar, edible vegetable oil`;
   `_CAPTION` rejects `Mfd by: ... Milk`; `is_address_like` rejects the
   manufacturer whose trading name contains a commodity.
2. **Only lines nothing else claimed.** This tier runs last and looks solely
   at `other`. It never overrides a captioned declaration.
3. **Prose markers reject the line.** A commodity term inside a sentence is
   not a declaration of the commodity.
4. **One per pack, chosen by display type.** A pack declares its commodity
   once. Where several lines match, the one set in the largest type wins --
   `cap_height_px` is already measured during OCR, and display type on the
   principal panel is precisely where 6(1)(b) expects this to be printed.

The brand is usually the largest text on a pack and would beat the generic
name on guard 4. It does not, because a brand is not in the lexicon: `Santoor`
and `Surf Excel` match nothing here, which is the same property that makes
`Product Name` a forbidden caption in the rulepack -- 6(1)(b) wants the
commodity, never the marque.
"""

from __future__ import annotations

import re
import unicodedata

from vision.classify.regex_tier import FieldGuess, is_address_like
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
    r"(?i)^[\W_]*((the\s*)?(product|item|commodity|contents?|variant|type"
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
    r"|direction|instruction|best\s*before|use\s*(by|before|within))\b"
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
        "condensed milk", "dairy whitener",
    ),
    "staples and condiments": (
        "sugar", "crystal sugar", "jaggery", "gur", "salt", "rock salt",
        "iodised salt", "honey", "jam", "ketchup", "tomato ketchup", "sauce",
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


def match(text: str) -> str | None:
    """The most specific commodity term this line declares, or `None`.

    Guards 1 and 3 live here so that a caller testing a single string gets the
    same answer the pipeline would give it.
    """
    stripped = text.strip()
    if not stripped or len(stripped.split()) > MAX_WORDS:
        return None
    if is_address_like(stripped):
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

    for term in TERMS:  # longest first
        if len(term) < _minimum_length(term):
            continue
        folded = _normalise(term)
        if not _word_bounded(normalised, folded):
            continue
        # Prose is judged on what is left once the term is taken out. The
        # marker has to be words *around* the commodity -- `KEEP SOAP DRY` --
        # because a term is allowed to contain one of them itself. Checking the
        # whole line instead made `dish wash` and `after shave` unmatchable:
        # `wash` and `after` were prose markers, so every line that could have
        # carried those commodities was rejected before the lexicon was read.
        residue = f" {normalised} ".replace(f" {folded} ", " ", 1)
        if _PROSE.search(residue):
            return None
        return term
    return None


def identify(
    lines: list[OcrLine],
    guesses: list[FieldGuess],
) -> tuple[int, str] | None:
    """The one line on this pack that declares its commodity, or `None`.

    Guards 2 and 4. Returns the index rather than mutating, so the caller owns
    the decision and a test can ask what this tier *would* have said without
    running the classifier.
    """
    candidates: list[tuple[float, int, str]] = []
    for index, (line, guess) in enumerate(zip(lines, guesses, strict=True)):
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
