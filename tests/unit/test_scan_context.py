"""`ScanContext` — additive-only, one named slot per block. AKSHAR.md 8b.

    "Additive-only is what makes a finding reproducible six months later. If B9
     could overwrite B7's output, we could not show what the system actually
     read."

The guarantee is asserted here rather than trusted: there is no setter on the
context and no setter on `ScanOutcome`, so a block's output cannot be replaced
by any code path at all.
"""

from __future__ import annotations

import dataclasses

import pytest

from contracts import CaptureQuality, Framing
from tests.unit.conftest import make_declaration, make_set
from vision.context import ScanContext
from vision.degradation import Degradation
from vision.pipeline import ScanOutcome
from vision.types import Identity


def outcome(
    *,
    declarations=None,
    exit_path="full",
    message="",
    tier="L0",
    quality=None,
    framing=None,
) -> ScanOutcome:
    return ScanOutcome(
        exit_path=exit_path,
        identity=Identity(),
        degradation=Degradation(tier=tier),
        declarations=declarations,
        quality=quality,
        framing=framing,
        message=message,
    )


def panel_frame(fields=("mrp", "net_quantity", "manufacturer")):
    return outcome(
        declarations=make_set([make_declaration(f, f"{f} text") for f in fields])
    )


# ---------------------------------------------------------------------------
# Additive-only
# ---------------------------------------------------------------------------


def test_adding_a_frame_returns_a_new_context_and_leaves_the_old_one_alone():
    first = ScanContext(scan_id="s1")
    second = first.add(panel_frame())
    assert first.frame_count == 0
    assert second.frame_count == 1
    assert second is not first


def test_frames_can_only_grow():
    context = ScanContext(scan_id="s1").add(panel_frame()).add(panel_frame(("batch",)))
    assert context.frame_count == 2
    assert context.frames[0].declarations is not None


def test_nothing_can_overwrite_a_block_because_nothing_can_assign_to_one():
    """The guarantee is structural: both objects are frozen."""
    context = ScanContext(scan_id="s1").add(panel_frame())
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.frames = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.frames[0].declarations = None  # type: ignore[misc]


def test_there_is_no_setter_for_any_slot():
    """A named slot is read off the primary frame; it is never written here."""
    for name in ("quality", "framing", "scale", "declarations", "recognised_regions"):
        assert isinstance(getattr(ScanContext, name), property)
        assert getattr(ScanContext, name).fset is None


# ---------------------------------------------------------------------------
# Which frame answers for the pack
# ---------------------------------------------------------------------------


def test_the_primary_frame_is_the_one_showing_the_declaration_panel():
    face = outcome(declarations=make_set([make_declaration("marketing_text", "TASTY")]))
    panel = panel_frame()
    context = ScanContext.of("s1", [face, panel])
    assert context.primary_index == 1
    assert context.primary is panel


def test_a_frame_that_read_nothing_stays_in_the_record():
    """Three photographs of which one was unusable is not a scan of two."""
    blurred = outcome(
        exit_path="unusable",
        message="Hold the camera still.",
        quality=CaptureQuality(
            usable=False,
            blur_score=0.05,
            glare_ratio=0.0,
            exposure_score=0.9,
            width=1600,
            height=1200,
            faults=("blur",),
            reason="Hold the camera still.",
        ),
    )
    context = ScanContext.of("s1", [panel_frame(), blurred])

    assert context.frame_count == 2
    assert context.read_frames == (0,)
    assert context.unread_frames() == ((1, "Hold the camera still."),)
    assert context.declarations is not None
    assert context.declarations.frame_count == 1


def test_a_scan_where_no_frame_read_anything_has_no_declarations():
    """The multi-frame form of L4: a record, and nothing that could be judged."""
    context = ScanContext.of(
        "s1",
        [outcome(exit_path="no_package", message="No packaged product found.")] * 2,
    )
    assert context.declarations is None
    assert context.primary_index is None
    assert context.primary is not None  # there is still a frame to report on


def test_the_union_numbers_declarations_by_the_shot_the_officer_took():
    """Frame 1 was rejected, so what came out of the third shot is frame 2."""
    blurred = outcome(exit_path="unusable", message="Hold the camera still.")
    context = ScanContext.of(
        "s1",
        [panel_frame(("mrp",)), blurred, panel_frame(("net_quantity",))],
    )
    declarations = context.declarations
    assert declarations is not None
    assert {d.frame_id for d in declarations.declarations} == {0, 2}


# ---------------------------------------------------------------------------
# The named slots
# ---------------------------------------------------------------------------


def test_the_named_slots_read_the_primary_frame():
    quality = CaptureQuality(
        usable=True, blur_score=0.9, glare_ratio=0.0, exposure_score=0.9,
        width=2000, height=1500,
    )
    framing = Framing(
        shows_declarations=True, mandatory_found=3, mandatory_expected=6, text_regions=54
    )
    face = outcome(declarations=make_set([make_declaration("marketing_text", "TASTY")]))
    panel = ScanOutcome(
        exit_path="full",
        identity=Identity(),
        degradation=Degradation(tier="L0"),
        declarations=make_set(
            [make_declaration(f, f) for f in ("mrp", "net_quantity", "manufacturer")]
        ),
        quality=quality,
        framing=framing,
    )
    context = ScanContext.of("s1", [face, panel])

    assert context.quality is quality
    assert context.framing is framing
    assert context.product_match is panel.identity
