"""B1 — the capture-quality pre-gate. AKSHAR.md sections 4, 8 and 17 (M0).

    "A blurry or glare-blown photo entering the pipeline produces a confident,
     wrong millimetre measurement. That is the single worst failure this project
     can have, and the fix costs nothing."                       -- section 8

    "No model. Ordinary mathematics answers 'is this blurry' deterministically
     and in about 8 ms. Rejecting a bad photo before spending 500 ms on it is
     both faster and more honest than measuring it badly."       -- section 8
"""

from vision.quality.framing import assess as assess_framing
from vision.quality.gate import THRESHOLDS, Thresholds, assess

__all__ = ["THRESHOLDS", "Thresholds", "assess", "assess_framing"]
