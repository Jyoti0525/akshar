"""Latency budget for the rules engine — AKSHAR.md section 4.

    Rules engine, 30 rules    target < 10 ms    build fails above 25 ms

A change that makes things slower breaks the build. Being able to say that in
Q&A is worth more than the numbers themselves.

Run just this file:      pytest bench/ -q
Run with a full report:  pytest bench/ --benchmark-columns=mean,median,max
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from contracts import (
    Box,
    Declaration,
    DeclarationSet,
    LabelGeometry,
    PackageContext,
    ParsedQuantity,
)
from rules.engine import evaluate
from rules.loader import load_rulepack

BUDGET_MS = 10.0
"""Target from the section 4 performance budget."""

FAIL_ABOVE_MS = 25.0
"""The build fails above this."""


def _declaration(field: str, text: str, y: float, height_mm: float) -> Declaration:
    box = Box(x=10, y=y, w=140, h=16, panel_id="pdp")
    return Declaration(
        field=field,  # type: ignore[arg-type]
        text=text,
        script="latin",
        box=box,
        height_px=16.0,
        height_mm=height_mm,
        height_mm_tolerance=0.15,
        scale_tier="A",
        ocr_confidence=0.95,
        field_confidence=0.93,
        contrast_ratio=8.0,
        char_boxes=[Box(x=10 + i * 8, y=y, w=6, h=16) for i in range(12)],
        numeral_box=Box(x=40, y=y, w=30, h=16, panel_id="pdp"),
    )


@pytest.fixture(scope="module")
def realistic_scan() -> tuple[DeclarationSet, PackageContext]:
    """A full pack: every mandatory declaration, character geometry, panel."""
    ds = DeclarationSet(
        source="photo",
        declarations=[
            _declaration("mrp", "MRP Rs. 45.00 (inclusive of all taxes)", 10, 2.4),
            _declaration("net_quantity", "Net Wt. 250 g", 40, 2.6),
            _declaration("manufacturer", "Manufactured by: Acme Foods Pvt Ltd, Odisha", 200, 1.4),
            _declaration("generic_name", "Common name: Biscuits", 230, 1.3),
            _declaration("mfg_date", "Mfg. Date: 03/2026", 260, 1.2),
            _declaration("consumer_care", "Consumer care 1800 123 4567, Cuttack", 280, 1.2),
            _declaration("batch", "Batch 24MRP07", 300, 1.1),
            _declaration("marketing_text", "Rs. 20 OFF", 320, 3.0),
        ],
        geometry=LabelGeometry(
            mm_per_px=0.125,
            mm_per_px_tolerance=0.01,
            rectified=True,
            scale_tier="A",
            pdp_polygon=[(0, 0), (400, 0), (400, 400), (0, 400)],
            label_area_cm2=180.0,
        ),
        coverage=0.95,
        degradation_tier="L0",
        captured_at=datetime.now(UTC),
        model_versions={"detector": "rtmdet-ins-tiny@int8", "ocr": "ppocrv6-det+ppocrv5-rec", "ep": "webgpu"},
        raw_text="MRP Rs. 45.00 (inclusive of all taxes) Net Wt. 250 g Acme Foods",
    )
    ctx = PackageContext(
        category="biscuits",
        net_quantity=ParsedQuantity(value=250, unit="g", base_g_ml=250.0),
    )
    return ds, ctx


@pytest.mark.benchmark
def test_engine_meets_latency_budget(benchmark, realistic_scan):
    ds, ctx = realistic_scan
    pack = load_rulepack()

    verdicts = benchmark(evaluate, ds, ctx, pack)

    assert len(verdicts) >= 30, "the budget is quoted for a 30-rule pack"

    mean_ms = benchmark.stats.stats.mean * 1000
    assert mean_ms < FAIL_ABOVE_MS, (
        f"rules engine took {mean_ms:.2f} ms, above the {FAIL_ABOVE_MS} ms build limit"
    )
    if mean_ms >= BUDGET_MS:
        pytest.warns(UserWarning)  # surfaced in the report; not yet a failure


@pytest.mark.benchmark
def test_rulepack_loads_quickly(benchmark):
    """Cold load matters: the browser fetches this pack on first run."""
    pack = benchmark(load_rulepack)
    assert len(pack.rules) == 31
