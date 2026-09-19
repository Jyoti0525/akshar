"""What a printed date looks like, in one place.

Two modules need this and they cannot import each other: `associate` imports
`FieldGuess` from `regex_tier`, so `regex_tier` importing `associate` would
close the loop. Before this module existed the grammar lived only in
`associate`, and `regex_tier` had no notion of a date at all -- which is how it
came to call one a barcode.

**The bug that moved it here.** `regex_tier` strips the marks OCR invents
inside a barcode before testing the length, hyphens and full stops among them,
because a scanned EAN comes back as `'8901537"024014'` often enough to matter.
That strip turns `09-08-2023` into `09082023`: eight digits, exactly the length
of an EAN-8. Any date printed `DD-MM-YYYY` was therefore a barcode as far as
classification was concerned.

It stayed invisible while such dates arrived welded to their neighbours in one
unreadable region. `vision.ocr.split` un-welds them, and the first thing the
newly separated dates did was disappear into `barcode` -- where nothing can use
them, because association only considers lines left as `other`.

So the length rule was never wrong; it simply had no way to ask whether the
thing it was about to name had already said what it was.
"""

from __future__ import annotations

import re

DAY = r"(?:0?[1-9]|[12]\d|3[01])"
MONTH = r"(?:0?[1-9]|1[0-2])"

YEAR = r"(?:19\d{2}|20\d{2}|[2-9]\d|1[5-9])"
"""Four digits, or two digits from 15 on.

A two-digit year below 15 is not a year on a pack in circulation, and admitting
one turns `342-00` and `92.00` into dates. That was the single largest source
of cross-matching when these patterns were first drawn."""

SEP = r"\s*[/.\->]\s*"
"""`>` is in there because the recogniser reads a slash as one often enough to
matter -- `'1 PKD. : 29>7/20'` on `parleg.jpg`."""

MONTH_NAME = r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*"

DATE_CORE = (
    rf"{DAY}{SEP}{MONTH}{SEP}{YEAR}"
    rf"|\d{{0,2}}\s*{MONTH_NAME}\s*[.\-/]?\s*{YEAR}"
    rf"|{DAY}\s*{SEP}?\s*{MONTH_NAME}{SEP}{YEAR}"
    rf"|{MONTH}{SEP}{YEAR}"
)
"""The alternation with no boundary guards, for anchored matching."""

DATE = rf"(?<![\d])(?:{DATE_CORE})(?![\d])"
"""The guarded form, for searching a line."""

IS_DATE = re.compile(rf"(?i)\A\s*(?:{DATE_CORE})\s*\Z")
"""Is this fragment a date and nothing else?

Whole-string on purpose. `regex_tier` uses it to decline naming something a
barcode, and a date appearing *inside* a longer string says nothing about what
that string is -- `'MFD 09-08-2023 LOT 4471'` is neither a date nor a barcode.
"""


def is_date(text: str) -> bool:
    """True where the whole fragment is one printed date."""
    return bool(IS_DATE.match(text))


__all__ = [
    "DATE",
    "DATE_CORE",
    "DAY",
    "IS_DATE",
    "MONTH",
    "MONTH_NAME",
    "SEP",
    "YEAR",
    "is_date",
]
