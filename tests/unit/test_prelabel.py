"""The Label Studio config against `contracts`. AKSHAR.md sections 14 and 16.

`training/detector/label_config.xml` opens with a claim:

    "Every label value is a member of a contracts Literal ... If a name below
     and a name in contracts/ ever disagree, contracts/ is right and
     tests/unit/test_prelabel.py fails."

**That file did not exist.** The guard was asserted in a comment and never
written, and on 2026-09-18 the drift it was meant to catch was found by hand:
`nutrition`, `ingredients`, `storage_use`, `fssai_licence`, `barcode` and
`unit_sale_price` had been in `contracts.FieldName` since 2026-09-10 and in the
annotation tool never.

The cost of that gap is not a crash. It is silent and it is paid by a person: an
annotator meeting an FSSAI licence number has no way to say so, records it as
`other`, and the label is indistinguishable from "I could not read this" — which
is the exact confusion the six names were added to end. Several hundred
photographs of that is work that cannot be recovered afterwards, because nobody
can tell later which `other` meant which.

So the comment is now true.
"""

from __future__ import annotations

import re
import typing
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from contracts import FieldName, PanelId, Script

CONFIG = Path(__file__).resolve().parents[2] / "training" / "detector" / "label_config.xml"

#: Labels in the `objects` group are detector classes, not declaration fields,
#: and have no `contracts` Literal of their own.
OBJECT_LABELS = frozenset({"package", "marker_card"})


@pytest.fixture(scope="module")
def groups() -> dict[str, set[str]]:
    """Every label value in the config, keyed by the control that owns it."""
    root = ET.fromstring(CONFIG.read_text(encoding="utf-8"))
    found: dict[str, set[str]] = {}
    for control in root:
        name = control.get("name")
        if name is None:
            continue
        values = {
            child.get("value")
            for child in control
            if child.tag in {"Label", "Choice"} and child.get("value")
        }
        if values:
            found[name] = values  # type: ignore[assignment]
    return found


def test_the_config_parses_at_all(groups):
    """A malformed config is pasted into Label Studio and rejected there, which
    is a worse place to find out than here."""
    assert set(groups) == {"objects", "panels", "declarations", "script"}


def test_every_declaration_label_is_a_contracts_field(groups):
    """A label typed `manufacture` draws a box that `convert.py` throws away."""
    declared = set(typing.get_args(FieldName))
    unknown = groups["declarations"] - declared
    assert not unknown, (
        f"these labels are not in contracts.FieldName: {sorted(unknown)}. "
        f"contracts/ is right; fix the config."
    )


def test_every_contracts_field_can_be_drawn(groups):
    """The direction that actually bit, and the expensive one.

    A field the pipeline can produce but the annotator cannot select is not a
    crash — it is an annotator recording it as `other` a few hundred times, and
    `other` already means "I could not read this". The two are then
    indistinguishable forever.
    """
    missing = set(typing.get_args(FieldName)) - groups["declarations"]
    assert not missing, (
        f"contracts.FieldName carries {sorted(missing)} and the annotation tool "
        f"offers no way to say so. Every one of these would be recorded as "
        f"`other`, which already means something else."
    )


def test_every_panel_label_is_a_contracts_panel(groups):
    declared = set(typing.get_args(PanelId))
    assert groups["panels"] <= declared, sorted(groups["panels"] - declared)


def test_every_panel_can_be_drawn(groups):
    missing = set(typing.get_args(PanelId)) - groups["panels"]
    assert not missing, f"no polygon label for panel(s) {sorted(missing)}"


def test_script_choices_match_contracts(groups):
    assert groups["script"] == set(typing.get_args(Script))


def test_the_object_labels_are_the_two_the_detector_knows(groups):
    assert groups["objects"] == OBJECT_LABELS


def test_no_label_is_offered_twice(groups):
    """Two entries with the same value render as two buttons that do the same
    thing, and an annotator who uses both has no way to know they agreed."""
    text = CONFIG.read_text(encoding="utf-8")
    values = re.findall(r'<(?:Label|Choice) value="([^"]+)"', text)
    duplicates = {v for v in values if values.count(v) > 1}
    # `other` is legitimately in both `declarations` and `script`.
    assert duplicates <= {"other"}, f"duplicated label values: {sorted(duplicates)}"


def test_the_config_still_claims_this_test_guards_it(groups):
    """The comment that was false for nine days.

    If someone removes the claim, they should also decide whether to remove the
    guard; if someone removes the guard, this fails first.
    """
    assert "test_prelabel.py" in CONFIG.read_text(encoding="utf-8")
