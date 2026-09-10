"""Fixtures for the rules-engine unit tests.

These build DeclarationSets by hand rather than running the pipeline, which is
the point of the extraction/decision split: the whole legal layer is testable
with no image, no model and no database.
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
from rules.loader import load_rulepack
from rules.models import Rulepack


@pytest.fixture(scope="session")
def pack() -> Rulepack:
    return load_rulepack()


def make_declaration(
    field: str,
    text: str,
    *,
    script: str = "latin",
    x: float = 10,
    y: float = 10,
    w: float = 120,
    h: float = 14,
    panel: str | None = "pdp",
    height_px: float | None = None,
    height_mm: float | None = None,
    tolerance: float | None = None,
    contrast: float | None = None,
    char_boxes: list[Box] | None = None,
    numeral_box: Box | None = None,
    numeral_height_px: float | None = None,
    embossed: bool = False,
    rotation_k: int = 0,
) -> Declaration:
    box = Box(x=x, y=y, w=w, h=h, panel_id=panel)  # type: ignore[arg-type]
    return Declaration(
        field=field,  # type: ignore[arg-type]
        text=text,
        script=script,  # type: ignore[arg-type]
        box=box,
        height_px=height_px if height_px is not None else h,
        height_mm=height_mm,
        height_mm_tolerance=tolerance,
        scale_tier="A" if height_mm is not None else None,
        ocr_confidence=0.95,
        field_confidence=0.92,
        contrast_ratio=contrast,
        char_boxes=char_boxes or [],
        numeral_box=numeral_box,
        numeral_height_px=numeral_height_px,
        is_embossed=embossed,
        text_rotation_k=rotation_k,
    )


def make_set(
    declarations: list[Declaration],
    *,
    source: str = "photo",
    mm_per_px: float | None = 0.125,
    pdp_polygon: list[tuple[float, float]] | None = None,
    label_area_cm2: float | None = None,
    raw_text: str | None = None,
    coverage: float = 1.0,
    tier: str = "L0",
) -> DeclarationSet:
    return DeclarationSet(
        source=source,  # type: ignore[arg-type]
        declarations=declarations,
        geometry=LabelGeometry(
            mm_per_px=mm_per_px,
            rectified=True,
            scale_tier="A" if mm_per_px else "C",
            pdp_polygon=pdp_polygon or [(0, 0), (400, 0), (400, 300), (0, 300)],
            label_area_cm2=label_area_cm2,
        ),
        coverage=coverage,
        degradation_tier=tier,  # type: ignore[arg-type]
        captured_at=datetime.now(UTC),
        model_versions={"detector": "test", "ocr": "test", "classifier": "test"},
        raw_text=raw_text,
    )


@pytest.fixture
def compliant_250g() -> DeclarationSet:
    """A fully compliant 250 g biscuit pack.

    250 g falls in Table I's 200-500 band, so numerals must be at least 2 mm.
    """
    chars = [Box(x=10 + i * 8, y=10, w=6, h=16) for i in range(10)]
    return make_set(
        [
            make_declaration(
                "mrp",
                "MRP Rs. 45.00 (inclusive of all taxes)",
                height_mm=2.4,
                tolerance=0.15,
                contrast=8.0,
                char_boxes=chars,
                numeral_box=Box(x=40, y=10, w=30, h=16, panel_id="pdp"),
            ),
            make_declaration(
                "net_quantity",
                "Net Wt. 250 g",
                y=40,
                height_mm=2.6,
                tolerance=0.15,
                contrast=9.0,
                char_boxes=chars,
                numeral_box=Box(x=60, y=40, w=24, h=16, panel_id="pdp"),
            ),
            make_declaration(
                "manufacturer",
                "Manufactured by: Acme Foods Pvt Ltd, Bhubaneswar, Odisha 751001",
                y=200,
                height_mm=1.4,
            ),
            make_declaration("generic_name", "Common name: Biscuits", y=230, height_mm=1.3),
            make_declaration("mfg_date", "Mfg. Date: 03/2026", y=260, height_mm=1.2),
            make_declaration(
                "consumer_care",
                "Consumer care: care@acmefoods.in, 1800 123 4567, Acme House, Cuttack",
                y=280,
                height_mm=1.2,
            ),
        ],
        raw_text=(
            "MRP Rs. 45.00 (inclusive of all taxes) Net Wt. 250 g "
            "Manufactured by: Acme Foods Pvt Ltd Common name: Biscuits "
            "Mfg. Date: 03/2026 Consumer care 1800 123 4567"
        ),
    )


@pytest.fixture
def biscuit_ctx() -> PackageContext:
    return PackageContext(
        category="biscuits",
        net_quantity=ParsedQuantity(value=250, unit="g", base_g_ml=250.0),
    )


@pytest.fixture
def client_officer():
    """An authenticated officer's HTTP client.

    Officer rather than supervisor deliberately: the routes this serves —
    section 15's rule explainer — are the ones an officer needs on a shop floor,
    and a test that only ever authenticates as a supervisor would not notice a
    role check quietly closing them.
    """
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from api.config import Settings, get_settings
    from api.deps import get_audit_log, get_user_store
    from api.main import app
    from api.repository import InMemoryAuditLog, InMemoryUserStore, UserRecord
    from api.security import create_token, hash_password

    settings = Settings(jwt_secret="test-secret-not-the-default", environment="development")
    officer = UserRecord(
        id=uuid4(),
        email="officer@akshar.test",
        full_name="R Mohanty",
        password_hash=hash_password("correct horse"),
        role="officer",
        district="Khordha",
    )
    users = InMemoryUserStore()
    users.add(officer)

    app.dependency_overrides[get_user_store] = lambda: users
    app.dependency_overrides[get_audit_log] = lambda: InMemoryAuditLog()
    app.dependency_overrides[get_settings] = lambda: settings

    token = create_token(subject=officer.id, role="officer", settings=settings)
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        yield client
    app.dependency_overrides.clear()
