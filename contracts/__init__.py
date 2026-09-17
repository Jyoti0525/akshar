"""Shared vocabulary between extraction, decision, API and web.

Nothing in this package may import cv2, PaddleOCR, or a database driver.
`tests/test_boundaries.py` enforces it — if that test fails, the wall between
extraction and decision has leaked and the listing_text channel is about to
become a rewrite.
"""

from contracts.context import (
    ConsumerType,
    DeclarationStyle,
    PackageContext,
    PackageType,
    ParsedQuantity,
    QuantityUnit,
    Surface,
)
from contracts.declarations import (
    NON_STATUTORY_FIELDS,
    Box,
    Declaration,
    DeclarationSet,
    DegradationTier,
    FieldName,
    LabelGeometry,
    PanelId,
    ScaleTier,
    Script,
    Severity,
    SourceChannel,
    Verdict,
    VerdictStatus,
)
from contracts.quality import (
    ADVICE,
    FRAMING_ADVICE,
    CaptureQuality,
    Framing,
    FramingFault,
    QualityFault,
)

__all__ = [
    "NON_STATUTORY_FIELDS",
    "ADVICE",
    "Box",
    "CaptureQuality",
    "FRAMING_ADVICE",
    "ConsumerType",
    "Declaration",
    "DeclarationSet",
    "DeclarationStyle",
    "DegradationTier",
    "FieldName",
    "Framing",
    "FramingFault",
    "LabelGeometry",
    "PackageContext",
    "PackageType",
    "PanelId",
    "ParsedQuantity",
    "QualityFault",
    "QuantityUnit",
    "ScaleTier",
    "Script",
    "Severity",
    "SourceChannel",
    "Surface",
    "Verdict",
    "VerdictStatus",
]
