"""Structure-aware chunking of gazette text. AKSHAR.md section 15.

    "Chunking is the decision that actually matters. [...] Fixed 512-token
     windows would cut Rule 8(1) away from its proviso, and the proviso *is*
     the exclusion-zone rule."

That sentence is the whole specification, and it is worth being precise about
why. Rule 8(1) says every declaration shall appear on the principal display
panel — unremarkable, and on its own it supports no check we perform. Its
proviso says the area around the quantity declaration shall be free from printed
information, and then (a) and (b) give the distances. **`clear_space` is that
proviso.** A chunker that split by length would put the rule in one window and
its proviso in another, and an officer who tapped "why" on a clear-space finding
would be shown a sentence that does not mention clear space.

So the boundaries here are the statute's own: rule, sub-rule, clause, proviso,
Table. Each level is emitted as its own chunk **and** included in its parent, so
a lookup can be as specific as the citation is:

    Rule 7                  the whole rule, heading included
    Rule 7(2)               the sub-rule
    Rule 7(3) proviso       the proviso alone — a separately citable rule
    Rule 6(1)(a)            the clause
    Rule 7, Table I         the table

**Nothing here is learned and nothing is generative.** It is a line scanner over
a numbering convention, which is the correct tool: the hierarchy is printed in
the document, so inferring it would be inventing something that is already
written down.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from retrieval import provenance
from retrieval.normalise import (
    repair_spacing,
    restore_ascii_punctuation,
    strip_page_furniture,
    tidy,
    vocabulary,
)

RULE = re.compile(r"^\s*(\d{1,3})\.\s*(.*)$")
SCHEDULE = re.compile(
    r"^\s*(?:THE\s*)?([A-Z]+)\s*SCHEDULE\s*"
    r"(?:[-\u2013\u2014]?\s*HEADING\s*[-\u2013\u2014]?\s*([A-Z])\s*)?[-\u2013\u2014:]?\s*$",
    re.IGNORECASE,
)
"""A Schedule heading, in the four shapes these gazettes actually print.

`THE SECOND SCHEDULE` is the Packaged Commodities form. The General Rules drop
the article and the space -- `SIXTHSCHEDULE` -- and subdivide the Seventh into
`SEVENTH SCHEDULE - HEADING - A` through E, one per class of instrument. All
655 pages of it are Schedules, so requiring `THE` found none of them and filed
every specification in the document as `Rule n` against a numbering that
restarts in each Part.

**A trailing full stop is excluded, and that is the guard.** Dropping `THE`
would otherwise match the sentence fragments the rules are full of -- `... are
specified in Part I of First Schedule.` -- and open a Schedule in the middle of
Rule 4. Headings do not end in a full stop; cross-references do.
"""

SCHEDULE_HEADING = re.compile(r"^\s*HEADING\s*[-\u2013\u2014]*\s*([A-Z])\s*$", re.IGNORECASE)
"""`SEVENTHSCHEDULE` on one line, `HEADING-B` on the next -- the same heading
broken across two lines by the column reader. Without this, four of the five
Headings of the Seventh Schedule collapse into one ref."""

INDEX_ENTRIES_REPEAT = True
"""A Schedule that opens twice was an index the first time.

The General Rules print `INDEX OF SCHEDULE` and enumerate all thirteen before
the first one begins, and every entry looks exactly like a heading: `EIGHTH
SCHEDULE` above `SPECIFICATIONS FOR MEASURING INSTRUMENTS`. Length cannot tell
the two apart -- that index entry carries 406 characters and the National
Standards Seventh Schedule, which is real, carries 315 -- and neither can the
presence of numbered items, since both have none.

What does tell them apart is that the index is an enumeration *and then the
document does it again*. So the later occurrence wins and the earlier one's
lines are carried into it, which keeps the index in the corpus as front matter
of the Schedule it introduces rather than as a Schedule of its own.

This is a constant only so that it has somewhere to be explained.
"""

SUB_RULE = re.compile(r"^\s*[*†#]?\s*\((\d{1,2})\)\s*(.*)$")
CLAUSE = re.compile(r"^\s*[*†#]?\s*\(([a-z]{1,3}|[ivxl]{1,5})\)\s*(.*)$")
"""The optional `*` is an amendment footnote marker, and dropping it lost a rule.

The gazette prints `*(6) The declaration of quantity shall not contain any word
or expression which tends to create an exaggerated, misleading or inadequate
impression …` — the asterisk marking a later amendment. Without it in the
pattern, Rule 12(6) was invisible, and `LMPC.QTY.BANNED_WORDS` — the rule that
catches "minimum", "not less than", "about" on a net quantity — cited a
provision the index insisted did not exist.

The failure was instructive in the other direction too: the first reading was
that our *rulepack* had cited a sub-rule the gazette skips. It had not. The
parser was wrong, and it took opening the page to find out — which is the
argument for storing the page number with every chunk.
"""
PROVISO = re.compile(r"^\s*Provided(\s+further|\s+also)?\s*,?\s*that", re.IGNORECASE)
EXPLANATION = re.compile(r"^\s*Explanation\s*[.:—-]", re.IGNORECASE)
TABLE = re.compile(r"^\s*TABLE\s*[-–—]?\s*([IVX]+)\s*$", re.IGNORECASE)  # noqa: RUF001

# The en and em dashes are load-bearing, not typographic drift: the gazette
# opens rules with `.-`, `:-` and `.—` interchangeably, and a pattern that
# accepted only the ASCII hyphen would miss every heading typeset the other way.
_HEADING_TAIL = re.compile(r"\s*[.:—–-]+\s*$")  # noqa: RUF001

MIN_RULE_HEADING_WORDS = 2
"""A rule heading is prose, not a list item.

