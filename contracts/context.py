"""Package context — inputs the applicability gates need before any rule runs.

SPEC DELTA. AKSHAR.md section 9 freezes `DeclarationSet` without any of this,
but section 13's applicability gate and several rules reference facts that are
properties of the *package*, not of a declaration:

    applicability.exclude_if.category_in          -> category
    applicability.exclude_if.consumer_type_in     -> consumer_type
    applicability.package_type_rules              -> package_type   (Rule 24)
    applicability.exclude_if.net_quantity_gt      -> parsed quantity
    LMPC.CONTRAST.NUMERALS.skip_if.surface_in     -> surface
    LMPC.MRP.*.variant_key: embossed              -> declaration_style
    LMPC.MRP.DEFACED.only_if                      -> sticker_or_overprint_detected
    LMPC.QTY.WHEN_PACKED.unless_category_in       -> category
    LMPC.*.keyed_by: category                     -> category
    Rule 7(4) height disapplication                -> other_law_mandates

Without these the engine cannot run the six gates, and applying a retail rule
to a wholesale carton produces four false violations on every scan — which the
plan calls out by name as worse than missing a real violation.

Kept in its own module so the delta from the frozen contract stays visible.
Recorded in docs/spec-deltas.md.

This module MUST NOT import cv2 or the database.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------

PackageType = Literal["retail", "wholesale", "group", "combination"]
"""Rule 24: a WHOLESALE package needs only three declarations — manufacturer,
generic name, and count or net quantity. This is the gate most teams miss."""

ConsumerType = Literal["retail", "industrial", "institutional"]
"""Rule 3(b): packages for industrial or institutional consumers are outside
these rules entirely."""

Surface = Literal[
    "paper",
    "kraft",
    "foil",
    "plastic_film",
    "blown",
    "molded",
    "glass",
    "plastic_formed",
    "metal",
    "other",
]
"""``LMPC.CONTRAST.NUMERALS`` is skipped on blown, moulded, glass and formed
plastic surfaces, where the declaration is part of the container and has no
ink contrast to measure."""

DeclarationStyle = Literal["normal", "embossed"]
"""Selects the column of Rule 7(2) Table I. Embossed, blown or moulded
lettering must be roughly twice as tall to be equally legible."""

QuantityUnit = Literal["g", "kg", "mg", "ml", "l", "cm", "mm", "m", "t", "N", "U"]


class ParsedQuantity(BaseModel):
    """A net quantity reduced to a comparable number.

    ``base_g_ml`` normalises mass and volume to grams / millilitres so the
    Table I lookup and the Rule 3(a) size gate can compare against thresholds
    without repeating unit arithmetic in every check.
    """

    model_config = ConfigDict(frozen=True)

    value: float
    unit: QuantityUnit
    base_g_ml: float | None = None
    """Normalised magnitude in g or ml. None for count/length units, where
    Table I does not apply and Table II (PDP area) governs instead."""

    is_count_or_dimension: bool = False
    """True for number (U), length (cm/mm/m) and area declarations. Rule 7(2)(ii)
    Table II applies to these, not Table I."""


class PackageContext(BaseModel):
    """Facts about the package that gate which rules may lawfully be applied.

    Everything defaults to the most common case — a retail food package with a
    normally printed paper label sold to a consumer — so a caller that knows
    nothing still gets sensible behaviour rather than a validation error.
    """

    category: str = "unknown"
    """Free text keyed against rulepack tables: food, biscuits, tea, cement,
    toilet_soap, cosmetic, electronics, footwear, medical_device, bidi, ...
    Free rather than an enum because the Second and Fourth Schedules name
    dozens of commodities and the list changes by amendment."""

    package_type: PackageType = "retail"
    consumer_type: ConsumerType = "retail"
    surface: Surface = "paper"
    declaration_style: DeclarationStyle = "normal"

    net_quantity: ParsedQuantity | None = None
    """Parsed from the net_quantity declaration when the engine can; may be
    supplied directly by the listing_text channel."""

    is_imported: bool = False
    """Drives ``LMPC.IMPORTER.PRESENT`` (conditional_present).

    Set by the officer or read from a listing. A pack can be an import and
    still declare no country of origin, so this is not redundant with the
    declaration that normally triggers the rule.
    """

    sticker_or_overprint_detected: bool = False
    """Gates ``LMPC.MRP.DEFACED`` (Rule 18(5)) so a clean printed label is
    never accused of being defaced."""

    other_law_mandates: list[str] = Field(default_factory=list)
    """Rule 7(4): where another statute requires the same information, the
    height rules of these rules do not apply to it. Field names."""

    outer_wrapper_transparent: bool | None = None
    """Rule 9(3): an outer wrapper must repeat the declarations unless it is
    transparent enough to read them through."""

    readable_only_through_contents: bool = False
    """Rule 9(2): a declaration must not be legible only through the liquid
    contents of the package."""

    def is_wholesale(self) -> bool:
        return self.package_type == "wholesale"


__all__ = [
    "ConsumerType",
    "DeclarationStyle",
    "PackageContext",
    "PackageType",
    "ParsedQuantity",
    "QuantityUnit",
    "Surface",
]
