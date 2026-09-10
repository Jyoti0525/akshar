"""Cleaning gazette text without editing it. AKSHAR.md section 15.

The extracted text of the Packaged Commodities Rules carries spaces *inside*
words — "the decl aration", "principal display panel [...] capac ity", "conf
erred". That is not an extraction bug: the same artefact comes out of `pypdf`
and out of the text file already in `data/rulebook/extracted/`, because the
spacing is in the PDF's own text layer, which positions glyphs individually.

**This matters more here than it would anywhere else in the system.** Tier 1
retrieval shows an officer the verbatim clause behind a verdict, and verbatim is
the entire value of it — §15: *"The verbatim clause is the actual authority."* A
statute displayed as "the decl aration shall be legible" undermines the one
feature whose selling point is that no model wrote it.

**So the repair is deliberately incapable of inventing a word.** A space between
two fragments is closed only when the joined form appears in this corpus **more
often than either fragment does**. There is no dictionary and no model: the
document is its own authority, so the repair can only restore a word the statute
already uses, and only when the evidence says the fragments are debris.

The frequency test rather than a plain "is this a word" test, because the
artefacts repeat. "hei" occurs several times across the document — a membership
check would therefore accept it as a word of the corpus and refuse the repair,
which is exactly what the first version of this module did. Counting settles it:
`height` appears 10 times against `hei` once and `ght` three times, so the join
is evidence-backed. `of`/`fice` fails immediately — `of` appears 618 times and
`office` once — and `any`/`where` fails because `anywhere` never appears at all.

It is deliberately conservative and leaves some artefacts in place. "perforate
d" survives, because `perforated` (3) is rarer than `d` (18) and the rule has no
way to know which `d` is which. A visible artefact is a much smaller problem
than a silently altered statute.

Nothing else is corrected apart from `restore_ascii_punctuation`, which is a
codepoint substitution and not an edit. Hyphenation, capitalisation, the
numbering and the wording are left exactly as extracted, and the page number travels with every
chunk so a reader can check the gazette.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

PAGE_MARKER = re.compile(r"^<<<PAGE\s+(\d+)>>>\s*$")
PAGE_FOOTER = re.compile(r"^\s*Page\s+\d+\s+of\s+\d+\s*$", re.IGNORECASE)

RUNNING_HEAD = re.compile(
    r"^\s*\d{0,4}\s*THE\s*GAZETTE\s*OF\s*IND"
    r"|^\s*\[?\s*PART\s*I{1,3}\b"
    r"|^\s*Printed\s+by\s+the\s+Manager"
    r"|^\s*(and\s+)?Published\s+by\s+the\s+Controller",
    re.IGNORECASE,
)
"""The masthead printed at the top of every gazette page.

Harmless in a text layer, where it is one tidy line. Corrosive after OCR: the
recogniser drops the spaces (`THEGAZETTEOFINDIA:EXTRAORDINARY`), mangles the
letters (`THE GAZETTEOFINDLA`), and emits it as a separate line on all 838
pages — where it lands *inside* whichever clause spans the page break, and
turns up in every search for words the statute never used.

Matched loosely on purpose. This is running furniture with no legal content, so
over-matching costs a line of boilerplate and under-matching puts noise in a
corpus whose only value is being verbatim.
"""

_WORD = re.compile(r"[A-Za-z]+")
_SPLIT_PAIR = re.compile(r"\b([A-Za-z]{1,12}) (?=([A-Za-z]{1,12})\b)")
"""The right fragment is matched in a **lookahead**, and that is not a stylistic
choice — it is the difference between repairing four words and repairing eighty.