`13.` opens Rule 13; `13.` also opens a numbered row of a Schedule's commodity
list. Those rows are a number and a short name — "15. Soaps" — so requiring two
words separates a heading from a row without needing to know where the tables
are.

**With one exception, and it cost Rule 2.** `2. Definitions:-` is a single word,
so the word count alone silently dropped the rule that defines "pre-packaged
commodity" — and the rulepack cites `Rule 2(m)`. The heading punctuation the
gazette uses to open every rule (`:-`, `.-`, `.—`) is the second signal, and it
is one a commodity row never carries.
"""

_HEADING_PUNCTUATION = re.compile(r"[.:][-–—]\s*$")  # noqa: RUF001

SCHEDULE_ORDINALS = (
    "FIRST",
    "SECOND",
    "THIRD",
    "FOURTH",
    "FIFTH",
    "SIXTH",
    "SEVENTH",
    "EIGHTH",
    "NINTH",
    "TENTH",
    "ELEVENTH",
    "TWELFTH",
    "THIRTEENTH",
)
"""Ten was the Packaged Commodities count. The General Rules run to thirteen,
and its Eleventh, Twelfth and Thirteenth Schedules -- the manufacturer's
register, the scale of fees, and the form nominating a company's Director --
were being read as ordinary rules."""

SCHEDULE_SPELLINGS = {"EIGHT": "EIGHTH"}
"""The gazette sets the National Standards Rules' eighth Schedule as `THE EIGHT
SCHEDULE`. It is a typesetting error in the source, not a reading error, and
`Eighth Schedule` is what rule 18 calls it, so that is what it is filed as."""
"""Where the numbering restarts, and where a naive scanner goes badly wrong.

The Packaged Commodities Rules run to Rule 34 and are then followed by seven
Schedules, and **the Seventh Schedule numbers its own items from 1 again.** Its
item 7 is "Checking of other declarations". A scanner that sees `7.` and calls
it Rule 7 therefore overwrites the real Rule 7 — principal display panel, area,
size and letter — which is the rule behind every height check we perform.

That is not a cosmetic bug. An officer tapping "why" on a numeral-height finding
would have been shown a paragraph about examining declarations at a packer's
premises: confidently displayed, correctly formatted, and the wrong law. It was
caught by checking the first chunk this module produced for `Rule 7` against the
gazette, which is the only way it *could* have been caught.
"""


def _schedule_ref(
    ordinal: str,
    heading: str | None,
    division: tuple[str | None, str | None] = (None, None),
) -> str:
    """`Seventh Schedule`, `Seventh Schedule, Heading A`, `Eighth Schedule,
    Part VI, Appendix A` -- built in the order the gazette nests them."""
    ref = f"{ordinal} Schedule"
    if heading:
        ref += f", Heading {heading.upper()}"
    for level in division:
        if level:
            ref += f", {level}"
    return ref


@dataclass(frozen=True, slots=True)
class Chunk:
    """One citable unit of statute. §15's `{doc_id, rule_ref, parent_ref, text}`."""

    doc_id: str
    ref: str
    parent_ref: str | None
    heading: str
    text: str
    page: int
    kind: str = "sub_rule"
    source: str = provenance.TEXT_LAYER
    """How the page this chunk starts on was read. See `retrieval.provenance`."""

    @property
    def key(self) -> str:
        return self.ref.lower()

    @property
    def quotable(self) -> bool:
        """May this text be reproduced as the words of the statute?"""
        return self.source in provenance.QUOTABLE


@dataclass
class _Node:
    """A unit being accumulated, before its text is closed."""

    ref: str
    parent_ref: str | None
    heading: str
    page: int
    kind: str
    lines: list[str] = field(default_factory=list)

    def close(self, doc_id: str, sources: Mapping[int, str] | None = None) -> Chunk | None:
        text = tidy(" ".join(self.lines))
        if not text:
            return None
        return Chunk(
            doc_id=doc_id,
            ref=self.ref,
            parent_ref=self.parent_ref,
            heading=self.heading,
            text=text,
            page=self.page,
            kind=self.kind,
            source=(sources or {}).get(self.page, provenance.TEXT_LAYER),
        )


_ROMAN = frozenset(
    ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv")
)


def _follows(token: str, previous: str | None) -> bool:
    """Is `token` the next letter after `previous` in the clause sequence?

    The single most useful fact in this file. `(l)` after `(k)` continues a list
    of definitions; `(a)` after `(k)` is a fresh list nested inside something.
    That one distinction resolves both of the ambiguities below.
    """
    if previous is None or len(previous) != 1 or len(token) != 1:
        return False
    return ord(token) == ord(previous) + 1


def _is_roman(token: str, *, previous: str | None) -> bool:
    """Is `(i)` the numeral one, or the letter i? Only context can say.

    Both appear in this gazette. `(ii)` and above are unambiguous; `(i)`, `(v)`
    and `(x)` are not, and they land at different depths:

    - Rule 6(1) runs `(a)` … `(h)` `(i)` `(j)` … — a lettered list where `(i)`
      is the ninth letter.
    - Rule 7(2) is followed directly by `(i)` and `(ii)` with no lettered clause
      before them — numerals.
    - Rule 2(c) opens a lettered clause and *then* uses `(i)`, `(ii)` — numerals
      one level further down.

    So a single-letter token is a letter exactly when it continues the sequence.
    Reading it the other way would make `Rule 6(1)(i)` — the declaration of the
    month and year of packing — a sub-item of `Rule 6(1)(h)` instead of a
    requirement in its own right.
    """
    if token not in _ROMAN:
        return False
    return len(token) > 1 or not _follows(token, previous)


def _looks_like_a_heading(tail: str) -> bool:
    return (
        len(tail.split()) >= MIN_RULE_HEADING_WORDS
        or _HEADING_PUNCTUATION.search(tail) is not None
    )


_BARE_NUMBER = re.compile(r"^\s*[*†#]?\s*(\d{1,3})\.?\s*$")
"""The trailing stop is optional because OCR loses it.

The National Standards Rules' item 7 — the symbol-printing rules behind four of
our advisory checks — arrives as a bare `7`. Making the stop optional is what
lets that be found, and it is also why this cannot be the only test: a table
of SI prefixes is full of bare numbers, and this document has 148 lines that
match. The sequence check in `_join_orphan_headings` is what separates them.
"""

_ORPHAN_HEADING = re.compile(
    r"^[A-Za-z].{2,90}?(?:[.:]\s*[-–—]|[a-z][-–—](?=[A-Z(])|[a-z][-–—]\s*$)"  # noqa: RUF001
)
"""What a rule heading looks like once its number has been stripped off.

The gazette terminates every heading with a dash: after a full stop or colon in
the principal rules — `Short title and commencement. -`, `Definitions:-` — and
directly after the last word in the National Standards schedules, `Permitted
unit of volume-(1)`, `Printing:(1) Symbols of units-`. That dash is the only
thing separating a heading from a table cell that begins with a capital letter.

The bare-dash forms require an upper-case letter, an opening bracket, or the
end of the line after the dash, which is what keeps `Non-soapy detergents` — a
commodity in the Second Schedule, hyphenated mid-word — from reading as one.

Without it, `3.` followed by `Bread including brown bread but excluding bun.
100g and thereafter...` reads as a rule heading, and the Second Schedule's
standard pack sizes are silently rebuilt one row out of alignment: item 14
becomes `14. 15. Soaps`, and items 6, 8 and 19 vanish. A rule wrongly dropped
is a gap an officer can see. A schedule wrongly shifted is a confident answer
about the wrong commodity.
"""


_SUB_RULE_AT_START = re.compile(r"^\(\d{1,2}\)")
"""A rule whose text begins at its first sub-rule, with no heading between.

The National Standards Rules print `5.(1) Base units of Mass- The Base unit of
mass shall be the kilogram.` on a single line. `_looks_like_a_heading` accepts
the whole of it, so the rule opened with its own sub-rule as the heading and
`Rule 5(1)` -- the definition of the kilogram -- was never a chunk at all.

Requiring the bracket at the very start is what keeps this away from the
National Standards schedules, whose items read `Printing:(1) Symbols of units-`
and `Permitted unit of volume-(1)`. Those carry a real heading before the
bracket and must keep it.
"""

SCHEDULE_PART = re.compile(
    r"^\s*PART\s*[-\u2013\u2014.]?\s*([IVXL]{1,6}|\d{1,2})"
    r"(?:\s*[-\u2013\u2014.]?\s*([A-Z]))?\s*[.:]?\s*$"
    r"|^\s*PART[\s\-\u2013\u2014.]+([A-Z])\s*[.:]?\s*$",
    re.IGNORECASE,
)
SCHEDULE_APPENDIX = re.compile(
    r"^\s*(APPENDIX|ANNEXURE)\s*([A-E]|\d{1,2})\s*[.:]?\s*$"
    r"|^\s*(APPENDIX|ANNEXURE)[\s\-\u2013\u2014.]+([A-Z]|\d{1,2})\s*[.:]?\s*$",
    re.IGNORECASE,
)
"""How a Schedule divides itself, in the five spellings these gazettes use.

The Eighth Schedule of the General Rules is 126 pages of specifications --
filling machines, bulk meters, water meters, thermometers -- and **every
division numbers its clauses from 1**. Without them in the citation,
`Eighth Schedule, item 3` named twenty-three different provisions, among
them the tests for a filling machine and the nominal sizes of a water
meter, and tier 1 could only refuse all twenty-three.

An Appendix sits inside a Part, so the two are tracked separately and a new
Part clears the Appendix under it. `Eighth Schedule, Part VI, Appendix A,
item 1` is the test for hardness of a maximum indicating device; without
the Appendix it is one of four things called item 1 on page 578 alone.

The space after `PART` is optional because the column reader closes it --
`PARTI`, `PARTVIII`, `ANNEXUREB`. Anchoring at both ends is what keeps
`PARTICULARS OF LABORATORY` from reading as Part I. A single *letter* needs
a separator in front of it either way, because `PARTS` would otherwise be
Part S -- a citation to a division that does not exist, which is worse than
the ambiguity it was meant to remove.
"""

_DECIMAL = re.compile(r"^\s*\d{1,3}\.\d")
"""`2.0 to 3.5` is a range in a specification table, not item 2.

The stop with no space after it is the whole distinction, and it holds
across the corpus: the gazettes always set a space between a provision's
number and its text, and never inside a decimal. Without this, the Eighth
Schedule's tolerance tables opened an item at every measurement.
"""


_NUMBERS_ONLY = re.compile(r"^[\d.,\s]+$")
"""A row of column numbers, not a rule.

The Packaged Commodities Second Schedule heads its table `Sl. No. |
Commodities | Quantities`, then numbers the columns `1. 2. 3.` on the line
below. That read as item 1 with the heading `2. 3.`, and collided with the
real item 1 -- baby food -- so a citation to it resolved to two things, one
of which was a table header.
"""

RULE_COLON = re.compile(r"^\s*(\d{1,3}):\s*(.*)$")
"""`16: Deposit of Models or its drawings.` -- a colon where the gazette
means a full stop, in the Approval of Models Rules.

Kept apart from `RULE` and admitted only when the number continues the run
of rules, because `10:30` and `Table 3: dimensions` have this shape too and
neither is a provision.
"""

_SHORT_HEADING = re.compile(r"^[A-Z][a-z]{2,}[.:\u2013\u2014-]*$")
"""A rule whose heading is one word: `2. Definitions`, `11. Weights`.

`MIN_RULE_HEADING_WORDS` rejects these, and it is right to by itself -- a
Schedule's commodity rows read `15. Soaps`. What separates them is not the
heading but the number: a rule follows the rule before it. So a single word
is accepted only in sequence, which is also what makes `15. Soaps` open item
15 of the Schedule it sits in rather than be swallowed by item 14.

Alphabetic and capitalised, so the dimension line `3.5` in the General
Rules' drawings does not read as Rule 3.

The trailing punctuation is allowed because `_split_inline_openings` creates
this shape as well as finding it: `7. Printing:(1) Symbols of units-` splits
into `7. Printing:` and its sub-rule, and without the colon here the item that
carries four of the advisory checks stopped opening at all.
"""

_TRAILING_NUMBER = re.compile(r"(\d+)$")


_HEADING_THEN_SUB_RULE = re.compile(
    r"^(.{2,120}?[.:\u2013\u2014-])\s*(\((?:1|a)\)\s+\S.*)$"
)
"""A heading with the rule's first sub-rule printed on the end of it.

`15.Permitted units.(1) The units specified in the Fourth Schedule may` --
the gazettes set it this way **35 times**, in every instrument including the
Packaged Commodities Rules. The whole line became the heading, so sub-rule
(1) was not a chunk while (2), printed on its own line, was. Rules 15, 18,
22 and 23 of the National Standards Rules and fourteen of the Approval of
Models Rules all lost their first sub-rule that way.

`(a)` as well as `(1)`, because the same thing happens one level down: the
National Standards Tenth Schedule sets `1.Alcoholic strength-(a) The alcoholic
strength by volume...` and the IILM Rules `the Institute shall- (a) prepare,
print or publish...`, so clause (a) was body text while (b) and (c) were chunks.

Only the *first* marker of each level. A provision opens once, and looking for
`(2)` or `(c)` inline would start splitting sentences that merely mention them.

The sentence punctuation before the bracket is what makes this safe. A heading
that refers to `sub-rule (1) of rule 4` has a letter in front of the bracket,
not a stop, and is left whole.
"""

MIN_INLINE_WORDS = 3
"""How much text has to follow an inline marker before it is a provision.

`(5) (i) No system of units other than the International System of Units...`
is sub-rule 5 opening at clause (i). `(3) (i) and (ii) shall apply` is a
sentence that mentions two clauses. The words after the marker are what
separates them.
"""


_MANGLED_ROMAN = re.compile(r"^(\s*[*\u2020#]?\s*\()([il1]{2,3})(\).*)$")
ROMAN_MARKERS = {"i", "ii", "iii"}
"""`(ili)` is `(iii)` with an l for an i, and there are 420 of them.

`i`, `l` and `1` are one glyph to a recogniser reading a scan, so the
General Rules alone carry `(ili)` 153 times, `(li)` 71, `(il)` 48, `(ll)`
30. Every one of those became a citation an officer could never type:
`Rule 2(ili)(i)` is a real provision of the National Standards Rules and
there is no way to ask for it.

Only at the start of a line, where the marker opens a clause. In prose the
same three letters are a word, and rewriting those would be editing the
statute rather than repairing its transcription.

Only where the result is `ii` or `iii`. Mapping l and 1 onto i can only produce
runs of i, so a longer run -- `(ilil)`, `(lill)` -- did not come from a roman
numeral this scheme can recover, and is left as it was found. Pure digits are
left alone too: `(11)` is sub-rule 11 far more often than it is a damaged
`(ii)`, and there is nothing in the line to tell them apart.

**And never a single character.** `(l)` is a clause letter, not a damaged `(i)`
-- Rule 2(l) of the Packaged Commodities Rules is the definition of *retail
sale*. Rewriting it cost three of the pack's citations, and this is the guard
that stops it.
"""


def restore_roman_markers(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Put `(iii)` back where the recogniser read `(ili)`. See ROMAN_MARKERS."""
    out: list[tuple[int, str]] = []
    for page, text in lines:
        match = _MANGLED_ROMAN.match(text)
        if match:
            marker = match.group(2)
            numeral = marker.replace("l", "i").replace("1", "i")
            if not marker.isdigit() and numeral != marker and numeral in ROMAN_MARKERS:
                head = text[: match.start(2)]
                out.append((page, head + numeral + text[match.end(2) :]))
                continue
        out.append((page, text))
    return out


def _split_inline_openings(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Put a provision that opens at its own next level back onto two lines.

    Three shapes, one problem. `5.(1) Base units of Mass- ...` is a rule with no
    heading whose sub-rule (1) was being read as the heading, so the kilogram
    was not a chunk. `15.Permitted units.(1) The units specified...` is the same
    thing with a heading in front of it. And `(5) (i) No system of units other
    than the International System of Units shall be used...` is sub-rule 5
    opening at clause (i), so `Rule 13(5)(i)` -- which the rulepack cites -- was
    not a chunk either, while `Rule 13(5)(ii)`, printed on its own line, was.

    Splitting is the whole fix: each half then opens its own level through the
    branch that already exists for it. It runs *after* `_join_orphan_headings`,
    which is not the obvious order for its inverse -- but a rule number the
    recogniser pushed onto its own line has to be reunited with its heading
    before anyone can see what is on the end of that heading. Nothing is
    re-joined afterwards, because the joiner only ever acts on a bare number and
    refuses one followed by a sub-rule.

    The page number is carried onto both halves. The split is typographic; the
    provision did not move.
    """
    out: list[tuple[int, str]] = []
    for page, text in lines:
        rule = RULE.match(text)
        if rule and _SUB_RULE_AT_START.match(rule.group(2).strip()):
            out.append((page, f"{rule.group(1)}."))
            out.append((page, rule.group(2).strip()))
            continue

        inline = _HEADING_THEN_SUB_RULE.match(rule.group(2).strip()) if rule else None
        if inline:
            out.append((page, f"{rule.group(1)}. {inline.group(1)}"))
            out.append((page, inline.group(2)))
            continue

        # The same thing on a heading that wrapped. National Standards r. 23 is
        # set as `23. Custody, maintenance, etc. of national standards of
        # weights and` / `measures.-(1) The work relating to...`, so the sub-rule
        # arrives on a line that opens nothing and was read as body text.
        wrapped = _HEADING_THEN_SUB_RULE.match(text.strip())
        if wrapped and not RULE.match(text) and not SUB_RULE.match(text):
            out.append((page, wrapped.group(1)))
            out.append((page, wrapped.group(2)))
            continue

        sub = SUB_RULE.match(text)
        remainder = sub.group(2).strip() if sub else ""
        if sub and CLAUSE.match(remainder) and len(remainder.split()) >= MIN_INLINE_WORDS:
            out.append((page, f"({sub.group(1)})"))
            out.append((page, remainder))
            continue

        out.append((page, text))
    return out


