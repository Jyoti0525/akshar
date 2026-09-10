"""Ten fixed scenes, one committed snapshot each. AKSHAR.md §18.

    "Golden-file tests run the full pipeline over ten fixed photos and assert
     the DeclarationSet matches a committed JSON snapshot. This is how we catch
     a model update silently changing behaviour."                        -- §18

    pytest tests/golden -q
    AKSHAR_UPDATE_GOLDEN=1 pytest tests/golden -q     # re-record, then READ the diff

---------------------------------------------------------------------------
WHY THE SCENES ARE DRAWN AND NOT PHOTOGRAPHED
---------------------------------------------------------------------------
Section 18 says "ten fixed photos", and the honest reading of *fixed* is the
constraint that matters: the same bytes in, every run, on every machine, for
years. The corpus cannot supply that. `data/corpus/` is gitignored -- 900 MB of
photographs that are partly personal -- so a CI runner has none of them, and a
golden test that skips on the machine where regressions are actually caught is
not a golden test.

`tests/unit/synthetic.py` draws deterministic scenes with known ground truth,
and it already exists for exactly this reason. Its own docstring makes the
distinction this file inherits: *"correctness and accuracy are different
questions"*. These snapshots pin **correctness** -- that a change to the
detector, the recogniser, the classifier or the assembler did not silently move
what the pipeline believes. They say nothing about millimetre accuracy, which is
`data/test_split/`'s job and is sealed.

The corpus-backed variant is a real thing to want, and it is `--corpus`-marked
elsewhere rather than smuggled in here where it would fail on every clean
checkout.

---------------------------------------------------------------------------
WHAT IS IN A SNAPSHOT, AND WHAT IS DELIBERATELY NOT
---------------------------------------------------------------------------
A snapshot must fail when behaviour changes and must not fail when nothing
changed. Three things are excluded because they move on their own:

* **timings** -- a benchmark's job, and `bench/` already fails the build on
  those.
* **`captured_at`** -- a clock.
* **absolute pixel coordinates** -- rounded hard, to 1 px. OpenCV's warp is
  bit-identical for a given version but not across them, and a snapshot that
  broke on an OpenCV patch release would be re-recorded without being read,
  which is how a golden suite stops being one.

**Confidences are rounded to two decimals rather than dropped.** A recogniser
update that moves a confidence from 0.97 to 0.62 has changed behaviour even
though the text is identical, and that is precisely the *silent* change section
18 wants caught.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.unit.synthetic import blank_label, draw_marker, draw_text, on_canvas, photograph
from vision.ocr import detect_text
from vision.pipeline import scan, scan_listing_text

SNAPSHOTS = Path(__file__).parent / "snapshots"
UPDATING = os.environ.get("AKSHAR_UPDATE_GOLDEN") == "1"

pytestmark = pytest.mark.golden


# ---------------------------------------------------------------------------
# The ten scenes
# ---------------------------------------------------------------------------


def _label(lines, *, marker=True, tilt=0.10, yaw=0.06, bg=245):
    """A label carrying `lines` of (text, baseline_y, cap_px), photographed.

    One builder for every scene, so a scene differs from its neighbours only in
    the data below and a reader can see what each one is testing.
    """
    label = blank_label(bg=bg)
    for text, baseline, cap in lines:
        draw_text(label, text, baseline=(60, baseline), cap_px=cap)
    canvas = on_canvas(label)
    if marker:
        draw_marker(canvas, centre=(1010, 700), edge_px=110)
    shot, _homography = photograph(canvas, tilt=tilt, yaw=yaw)
    return shot


COMPLIANT = [
    ("MRP Rs. 45.00", 120, 34),
    ("NET WT 250 g", 210, 26),
    ("MFG 03/2026", 300, 20),
    ("Parle Products Pvt Ltd", 380, 18),
]

SCENES: dict[str, dict] = {
    # 1. The happy path. Everything present, flat, marker in frame.
    "compliant_flat_label": {"lines": COMPLIANT},
    # 2. No MRP at all. The rules engine must reach NO_DATA rather than invent
    #    one, and the extractor must not label something else `mrp` to fill the
    #    hole -- section 8b's "NO_DATA is never a guess".
    "no_mrp_declared": {"lines": [line for line in COMPLIANT if not line[0].startswith("MRP")]},
    # 3. The trap section 14 names first. A promotional graphic printed larger
    #    than the real MRP. If `Rs. 20 OFF` ever becomes the mrp declaration,
    #    this snapshot changes and somebody has to explain why.
    "marketing_text_larger_than_mrp": {
        "lines": [("Rs. 20 OFF", 110, 44), *COMPLIANT],
    },
    # 4. A batch code containing the literal string MRP. Section 14's table.
    "batch_code_contains_mrp": {"lines": [*COMPLIANT, ("BATCH 24MRP07", 450, 18)]},
    # 5. Two quantity-shaped strings, one of which is the legal one.
    "drained_weight_beside_net": {
        "lines": [*COMPLIANT, ("DRAINED WT 350 g", 450, 22)],
    },
    # 6. Bilingual. Section 16 wants >=25% of the corpus like this, and a
    #    Devanagari run must not corrupt the Latin declarations beside it.
    "bilingual_declarations": {
        "lines": [
            ("MRP Rs. 45.00", 120, 34),
            ("NET WT 250 g", 210, 26),
            ("BHARAT ME NIRMIT", 300, 22),
        ],
    },
    # 7. No marker card. Scale tier C: the three min_height_mm rules go dark and
    #    every presence, format and placement check still runs. Section 17 M2.
    "no_marker_tier_c": {"lines": COMPLIANT, "marker": False},
    # 8. Photographed hard off-axis. Rectification has real work to do, and the
    #    boxes must still land on the right strings afterwards.
    "steep_perspective": {"lines": COMPLIANT, "tilt": 0.22, "yaw": 0.16},
    # 9. Low-contrast kraft paper -- section 14's fourth predicted OCR failure.
    #    Not expected to read perfectly; expected to fail the *same way* twice.
    "low_contrast_kraft": {"lines": COMPLIANT, "bg": 168},
    # 10. Print at 8 px cap height. The declarations are present and small, so
    #     the interesting output is whether they are read at all -- this is the
    #     scene that moves when the recogniser is fine-tuned.
    "small_print": {"lines": [(text, y, 8) for text, y, _cap in COMPLIANT]},
}


# ---------------------------------------------------------------------------
# Snapshotting
# ---------------------------------------------------------------------------


def _round(value, places: int):
    return None if value is None else round(float(value), places)


def snapshot_of(outcome) -> dict:
    """The stable part of a `ScanOutcome`. See the module docstring for exclusions."""
    body: dict = {
        "exit_path": outcome.exit_path,
        "degradation_tier": outcome.degradation.tier,
        "degradation_reasons": sorted(outcome.degradation.reasons),
    }
    if outcome.quality is not None:
        body["quality"] = {
            "usable": outcome.quality.usable,
            "faults": sorted(outcome.quality.faults),
            # One decimal: the gate's own thresholds are far coarser than this,
            # so a change big enough to matter is visible and a change smaller
            # than this cannot flip a decision.
            "blur_score": _round(outcome.quality.blur_score, 2),
            "glare_ratio": _round(outcome.quality.glare_ratio, 2),
            "exposure_score": _round(outcome.quality.exposure_score, 2),
        }

    declarations = outcome.declarations
    if declarations is None:
        body["declarations"] = None
        return body

    body["coverage"] = _round(declarations.coverage, 2)
    body["source"] = declarations.source
    body["declaration_count"] = len(declarations.declarations)
    body["declarations"] = [
        {
            "field": declaration.field,
            "text": declaration.text,
            "script": declaration.script,
            "ocr_confidence": _round(declaration.ocr_confidence, 2),
            "field_confidence": _round(declaration.field_confidence, 2),
            "scale_tier": declaration.scale_tier,
            # 1 px, and see the docstring: a warp is not bit-stable across
            # OpenCV releases and a golden file nobody trusts is worse than none.
            "box": [
                round(declaration.box.x),
                round(declaration.box.y),
                round(declaration.box.w),
                round(declaration.box.h),
            ]
            if declaration.box
            else None,
            "height_mm": _round(declaration.height_mm, 2),
            "height_mm_tolerance": _round(declaration.height_mm_tolerance, 2),
        }
        for declaration in declarations.declarations
    ]
    return body


def compare(name: str, produced: dict) -> None:
    path = SNAPSHOTS / f"{name}.json"
    serialised = json.dumps(produced, indent=1, sort_keys=True, ensure_ascii=False) + "\n"

    if UPDATING or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialised, encoding="utf-8")
        if not UPDATING:
            pytest.skip(f"recorded a new snapshot for {name}; commit it and read the diff")
        return

    expected = json.loads(path.read_text(encoding="utf-8"))
    assert produced == expected, (
        f"the pipeline's output for `{name}` no longer matches its snapshot.\n"
        f"That is the point of this test -- something changed. Read the diff, decide "
        f"whether it is an improvement, and only then re-record with "
        f"AKSHAR_UPDATE_GOLDEN=1.\n"
        f"  snapshot: {path.relative_to(Path(__file__).parents[2]).as_posix()}"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(SCENES))
def test_scene_matches_its_snapshot(name):
    if not detect_text.is_available():
        pytest.skip("text detector weights absent; run scripts/fetch_models.py")

    spec = dict(SCENES[name])
    image = _label(
        spec.pop("lines"),
        marker=spec.pop("marker", True),
        tilt=spec.pop("tilt", 0.10),
        yaw=spec.pop("yaw", 0.06),
        bg=spec.pop("bg", 245),
    )
    assert not spec, f"unused scene keys: {sorted(spec)}"

    # `cache_lookup=None` forces the full path. With a cache in play these
    # would all exit at zero and the snapshots would pin nothing.
    outcome = scan(image, cache_lookup=lambda _identity: None)
    compare(name, snapshot_of(outcome))


def test_listing_text_channel_matches_its_snapshot():
    """The eleventh scene, and the one with no pixels at all.

    Section 3's wall: *"the identical engine judges an e-commerce listing that
    never had pixels."* It is snapshotted alongside the photographs because a
    change to the assembler that only breaks the text channel would otherwise
    pass every test in this file.
    """
    outcome = scan_listing_text(
        "Parle-G Glucose Biscuits 250 g. MRP Rs. 45.00 (inclusive of all taxes). "
        "Mfd by Parle Products Pvt Ltd, Mumbai 400057. Country of origin: India.",
        rulepack_version="lmpc_2011@2026.03",
    )
    compare("listing_text_channel", snapshot_of(outcome))


def test_every_scene_has_a_committed_snapshot():
    """A scene added without a snapshot silently tests nothing on the next run.

    `compare` records a missing snapshot and skips, which is right the first
    time and wrong for ever after -- a skipped test is a test nobody reads. This
    one fails instead.
    """
    if UPDATING:
        pytest.skip("recording")
    expected = {*SCENES, "listing_text_channel"}
    recorded = {path.stem for path in SNAPSHOTS.glob("*.json")}
    missing = expected - recorded
    stale = recorded - expected
    assert not missing, f"scenes with no committed snapshot: {sorted(missing)}"
    assert not stale, f"snapshots with no scene: {sorted(stale)} -- delete them"