`re.sub` resumes scanning after the end of a match. Consuming both fragments
means that once "the decl" has been tested and rejected, the scan has already
moved past "decl", so the pair that actually needed joining — "decl aration" —
is never examined at all. Every artefact preceded by a short ordinary word was
invisible to the first version of this module for exactly that reason, and the
repair count looked plausible the whole time."""

def vocabulary(text: str) -> Counter[str]:
    """How often this document uses each word, lower-cased.

    Counts rather than a set: membership cannot tell a word from a repeated
    artefact, and the artefacts repeat. See the module docstring.
    """
    return Counter(match.group(0).lower() for match in _WORD.finditer(text))


def repair_spacing(text: str, words: Counter[str]) -> tuple[str, int]:
    """Close spaces that split a word. Returns the text and how many were closed.

    The count is returned rather than logged because `scripts/build_rulebook.py`
    prints it: a repair pass on legal text should say how much it changed, and a
    number that suddenly jumps after a corpus update is worth looking at before
    the result is shipped to officers.
    """
    repairs = 0

    def join(match: re.Match[str]) -> str:
        nonlocal repairs
        left, right = match.group(1), match.group(2)
        merged = words[(left + right).lower()]
        if merged <= words[left.lower()] or merged <= words[right.lower()]:
            return match.group(0)
        repairs += 1
        # Only the space is consumed, so the right fragment stays in the stream
        # and can itself be the left half of the next join.
        return left

    # Two passes: a word broken twice ("declara tio ns") needs the first join
    # before the second becomes visible. Two is enough for everything in this
    # corpus and a fixed number cannot loop.
    for _ in range(2):
        text = _SPLIT_PAIR.sub(join, text)
    return text, repairs


_FULLWIDTH = {chr(code): chr(code - 0xFEE0) for code in range(0xFF01, 0xFF5F)}
"""Every character of the fullwidth block, mapped back to its ASCII twin.

U+FF01-FF5E is a one-to-one compatibility copy of printable ASCII, so the
arithmetic is the whole mapping and there is no table to keep in step.
"""

_CJK_PUNCTUATION = {"\u3001": ",", "\u3002": ".",
                    "\u3010": "[", "\u3011": "]"}

_ASCII_FORMS = str.maketrans(_FULLWIDTH | _CJK_PUNCTUATION)


def restore_ascii_punctuation(text: str) -> str:
    """Undo the recogniser's habit of setting `(1)` with a fullwidth bracket.

    PP-OCR was trained on Chinese as well as English and reaches for the CJK
    codepoint when a bracket is a little wide, so the gazettes come out with
    212 fullwidth left brackets, 170 right, and a scattering of commas,
    colons and full stops in the same forms.

    **This is not a correction to the statute.** The gazette printed ASCII;
    the recogniser chose a different codepoint for the same glyph, and this
    puts it back. What it costs to leave alone is concrete: `SUB_RULE` reads
    an ASCII bracket, so thirteen sub-rules never opened -- among them
    National Standards r. 8(1), the kelvin, whose whole rule was then filed
    under r. 6, the second.

    Restricted to a codepoint map rather than `unicodedata.normalize`,
    because NFKC would also rewrite `m²` as `m2`. That is a superscript in
    the Second Schedule's definition of the unit of area, and flattening it
    would change what the clause says rather than how it was encoded.
    """
    return text.translate(_ASCII_FORMS)

def strip_page_furniture(lines: Iterable[str]) -> list[tuple[int, str]]:
    """Drop page markers and running footers, keeping the page each line sits on.

    The page number is kept rather than discarded because it is what makes a
    retrieved clause checkable: an officer who doubts the text can open the
    gazette at that page. A citation with no page is a claim about a document
    rather than a pointer into one.
    """
    kept: list[tuple[int, str]] = []
    page = 1
    for raw in lines:
        marker = PAGE_MARKER.match(raw)
        if marker:
            page = int(marker.group(1))
            continue
        if RUNNING_HEAD.match(raw):
            continue
        if PAGE_FOOTER.match(raw):
            continue
        kept.append((page, raw.rstrip()))
    return kept


def tidy(text: str) -> str:
    """Collapse the wrapping the PDF imposed, keep the words as they are."""
    return re.sub(r"[ \t]+", " ", text.replace("\n", " ")).strip()


__all__ = [
    "repair_spacing",
    "restore_ascii_punctuation",
    "strip_page_furniture",
    "tidy",
    "vocabulary",
]