def _join_orphan_headings(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Rejoin `2.` to the heading OCR pushed onto the next line.

    A recogniser returns one box per printed line, and these gazettes indent
    the rule number into its own short line often enough that the number and
    its heading arrive separately:

        1.
        Short title and commencement. - (1) These rules may be called ...

    `RULE` then matches a heading of zero words, `MIN_RULE_HEADING_WORDS`
    rejects it, and the rule is dropped silently along with every sub-rule
    under it. That is how the Numeration Rules lost rules 1 and 2 — and r.2(3),
    the digit-form provision, is cited by the rulepack.

    A bare number followed by a sub-rule marker is left alone: `5.` then `(1)`
    is a rule whose heading the gazette genuinely does not print, and gluing
    those together would invent a heading out of the rule's first sub-rule.

    The following line must also *look* like a heading — see `_ORPHAN_HEADING`,
    which exists because the first version of this joined the Second Schedule's
    serial-number column to the next commodity in the table.

    **And the number must continue the sequence.** This is the same test
    `_follows` applies to clause letters, for the same reason. A gazette's item
    numbers run 1, 2, 3; a table of SI prefixes contains bare numbers in no
    order at all, and the National Standards Rules has 148 lines that are
    nothing but a number. Requiring the successor of the last number seen keeps
    `6.` followed by `7` and rejects a magnitude column.
    """
    joined: list[tuple[int, str]] = []
    expected: int | None = None
    index = 0
    while index < len(lines):
        page, text = lines[index]
        bare = _BARE_NUMBER.match(text)
        if bare and index + 1 < len(lines):
            number = int(bare.group(1))
            following = lines[index + 1][1].strip()
            in_sequence = number > 0 and (expected is None or number == expected)
            if in_sequence and _ORPHAN_HEADING.match(following) and not SUB_RULE.match(following):
                joined.append((page, f"{number}. {following}"))
                expected = number + 1
                index += 2
                continue
        # A schedule restarts numbering from 1, so whatever sequence was running
        # is void. The Fourth Schedule needs this: OCR lost its item 1 entirely,
        # so the first number that survives is `2`, and against a stale sequence
        # from the Third Schedule it would be rejected.
        if SCHEDULE.match(text):
            expected = None
        numbered = RULE.match(text)
        if numbered:
            expected = int(numbered.group(1)) + 1
        joined.append((page, text))
        index += 1
    return joined


def restore_ell_marker(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Put `(l)` back where the recogniser read `(1)`, and only after `(k)`.

    The mirror of `restore_roman_markers`, and the reason that one refuses to
    touch a single character: `l` and `1` are the same glyph, so a clause `(l)`
    reads as sub-rule `(1)` and is filed one level up under the wrong parent.
    The National Standards Rules lose the definition of *SI prefix* that way --
    it sits between `(k) "Schedule" means...` and `(m) "special units" mean...`
    and arrives as `Rule 2(1)`, a sub-rule that does not exist.

    **Position is the whole test, because the text cannot be.** A clause letter
    is a single character and no amount of reading it tells you which glyph was
    printed. What does tell you is that the line before opened clause `(k)`: an
    alphabetic run that has reached k continues at l, and a genuine sub-rule (1)
    opens a rule rather than interrupting a clause list. So the rewrite fires
    only where a `(1)` follows a `(k)` with no rule or Schedule heading between
    them -- five places in the corpus, every one of them a real clause (l):
    the dip stick's cross-section, the taximeter's constant, the Bessel points,
    the rated minimum fill, and the SI prefix.

    Nothing else is touched. `(1)` after `(j)`, after a heading, or after
    nothing at all is left exactly as it was found.
    """
    out: list[tuple[int, str]] = []
    letter: str | None = None
    for page, text in lines:
        if RULE.match(text) or SCHEDULE.match(text):
            letter = None
        elif (clause := CLAUSE.match(text)) and len(clause.group(1)) == 1:
            letter = clause.group(1)
        elif (sub := SUB_RULE.match(text)) and sub.group(1) == "1" and letter == "k":
            head = text[: text.index("(1)")]
            out.append((page, f"{head}(l){text[text.index('(1)') + 3 :]}"))
            letter = "l"
            continue
        out.append((page, text))
    return out


def chunk_document(
    raw: str,
    *,
    doc_id: str,
    repair: bool = True,
    sources: Mapping[int, str] | None = None,
) -> list[Chunk]:
    """Split one gazette into citable chunks, outermost first.

    A rule's own chunk carries the whole rule including everything nested under
    it, so `Rule 8` answers a question about Rule 8 and `Rule 8(1) proviso`
    answers a narrower one. The nesting is duplication measured in kilobytes,
    against a corpus §15 sizes at 1,700 chunks — and it is what lets tier 1
    answer at exactly the specificity the citation used.
    """
    # Before anything reads a bracket. `SUB_RULE` and `CLAUSE` key on ASCII
    # punctuation, and the recogniser emits the fullwidth forms.
    raw = restore_ascii_punctuation(raw)
    if repair:
        raw, _ = repair_spacing(raw, vocabulary(raw))

    # Join before splitting. The Numeration Rules print `1.` on its own line and
    # `Short title and commencement. - (1) These rules...` on the next, so the
    # inline sub-rule only becomes visible once the two are one line.
    lines = _split_inline_openings(
        _join_orphan_headings(
            restore_ell_marker(
                restore_roman_markers(strip_page_furniture(raw.splitlines()))
            )
        )
    )

    chunks: list[Chunk] = []
    rule: _Node | None = None
    sub: _Node | None = None
    clause: _Node | None = None
    subclause: _Node | None = None
    tail: _Node | None = None  # proviso, explanation or table
    schedule: str | None = None  # set once the Schedules begin; numbering restarts
    schedule_node: _Node | None = None  # the Schedule itself, as a citable chunk
    schedule_heading: str | None = None  # the Seventh Schedule's Headings A-E
    # `PART VI` and the `APPENDIX A` under it; see SCHEDULE_PART.
    schedule_part: str | None = None
    schedule_appendix: str | None = None
    awaiting_heading = False  # a Schedule just opened; its Heading may be next
    preamble: _Node | None = None  # the notification, before any rule opens
    last_clause: str | None = None  # the letter the current sequence reached

    if sources is None:
        sources = provenance.sources_for(doc_id)

    def close(node: _Node | None) -> None:
        if node is None:
            return
        finished = node.close(doc_id, sources)
        if finished is not None:
            chunks.append(finished)

    def close_tail() -> None:
        nonlocal tail
        close(tail)
        tail = None

    def close_subclause() -> None:
        nonlocal subclause
        close_tail()
        close(subclause)
        subclause = None

    def close_clause() -> None:
        nonlocal clause
        close_subclause()
        close(clause)
        clause = None

    def close_sub() -> None:
        nonlocal sub
        close_clause()
        close(sub)
        sub = None

    def close_rule() -> None:
        nonlocal rule
        close_sub()
        close(rule)
        rule = None

    def close_schedule() -> None:
        nonlocal schedule_node
        close_rule()
        close(schedule_node)
        schedule_node = None

    def absorb_index_entry(node: _Node) -> None:
        """Fold an earlier chunk for the same Schedule into this one.

        See `INDEX_ENTRIES_REPEAT`. The earlier chunk's text is carried rather
        than dropped, so the index survives as front matter and no line of the
        gazette is lost to the collapse.
        """
        for i, chunk in enumerate(chunks):
            if chunk.kind == "schedule" and chunk.ref == node.ref:
                node.lines.insert(0, chunks.pop(i).text)
                return

    def continues_the_sequence(number: int) -> bool:
        """Is this the successor of the provision already open?

        The one test that separates a rule number from a figure in a table,
        and the reason the looser heading forms below can be admitted at all.
        """
        if rule is None:
            return number == 1
        last = _TRAILING_NUMBER.search(rule.ref)
        return last is not None and number == int(last.group(1)) + 1

    def opens_an_unheaded_rule(index: int, number: int) -> bool:
        """Does a bare `4.` here open Rule 4, or is it a figure in a table?

        Two things have to hold, and the gazettes need both. The line must
        be followed by sub-rule **(1)** -- not any sub-rule, the first one,
        which is how a provision begins -- and the number must be the
        successor of the rule already open.

        The National Standards Rules are why this exists. Rules 4, 7 and 8
        print their number alone on a line and start straight at `(1)`, so
        no branch claimed them: rule 4's sub-rules were read as a *second*
        `Rule 3(1)` and `Rule 3(2)`, and rule 8's as a second `Rule 6(2)`.
        The base unit of length and the kelvin were filed under the metric
        system rule, which is a wrong citation rather than a missing one.

        That document also has 148 lines that are nothing but a number, so
        neither test can be dropped.
        """
        if not continues_the_sequence(number):
            return False
        for _, following in lines[index + 1 : index + 3]:
            text = following.strip()
            if not text:
                continue
            first = SUB_RULE.match(text)
            return first is not None and first.group(1) == "1"
        return False

    def feed(text: str) -> None:
        """Every line goes into its own unit *and* every unit above it.

        **`schedule_node` is deliberately not in this list.** A rule carries its
        sub-rules because they are one provision read together -- Rule 8(1) and
        its proviso are a single clear-space rule and splitting them is the
        failure this module exists to prevent. A Schedule is not that. It is a
        container of independent specifications, and the General Rules' Eighth
        Schedule is 126 pages of them; carrying its items made a single 416 KB
        chunk whose embedding described its first four hundred words and whose
        `tsvector` approached the type's own one-megabyte ceiling.

        So a Schedule's chunk is its front matter -- the heading, the `[See Rule
        13]`, the Part captions -- and its items are chunks in their own right,
        pointing at it through `parent_ref`.
        """
        for node in (rule, sub, clause, subclause, tail):
            if node is not None:
                node.lines.append(text)

    for index, (page, line) in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        schedule_match = SCHEDULE.match(line)
        if schedule_match:
            ordinal = schedule_match.group(1).upper()
            ordinal = SCHEDULE_SPELLINGS.get(ordinal, ordinal)
            if ordinal in SCHEDULE_ORDINALS:
                close_schedule()
                close(preamble)
                preamble = None
                schedule = ordinal.title()
                schedule_heading = schedule_match.group(2)
                # Division numbering restarts with the Schedule.
                schedule_part = schedule_appendix = None
                schedule_node = _Node(
                    ref=_schedule_ref(schedule, schedule_heading),
                    parent_ref=None,
                    heading="",
                    page=page,
                    kind="schedule",
                    lines=[stripped],
                )
                absorb_index_entry(schedule_node)
                awaiting_heading = schedule_heading is None
                continue

        # `SEVENTHSCHEDULE` then `HEADING-B`: the second half of a heading the
        # column reader split across two lines. Read only on the line directly
        # after the first half, so the ref is settled before anything uses it.
        #
        # The flag, rather than a count of the node's lines: `absorb_index_entry`
        # may already have put a line in, and a positional guard would then
        # silently stop joining and collapse four of the Seventh Schedule's five
        # Headings into one ref.
        if awaiting_heading and schedule_node is not None and schedule is not None:
            heading_match = SCHEDULE_HEADING.match(line)
            if heading_match:
                schedule_heading = heading_match.group(1).upper()
                schedule_node.ref = _schedule_ref(schedule, schedule_heading)
                schedule_node.lines.append(stripped)
                absorb_index_entry(schedule_node)
                awaiting_heading = False
                continue
        awaiting_heading = False

        # `PART V` inside a Schedule. It is not a chunk of its own -- a Part of
        # the Eighth Schedule runs to twenty pages and carrying its items would
        # rebuild the 416 KB chunk `feed` exists to prevent -- but it qualifies
        # every item ref beneath it, which is what makes those refs unique.
        if schedule is not None and schedule_node is not None:
            part_match = SCHEDULE_PART.match(stripped)
            if part_match:
                close_rule()
                # Two alternatives: a numeral, which the gazette may print
                # with no space (`PARTI`), or a letter, which must have a
                # separator before it -- otherwise `PARTS` reads as Part S.
                suffix = part_match.group(2)
                number = part_match.group(1) or part_match.group(3)
                schedule_part = f"Part {number.upper()}"
                if suffix:
                    schedule_part += f"-{suffix.upper()}"
                # An Appendix belongs to the Part it was printed under, so a
                # new Part ends it. Carrying it forward would file the next
                # Part's opening clauses under the previous Part's Appendix.
                schedule_appendix = None
                schedule_node.lines.append(stripped)
                continue

            appendix_match = SCHEDULE_APPENDIX.match(stripped)
            if appendix_match:
                close_rule()
                kind = (appendix_match.group(1) or appendix_match.group(3)).title()
                letter = appendix_match.group(2) or appendix_match.group(4)
                schedule_appendix = f"{kind} {letter.upper()}"
                schedule_node.lines.append(stripped)
                continue

        rule_match = RULE.match(line)
        # No instrument numbers a provision 0. Where one appears it came from a
        # figure in a specification table that happened to sit on its own line,
        # and it accounted for 78 spurious chunks of the General Rules alone.
        if rule_match and rule_match.group(1) == "0":
            rule_match = None
        # `1. 2. 3.` under `Sl. No. | Commodities | Quantities`. See `_NUMBERS_ONLY`.
        if rule_match and _NUMBERS_ONLY.match(rule_match.group(2)):
            rule_match = None
        # `2.0 to 3.5`. See `_DECIMAL`.
        if rule_match and _DECIMAL.match(line):
            rule_match = None
        # `16: Deposit of Models or its drawings.` The colon is admitted only
        # in sequence; see `RULE_COLON`.
        if rule_match is None:
            colon = RULE_COLON.match(line)
            if (
                colon
                and _looks_like_a_heading(colon.group(2))
                and continues_the_sequence(int(colon.group(1)))
            ):
                rule_match = colon

        # A rule the gazette prints without a heading. `_looks_like_a_heading`
        # cannot see one, and before this branch existed the line fell through
        # to the enclosing context and the rule ceased to be citable.
        unheaded = (
            rule_match is not None
            and _BARE_NUMBER.match(line) is not None
            and not _looks_like_a_heading(rule_match.group(2))
            and opens_an_unheaded_rule(index, int(rule_match.group(1)))
        )
        # `2. Definitions`, `11. Weights` -- one word, and still a rule.
        short_heading = (
            rule_match is not None
            and not unheaded
            and not _looks_like_a_heading(rule_match.group(2))
            and _SHORT_HEADING.match(rule_match.group(2).strip()) is not None
            and continues_the_sequence(int(rule_match.group(1)))
        )
        if rule_match and (
            unheaded or short_heading or _looks_like_a_heading(rule_match.group(2))
        ):
            close_rule()
            close(preamble)  # the preamble ends where the first rule begins
            preamble = None
            last_clause = None
            number = rule_match.group(1)
            # An unheaded rule is given no heading rather than a borrowed one.
            # Sub-rule (1) follows on the next line and becomes `Rule N(1)`,
            # which is the citation an officer would actually use.
            heading = "" if unheaded else _HEADING_TAIL.sub("", rule_match.group(2))
            rule = _Node(
                # Inside a Schedule the numbering has restarted, so `7.` is item
                # 7 of that Schedule and emphatically not Rule 7.
                ref=(
                    f"Rule {number}"
                    if schedule is None
                    else _schedule_ref(
                        schedule, schedule_heading, (schedule_part, schedule_appendix)
                    )
                    + f", item {number}"
                ),
                parent_ref=(
                    None if schedule is None else _schedule_ref(schedule, schedule_heading)
                ),
                heading=heading.strip(),
                page=page,
                kind="rule" if schedule is None else "schedule_item",
            )
            # Through `feed`, not `lines=[stripped]`: the heading line belongs
            # to the enclosing Schedule as well as to the item it opens. Seeding
            # the node directly meant every item heading in the Second Schedule
            # — the commodity names themselves — was missing from the Schedule's
            # own chunk. `close_rule` has already cleared sub, clause and tail,
            # so this line reaches exactly the item and its Schedule.
            feed(stripped)
            continue

        if rule is None:
            # Nothing citable is open, but the line is still part of the
            # instrument. Discarding it here is how the Schedules lost their
            # tables: the maximum-permissible-error table of the LMPC Second
            # Schedule, the standard pack sizes, and two thirds of the National
            # Standards Rules are rows that begin with a unit, not with `7.`,
            # so no branch above claims them. They go to the enclosing context
            # instead — the Schedule if one is open, otherwise the preamble.
            #
            # It is not made to look like a rule. `Second Schedule` and
            # `Preamble` are what they are, and a citation to either says so.
            if schedule_node is not None:
                schedule_node.lines.append(stripped)
                continue
            if preamble is None:
                preamble = _Node(
                    ref="Preamble",
                    parent_ref=None,
                    heading="",
                    page=page,
                    kind="preamble",
                )
            preamble.lines.append(stripped)
            continue

        table_match = TABLE.match(line)
        if table_match:
            close_tail()
            numeral = table_match.group(1).upper()
            tail = _Node(
                ref=f"{rule.ref}, Table {numeral}",
                parent_ref=(sub or rule).ref,
                heading=rule.heading,
                page=page,
                kind="table",
            )
            feed(stripped)
            continue

        if PROVISO.match(line):
            close_tail()
            parent = subclause or clause or sub or rule
            # Numbered, so a rule with two provisos does not collapse into one
            # chunk under one key — Rule 9(1)(b) has exactly that shape.
            existing = sum(1 for c in chunks if c.ref.startswith(f"{parent.ref} proviso"))
            suffix = "" if existing == 0 else f" {existing + 1}"
            tail = _Node(
                ref=f"{parent.ref} proviso{suffix}",
                parent_ref=parent.ref,
                heading=rule.heading,
                page=page,
                kind="proviso",
            )
            feed(stripped)
            continue

        if EXPLANATION.match(line):
            close_tail()
            parent = subclause or clause or sub or rule
            tail = _Node(
                ref=f"{parent.ref} explanation",
                parent_ref=parent.ref,
                heading=rule.heading,
                page=page,
                kind="explanation",
            )
            feed(stripped)
            continue

        sub_match = SUB_RULE.match(line)
        if sub_match:
            # A new sub-rule always ends an open proviso, and this is emphatically
            # not optional. Requiring `tail is None` here — which the first
            # version did, by analogy with the clause branch — meant that a rule
            # whose early sub-rule carried a proviso swallowed every sub-rule
            # after it. Eight disappeared, **including Rule 18(5)**: the
            # retailer's offence, the one finding in this system addressed to a
            # different respondent from all the others.
            #
            # The clause branch needs the guard because a proviso genuinely
            # contains lettered clauses — Rule 8(1)'s (a) and (b) *are* the
            # clear-space distances. A proviso never contains a numbered
            # sub-rule; that is what ends it.
            close_sub()
            last_clause = None
            sub = _Node(
                ref=f"{rule.ref}({sub_match.group(1)})",
                parent_ref=rule.ref,
                heading=rule.heading,
                page=page,
                kind="sub_rule",
            )
            feed(stripped)
            continue

        clause_match = CLAUSE.match(line)
        if clause_match and (tail is None or _follows(clause_match.group(1), last_clause)):
            # A lettered clause that *continues the sequence* ends an open
            # proviso; one that restarts at (a) belongs inside it. Rule 2 needs
            # the first reading — its definition (k) carries a proviso, and (l)
            # through (z) follow it, so without this the rule that defines
            # "retail sale price" is filed inside the proviso to "retail
            # package" and `Rule 2(m)` cannot be looked up at all. Rule 8(1)'s
            # proviso needs the second: its (a) and (b) *are* the clear-space
            # distances and must not be lifted out of the proviso that makes
            # them mean anything.
            close_tail()
            token = clause_match.group(1)
            if _is_roman(token, previous=last_clause):
                close_subclause()
                parent = clause or sub or rule
                subclause = _Node(
                    ref=f"{parent.ref}({token})",
                    parent_ref=parent.ref,
                    heading=rule.heading,
                    page=page,
                    kind="sub_clause" if clause is not None else "clause",
                )
            else:
                close_clause()
                # Rule 2 lists its definitions as (a)...(z) directly under the
                # rule, with no sub-rule between. Requiring one dropped the rule
                # that defines "pre-packaged commodity" — which the rulepack
                # cites as Rule 2(m).
                parent = sub or rule
                last_clause = token
                clause = _Node(
                    ref=f"{parent.ref}({token})",
                    parent_ref=parent.ref,
                    heading=rule.heading,
                    page=page,
                    kind="clause",
                )
            feed(stripped)
            continue

        feed(stripped)

    close_schedule()
    close(preamble)
    return chunks


__all__ = [
    "MIN_RULE_HEADING_WORDS",
    "Chunk",
    "chunk_document",
    "restore_ell_marker",
    "restore_roman_markers",
]
