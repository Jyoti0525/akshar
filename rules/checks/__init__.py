"""The thirteen check types — one module each.

Section 13: "Thirteen check types. Build these and no more."

`ratio_min` was dropped, and with it the `usp` field name. Both existed only
for a "Unit Sale Price must be half the MRP height" rule that came from a
vendor blog and is not in the 2011 Rules. Nothing in the bare act needs it.

Three of these — `min_height_mm`, `min_width_ratio` and `clear_space` — are
pure geometry and cannot be implemented without bounding boxes. Two of the
three need no millimetres either, because width-against-height and
gap-against-height are ratios of pixels. They survive total failure of scale
recovery, and they are the rules only this architecture can check.
"""

from __future__ import annotations

from collections.abc import Callable

from contracts import DeclarationSet, PackageContext
from rules.checks import (
    clear_space,
    conditional_present,
    in_table,
    min_contrast,
    min_height_mm,
    min_width_ratio,
    no_duplicate_field,
    present,
    regex,
    regex_absent,
    same_panel,
    symbol_case,
    value_in_range,
)
from rules.models import CheckOutcome, Rule, Rulepack

CheckFn = Callable[[Rule, DeclarationSet, PackageContext, Rulepack], CheckOutcome]

REGISTRY: dict[str, CheckFn] = {
    "present": present.check,
    "regex": regex.check,
    "regex_absent": regex_absent.check,
    "min_height_mm": min_height_mm.check,
    "min_width_ratio": min_width_ratio.check,
    "same_panel": same_panel.check,
    "clear_space": clear_space.check,
    "min_contrast": min_contrast.check,
    "no_duplicate_field": no_duplicate_field.check,
    "conditional_present": conditional_present.check,
    "in_table": in_table.check,
    "symbol_case": symbol_case.check,
    "value_in_range": value_in_range.check,
}

SCALE_FREE_CHECKS = frozenset({"min_width_ratio", "clear_space"})
"""Geometric checks that compare pixels against pixels. They run at scale
tier C, with no marker and no calibration."""

REQUIRES_MILLIMETRES = frozenset({"min_height_mm"})
"""The only check that goes dark at scale tier C."""


def get(check_type: str) -> CheckFn:
    try:
        return REGISTRY[check_type]
    except KeyError:  # pragma: no cover - loader validates first
        raise KeyError(
            f"'{check_type}' is not one of the thirteen permitted check types: "
            f"{sorted(REGISTRY)}"
        ) from None


__all__ = ["REGISTRY", "REQUIRES_MILLIMETRES", "SCALE_FREE_CHECKS", "CheckFn", "get"]
