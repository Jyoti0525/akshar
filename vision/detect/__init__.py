"""M3 Detect — package and principal display panel, two classes, 640 px."""

from vision.detect.detector import (
    MIN_PACKAGE_AREA_FRAC,
    MODEL_FILENAME,
    PACKAGE_CONF,
    PANEL_CONF,
    detect,
    is_available,
)
from vision.detect.postprocess import CLASS_NAMES, MASK_THRESHOLD, decode
from vision.detect.preprocess import IMG_SIZE, Letterbox, letterbox

__all__ = [
    "CLASS_NAMES",
    "IMG_SIZE",
    "MASK_THRESHOLD",
    "MIN_PACKAGE_AREA_FRAC",
    "MODEL_FILENAME",
    "PACKAGE_CONF",
    "PANEL_CONF",
    "Letterbox",
    "decode",
    "detect",
    "is_available",
    "letterbox",
]
