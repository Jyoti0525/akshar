"""M2 Scale, three tiers — A a reference object, B a known SKU, C none at all.

Tier C is imported first deliberately: it is the tier that must always work,
and section 17 says to build it first.
"""

from vision.scale import tier_a, tier_b, tier_c
from vision.scale.resolve import resolve_scale

__all__ = ["resolve_scale", "tier_a", "tier_b", "tier_c"]
