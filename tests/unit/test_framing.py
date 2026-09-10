"""B1's second half — was the declaration panel in shot? AKSHAR.md section 8.

**These are not the acceptance tests either**, for the same reason as
`test_quality_gate.py`: the labelled set that would give `SPARSE_REGIONS` a
recall figure is the 40-50 declaration-block photographs still to come from the
field. What is asserted here is the behaviour the module must have for any
threshold to mean anything — and, more importantly, the three things it must
never do.

The load-bearing tests are the last three. A framing signal that leaks into a
verdict is worse than no framing signal at all: it hands every under-declared
package the excuse that we were probably looking the wrong way.
"""

from __future__ import annotations

from contracts import FRAMING_ADVICE, Framing
from tests.unit.test_check_sweep import declaration, declaration_set
from vision.quality import assess_framing
from vision.quality.framing import RULE_6_1_DECLARATIONS, SPARSE_REGIONS


def test_a_panel_naming_declarations_raises_no_fault() -> None:
    result = assess_framing(
        declaration_set(declaration("mrp"), declaration("net_quantity")), line_count=54
    )
    assert result.shows_declarations
    assert result.fault is None
    assert result.reason is None
    assert result.mandatory_found == 2
    assert result.advice() == ()


def test_a_sparse_frame_naming_nothing_is_told_to_turn_the_pack_over() -> None:
    """41 of the corpus's 122 frames. Sharp, well lit, and of the brand face."""
    result = assess_framing(declaration_set(), line_count=SPARSE_REGIONS - 1)
    assert not result.shows_declarations
    assert result.fault == "no_declaration_panel"
    assert result.reason == FRAMING_ADVICE["no_declaration_panel"]


def test_a_dense_frame_naming_nothing_is_not_told_to_turn_the_pack_over() -> None:
    """The nutrition-table frames: 62 confident lines, not one of them a
    declaration. "Turn the pack over" is wrong advice for someone already
    looking at the back, and it is the advice that earns a second photograph
    with the same fault."""
    result = assess_framing(declaration_set(), line_count=SPARSE_REGIONS + 40)
    assert result.fault == "wrong_panel"
    assert result.reason == FRAMING_ADVICE["wrong_panel"]
    assert "turn the pack" not in (result.reason or "").lower()


def test_the_two_faults_give_different_advice() -> None:
    assert FRAMING_ADVICE["no_declaration_panel"] != FRAMING_ADVICE["wrong_panel"]
    assert all(text.strip() for text in FRAMING_ADVICE.values())


def test_a_non_mandatory_field_alone_does_not_count_as_a_panel() -> None:
    """`batch` and `country_of_origin` are printed all over a pack, including on
    the face. Finding one is not evidence the declaration block is in shot."""
    result = assess_framing(
        declaration_set(declaration("batch", text="Batch No. A2291")), line_count=8
    )
    assert not result.shows_declarations
    assert result.fault == "no_declaration_panel"


def test_one_mandatory_declaration_is_enough_to_stop_second_guessing_the_aim() -> None:
    result = assess_framing(declaration_set(declaration("mrp")), line_count=4)
    assert result.shows_declarations
    assert result.fault is None


# ---------------------------------------------------------------------------
# What it must never do
# ---------------------------------------------------------------------------


def test_a_partly_read_panel_is_never_called_a_framing_fault() -> None:
    """The whole point of the zero-versus-nonzero line.

    A frame naming two of six may be a clipped panel or may be a package that
    genuinely declares two of six, and nothing available to us separates them.
    Calling the first a framing fault would give the second an alibi.
    """
    for count in range(1, len(RULE_6_1_DECLARATIONS)):
        fields = sorted(RULE_6_1_DECLARATIONS)[:count]
        result = assess_framing(
            declaration_set(*[declaration(f) for f in fields]), line_count=3
        )
        assert result.fault is None, f"{count} of six was reported as a framing fault"


def test_it_never_returns_a_verdict() -> None:
    """It measures the photograph, never the package. Same wall as B1."""
    result = assess_framing(declaration_set(), line_count=2)
    assert isinstance(result, Framing)
    for forbidden in ("status", "severity", "rule_id", "compliant", "verdict"):
        assert not hasattr(result, forbidden)


def test_no_rule_reads_framing() -> None:
    """`rules/` decides; `vision/` measures. `reading_supports_an_absence`
    withdraws the inference from silence against the live rulepack, and it must
    stay the only thing that does."""
    from pathlib import Path

    offenders = [
        path
        for path in Path("rules").rglob("*.py")
        if "framing" in path.read_text(encoding="utf-8").lower()
    ]
    assert offenders == []


def test_it_is_frozen() -> None:
    result = assess_framing(declaration_set(), line_count=2)
    try:
        result.fault = "wrong_panel"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Framing must be immutable")
