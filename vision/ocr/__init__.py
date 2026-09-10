"""M4 OCR — ROI crops only, English and Devanagari, never the full image."""

from vision.ocr import crosscheck, detect_text, dictionary, recognise, script
from vision.ocr.roi import MAX_REGIONS, is_available, rank_regions, read_regions, run

__all__ = [
    "MAX_REGIONS",
    "crosscheck",
    "detect_text",
    "dictionary",
    "is_available",
    "rank_regions",
    "read_regions",
    "recognise",
    "run",
    "script",
]
