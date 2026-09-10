"""M5 Classify — regex tier first, a 2M-parameter head only for addresses."""

from vision.classify import features, model_tier, regex_tier
from vision.classify.assemble import (
    address_candidates,
    classify_lines,
    from_lines,
    from_listing_text,
)
from vision.classify.regex_tier import FieldGuess, classify_line, classify_text

__all__ = [
    "FieldGuess",
    "address_candidates",
    "classify_line",
    "classify_lines",
    "classify_text",
    "features",
    "from_lines",
    "from_listing_text",
    "model_tier",
    "regex_tier",
]
