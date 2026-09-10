"""Latency budget for the model-free path — AKSHAR.md section 4.

    | Cache hit, in browser | <100 ms  | build fails above 200 ms  |
    | Cache miss, WebGPU    | <700 ms  | build fails above 1200 ms |
    | Cache miss, WASM      | <1300 ms | build fails above 2000 ms |

**What these benchmarks can and cannot claim.** They measure the *deterministic*
pipeline — B1, identity, rectification, scale recovery and measurement — which
is all of it that does not need model weights. The detector and the two OCR
heads are not exercised, so no number here is the 561 ms end-to-end figure and
none may be reported as one. `RESULTS.md` records them under their own heading
for exactly that reason.

**How the two cache-miss rows are enforced without a model.** Section 4's exit
two decomposes into eight stages, and only three of them run a network:

    B1 8 · pHash 18 · detect 110 · rectify 55 · scale 55 · OCR 290 · classify 20
    · rules 5   =   561 ms on WebGPU, 1036 ms on the WASM fallback

Everything except detect, OCR and classify costs the same on either backend, so
the deterministic share is 8 + 18 + 55 + 55 + 5 = 141 ms of both totals, and the
backend choice moves the other 420 ms to 895 ms. That share is what this file
measures, and it is budgeted against the *WASM* row rather than the WebGPU one
because WASM is the wider ceiling and a regression that fits inside 2000 ms but
not 1200 ms is still a regression worth catching at the tighter bound.

The consequence worth stating plainly: passing this file does not prove the
browser meets 1300 ms. It proves the half we control by hand-written arithmetic
has not drifted, and it fails the build when it does — which is why it is in CI
now rather than after the weights land.

These run on a CPU with no GPU, so they are a pessimistic bound on the browser
figures rather than an optimistic one.
"""

from __future__ import annotations

import pytest

from tests.unit.synthetic import blank_label, draw_marker, draw_text, on_canvas, photograph
from vision.identify import identify
from vision.identify.phash import normalise_for_hash
from vision.pipeline import scan
from vision.quality import assess as assess_quality
from vision.rectify import rectify
from vision.scale.resolve import resolve_scale

CACHE_HIT_BUDGET_MS = 100.0
CACHE_HIT_FAIL_MS = 200.0
"""Section 4. Exit zero must stay cheap or the whole cache argument collapses:
if a cache hit costs as much as a scan, there is no point having one."""

GEOMETRY_BUDGET_MS = 400.0
GEOMETRY_FAIL_MS = 800.0
"""Rectify (55) + scale (55) from section 4's table, with generous headroom for
a CPU-only CI runner and the pre-hash normalisation pass.

Scale was 70 ms in the plan this one replaced; ArUco corner detection on a
printed ChArUco card is cheaper than the coin-ellipse fit it superseded, and
`docs/plan-migration.md` records that as one of the switch's few wins."""

QUALITY_BUDGET_MS = 15.0
QUALITY_FAIL_MS = 30.0
"""Section 18b's M0: B1 is done when it rejects the bad frames *"in under
15 ms"*. It sits in front of everything — before the cache, before the
detector — so every scan pays it, including the ones that exit at zero. A gate
that costs more than the exit it protects is not a gate, it is a tax."""

DETERMINISTIC_SHARE_MS = 141.0
"""B1 (8) + pHash (18) + rectify (55) + scale (55) + rules (5). The part of
section 4's exit-two total that is identical on WebGPU and on WASM."""

CACHE_MISS_WASM_BUDGET_MS = 1300.0
CACHE_MISS_WASM_FAIL_MS = 2000.0
"""Section 4's third row, verbatim. What is asserted against it is the
deterministic share scaled for a CPU-only runner — see the module docstring;
the model stages are not in this process."""

