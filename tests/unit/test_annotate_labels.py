"""Every field an exhibit can draw has words a person would use for it.

`evidence/annotate.py` captions each box on the annotated photograph — the
exhibit that goes out with a notice under section 14. `field_label` falls back
to `name.replace("_", " ").capitalize()` for anything it has no entry for, which
is a safety net and not a naming scheme: on 2026-09-19 that fallback was
rendering **"Fssai licence"** on a legal document, because the six non-statutory
names went into `contracts.FieldName` on 2026-09-10 and into the caption table
never.

This is the third place the same drift has been found — the Label Studio config
(`test_prelabel.py`) and this one — so it gets the same treatment: a test that
fails when `contracts` grows a name and a human-facing table does not.
"""

from __future__ import annotations

import typing

import pytest

from contracts import FieldName
from evidence.annotate import FIELD_LABELS, field_label


def test_every_field_has_a_caption_written_for_it():
    missing = sorted(set(typing.get_args(FieldName)) - set(FIELD_LABELS))
    assert not missing, (
        f"{missing} would be captioned by the fallback, which title-cases the "
        f"identifier. That reads as {[field_label(f) for f in missing]} on an "
        f"exhibit. Add them to FIELD_LABELS."
    )


def test_no_caption_is_for_a_field_that_does_not_exist():
    """A caption for a removed field is dead text nobody will notice is dead."""
    declared = set(typing.get_args(FieldName))
    stray = sorted(set(FIELD_LABELS) - declared)
    assert not stray, f"FIELD_LABELS captions {stray}, which contracts does not define"


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        # The one that was wrong on a document. An acronym is not a word to be
        # title-cased.
        ("fssai_licence", "FSSAI licence"),
        ("mrp", "MRP"),
        # And the ones whose identifier reads nothing like the thing.
        ("nutrition", "Nutritional information"),
        ("storage_use", "Storage or usage instruction"),
        ("other", "Unclassified text"),
    ],
)
def test_the_captions_that_the_fallback_would_get_wrong(field, expected):
    assert field_label(field) == expected


def test_an_unknown_name_still_captions_rather_than_raising():
    """The fallback stays. An exhibit with one oddly-worded box beats an
    exhibit that failed to render because a field was added upstream."""
    assert field_label("some_future_field") == "Some future field"


# ---------------------------------------------------------------------------
# And the same table on the other side of the wire
# ---------------------------------------------------------------------------


def _web_field_labels() -> dict[str, str]:
    """Parse `FIELD_LABELS` out of `web/src/lib/format.ts`.

    Read as text rather than executed, the way `tests/test_boundaries.py` reads
    imports and `tests/unit/test_schema.py` reads SQL: there is no JavaScript
    test runner in this project, and the drift is worth catching anyway.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    source = (root / "web" / "src" / "lib" / "format.ts").read_text(encoding="utf-8")
    body = re.search(
        r"export const FIELD_LABELS: Record<string, string> = \{(.*?)\n\};", source, re.S
    )
    assert body, "FIELD_LABELS is no longer declared the way this test parses it"
    return dict(re.findall(r'^\s*(\w+):\s*"([^"]*)",\s*$', body.group(1), re.M))


def test_the_browser_calls_every_field_what_the_exhibit_calls_it():
    """The screen and the printed exhibit are the same scan, so they say the same words.

    Four places in the web app rendered a field by `field.replace(/_/g, " ")`,
    so an officer comparing the screen against the exhibit saw `fssai licence`
    on one and `FSSAI licence` on the other. A difference in wording between a
    document and the tool that produced it is the kind of thing that gets asked
    about in a hearing, and the answer "they are the same, it is just styling"
    is one nobody should have to give.
    """
    assert _web_field_labels() == FIELD_LABELS


# ---------------------------------------------------------------------------
# And the order the key panel puts them in
# ---------------------------------------------------------------------------


def test_every_field_belongs_to_a_family_in_the_key():
    """The same drift, one table further along.

    `FAMILIES` decides which heading a declaration is listed under on the
    exhibit. A field missing from it still gets drawn and still gets a row --
    it falls to "Other declarations" -- but an exhibit that files the MRP under
    "Other declarations" is one a reader has to be told to ignore.
    """
    from evidence.annotate import FAMILIES

    placed = {field for _title, fields in FAMILIES for field in fields}
    declared = set(typing.get_args(FieldName)) - {"other"}

    assert not sorted(declared - placed), (
        f"{sorted(declared - placed)} would be listed under 'Other declarations'"
    )
    assert not sorted(placed - declared), (
        f"FAMILIES files {sorted(placed - declared)}, which contracts does not define"
    )


def test_no_field_is_filed_under_two_headings():
    from evidence.annotate import FAMILIES

    seen: list[str] = [field for _title, fields in FAMILIES for field in fields]
    assert len(seen) == len(set(seen))


def test_the_address_block_is_a_subset_of_the_name_and_address_family():
    """The region drawn on the photograph and the heading in the key have to
    agree, or the exhibit brackets four boxes and lists them apart."""
    from evidence.annotate import ADDRESS_BLOCK, FAMILIES

    family = next(fields for title, fields in FAMILIES if title == "Name and address")
    assert set(ADDRESS_BLOCK) <= set(family)
