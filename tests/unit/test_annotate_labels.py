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