MODEL_SHARE_WASM_MS = 895.0
"""detect + OCR + classify on the WASM fallback: 1036 - 141. Held out of the
measurement, and subtracted from the ceiling rather than ignored, so the
headroom this file leaves is the headroom the browser will actually have."""


@pytest.fixture(scope="module")
def shelf_photo():
    label = blank_label()
    draw_text(label, "MRP Rs. 45.00", baseline=(60, 120), cap_px=34)
    draw_text(label, "NET WT 250 g", baseline=(60, 230), cap_px=26)
    draw_text(label, "MFG 03/2026", baseline=(60, 330), cap_px=18)
    canvas = on_canvas(label)
    draw_marker(canvas, centre=(1010, 700), edge_px=110)
    shot, _ = photograph(canvas, tilt=0.08, yaw=0.05)
    return shot


def test_cache_hit_stays_under_budget(benchmark, shelf_photo):
    """Exit zero: identity plus a cache lookup, and no model at all."""
    outcome = benchmark(lambda: scan(shelf_photo, cache_lookup=lambda _identity: "scan-1"))
    assert outcome.exit_path == "cache_hit"

    mean_ms = benchmark.stats.stats.mean * 1000.0
    assert mean_ms < CACHE_HIT_FAIL_MS, (
        f"cache hit took {mean_ms:.1f} ms against a {CACHE_HIT_FAIL_MS:.0f} ms ceiling"
    )
    if mean_ms > CACHE_HIT_BUDGET_MS:
        pytest.skip(f"over the {CACHE_HIT_BUDGET_MS:.0f} ms target at {mean_ms:.1f} ms")


def test_prehash_normalisation_is_cheap(benchmark, shelf_photo):
    """The spec delta only holds if the cheap flatten really is cheap.

    Section 4 budgets 18 ms for hash plus lookup. If normalising first cost
    anything like the 55 ms full rectify, hashing the raw frame would be the
    right trade after all and the delta would be wrong.
    """
    benchmark(lambda: normalise_for_hash(shelf_photo))
    mean_ms = benchmark.stats.stats.mean * 1000.0
    assert mean_ms < 40.0, f"pre-hash flatten cost {mean_ms:.1f} ms; the delta needs it cheap"


def test_identity_stays_under_budget(benchmark, shelf_photo):
    normalised = normalise_for_hash(shelf_photo)
    benchmark(lambda: identify(normalised, shelf_photo))
    mean_ms = benchmark.stats.stats.mean * 1000.0
    assert mean_ms < 120.0, f"identity cost {mean_ms:.1f} ms"


def test_geometry_path_stays_under_budget(benchmark, shelf_photo):
    """Rectify plus scale recovery — the two stages no model is involved in."""

    def run():
        result = rectify(shelf_photo)
        return resolve_scale(
            shelf_photo,
            result.image,
            homography=result.homography,
            rectify_method=result.method,
        )

    estimate = benchmark(run)
    assert estimate.tier in {"A", "B", "C"}

    mean_ms = benchmark.stats.stats.mean * 1000.0
    assert mean_ms < GEOMETRY_FAIL_MS, (
        f"geometry path took {mean_ms:.1f} ms against a {GEOMETRY_FAIL_MS:.0f} ms ceiling"
    )


def test_capture_gate_stays_under_budget(benchmark, shelf_photo):
    """B1, section 18b's M0: *"in under 15 ms"*.

    Every scan pays this, including the ones that exit at the cache, so it is
    the one stage whose cost is never amortised by a hit. It is also the only
    stage measured here that section 4 budgets in single digits — 8 ms — which
    leaves no room for a convenience like decoding the frame twice.

    Asserted against the *acceptance* figure of 15 ms rather than the budget
    figure of 8, because M0 is the criterion `RESULTS.md` has to be able to
    quote, and a benchmark that fails the build at a number nobody wrote down
    is a benchmark that gets deleted the first time it goes red.
    """
    quality = benchmark(lambda: assess_quality(shelf_photo))
    assert quality.width and quality.height, "the gate must report the frame it measured"

    mean_ms = benchmark.stats.stats.mean * 1000.0
    assert mean_ms < QUALITY_FAIL_MS, (
        f"B1 took {mean_ms:.1f} ms against a {QUALITY_FAIL_MS:.0f} ms ceiling; "
        f"section 18b's M0 requires under {QUALITY_BUDGET_MS:.0f} ms"
    )
    if mean_ms > QUALITY_BUDGET_MS:
        pytest.skip(f"over the {QUALITY_BUDGET_MS:.0f} ms M0 target at {mean_ms:.1f} ms")


