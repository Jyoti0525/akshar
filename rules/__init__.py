"""The decision layer.

Rules decide, models never. A neural network may extract a fact; only YAML
issues a verdict, because a rule can be read aloud in court and a confidence
score cannot.

Nothing in this package may import cv2, PaddleOCR, or a database driver.
"""

from rules.engine import evaluate, is_compliant, summarise
from rules.loader import cached_rulepack, load_rulepack
from rules.models import CheckOutcome, Rule, Rulepack

__all__ = [
    "CheckOutcome",
    "Rule",
    "Rulepack",
    "cached_rulepack",
    "evaluate",
    "is_compliant",
    "load_rulepack",
    "summarise",
]