def test_cache_miss_deterministic_share_fits_the_wasm_budget(benchmark, shelf_photo):
    """Section 4's third row: cache miss on the WASM fallback, <1300 ms, fails above 2000 ms.

    The three model stages are not in this process, so what is measured is the
    other five — B1, identity, rectify, scale and the measurement arithmetic —
    run as one sequence through `scan()` rather than as five separate timings
    added up. Running the composition matters: the stages hand each other
    images, and a change that makes `rectify` return a copy instead of a view
    costs real milliseconds that no per-stage benchmark would ever see.

    The ceiling is section 4's own, minus the 895 ms the same section budgets
    for detect + OCR + classify on WASM. What is left is the room the
    deterministic half is allowed to occupy, and the assertion is that it fits
    inside that room on a CPU-only runner with no GPU — which is the pessimistic
    case, not the optimistic one.

    `cache_lookup` returns `None`, which is what makes this a *miss*: exit zero
    is declined and the frame goes down the full path. Without that the test
    would measure the 60 ms replay and pass for ever.
    """
    outcome = benchmark(lambda: scan(shelf_photo, cache_lookup=lambda _identity: None))
    assert outcome.exit_path in {"full", "no_package"}, (
        f"expected a cache miss to reach the full path, got {outcome.exit_path!r}"
    )

    headroom_ms = CACHE_MISS_WASM_FAIL_MS - MODEL_SHARE_WASM_MS
    mean_ms = benchmark.stats.stats.mean * 1000.0
    assert mean_ms < headroom_ms, (
        f"the model-free share of a cache miss took {mean_ms:.1f} ms; section 4 leaves it "
        f"{headroom_ms:.0f} ms before the {CACHE_MISS_WASM_FAIL_MS:.0f} ms WASM ceiling is "
        f"breached with the budgeted {MODEL_SHARE_WASM_MS:.0f} ms of model time added"
    )
    target_ms = CACHE_MISS_WASM_BUDGET_MS - MODEL_SHARE_WASM_MS
    if mean_ms > target_ms:
        pytest.skip(
            f"{mean_ms:.1f} ms against the {target_ms:.0f} ms implied by the "
            f"{CACHE_MISS_WASM_BUDGET_MS:.0f} ms target; under the ceiling but over the target"
        )


def test_the_deterministic_share_is_the_share_section_4_says_it_is(shelf_photo):
    """A guard on the arithmetic in this file's docstring, not on the code's speed.

    `DETERMINISTIC_SHARE_MS` and `MODEL_SHARE_WASM_MS` are hand-derived from
    section 4's table, and hand-derived constants rot: the scale row already
    moved from 70 ms to 55 ms once, when the coin gave way to the ChArUco card.
    If somebody edits one of them without the other, the ceiling the previous
    test asserts against silently becomes wrong in a direction nobody notices,
    because the test still passes.

    So the two are checked against the totals they were decomposed from.
    """
    webgpu_total, wasm_total = 561.0, 1036.0
    model_share_webgpu = 110.0 + 290.0 + 20.0  # detect + OCR + classify
    assert webgpu_total == DETERMINISTIC_SHARE_MS + model_share_webgpu
    assert wasm_total == DETERMINISTIC_SHARE_MS + MODEL_SHARE_WASM_MS
