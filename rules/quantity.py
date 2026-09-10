"""Net quantity parsing and unit arithmetic.

Shared by the applicability gate (Rule 3(a) size limits), the Table I height
lookup, `value_in_range` (Rule 13(2)-(3)) and `symbol_case`.

Kept out of the checks so unit handling is defined once. Getting this wrong is
invisible: a mis-parsed 1.5 kg reads as 1.5 g and silently selects the wrong
height threshold, producing a confident and completely wrong verdict.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from contracts import ParsedQuantity, QuantityUnit

# Multipliers to the base unit: grams for mass, millilitres for volume.
# Length, area and count are NOT normalised — Table I does not apply to them,
# Table II (PDP area) does.
_TO_BASE_G_ML: dict[str, float] = {
    "mg": 0.001,
    "g": 1.0,
    "kg": 1000.0,
    "t": 1_000_000.0,
    "ml": 1.0,
    "l": 1000.0,
}

_COUNT_OR_DIMENSION = {"cm", "mm", "m", "N", "U"}

# Mass and volume both normalise onto the same numeric scale (1 g == 1 ml as a
# magnitude), which is what Table I wants — it bands on "g/ml" without caring
# which. But a LIMIT comparison must not cross dimensions, or a 30 kg sack
# would trip the "over 25 litres" gate. Track the dimension explicitly.
_DIMENSION: dict[str, str] = {
    "mg": "mass",
    "g": "mass",
    "kg": "mass",
    "t": "mass",
    "ml": "volume",
    "l": "volume",
    "cm": "length",
    "mm": "length",
    "m": "length",
    "N": "count",
    "U": "count",
}

# Spellings that appear on real labels, mapped to the lawful symbol.
# `ltr`, `ltrs`, `gms` are themselves violations (plural / non-symbol forms)
# and are caught separately; here we only need to understand the magnitude.
_ALIASES: dict[str, str] = {
    "ltr": "l",
    "ltrs": "l",
    "litre": "l",
    "litres": "l",
    "liter": "l",
    "liters": "l",
    "gm": "g",
    "gms": "g",
    "gs": "g",
    "kgs": "kg",
    "mgs": "mg",
    "mls": "ml",
    "no": "U",
    "nos": "U",
    "pc": "U",
    "pcs": "U",
    "piece": "U",
    "pieces": "U",
}

_VALUE_UNIT = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>mg|kg|gms?|gs|g|mls?|ltrs?|litres?|liters?|l|cm|mm|m|t|N|U|nos?|pcs?|pieces?)"
    r"(?![A-Za-z])",
    re.IGNORECASE,
)

# Devanagari, Gujarati, Odia, Tamil digit blocks -> ASCII, so a Hindi-only
# label still yields a comparable magnitude. The fact that non-international
# digits were used is a separate finding (LMPC.NUM.DIGIT_FORM); it must not
# also cause us to report the quantity as unreadable.
_DIGIT_BLOCKS = ("०", "૦", "୦", "௦")  # noqa: RUF001 - Indic digit zeros, deliberately
"""Devanagari, Gujarati, Odia and Tamil ZERO. These are the block anchors, not
Latin letters: ruff's ambiguous-character warning is exactly backwards here,
because reading these scripts is the requirement."""


def normalise_digits(text: str) -> str:
    """Fold Indic digit forms to 0-9 without altering anything else."""
    out = []
    for ch in text:
        mapped = ch
        for base in _DIGIT_BLOCKS:
            offset = ord(ch) - ord(base)
            if 0 <= offset <= 9:
                mapped = chr(ord("0") + offset)
                break
        out.append(mapped)
    return "".join(out)


def has_non_international_digits(text: str) -> bool:
    """True if any digit is written in a non-international Indian form."""
    return any(
        0 <= ord(ch) - ord(base) <= 9 for ch in text for base in _DIGIT_BLOCKS
    ) or any(unicodedata.category(ch) == "Nd" and not ch.isascii() for ch in text)


@dataclass(frozen=True, slots=True)
class QuantityMatch:
    """A quantity as it was literally written, plus its normalised magnitude."""

    value: float
    unit_as_written: str
    unit: QuantityUnit
    raw: str
    base_g_ml: float | None
    is_count_or_dimension: bool

    def to_parsed(self) -> ParsedQuantity:
        return ParsedQuantity(
            value=self.value,
            unit=self.unit,
            base_g_ml=self.base_g_ml,
            is_count_or_dimension=self.is_count_or_dimension,
        )


def _canonical_unit(raw_unit: str) -> str:
    lowered = raw_unit.lower()
    if lowered in _ALIASES:
        return _ALIASES[lowered]
    # `N` and `U` are the only symbols whose case is meaningful here.
    if raw_unit in {"N", "U"}:
        return raw_unit
    if lowered in {"mg", "kg", "g", "ml", "l", "cm", "mm", "m", "t"}:
        return lowered
    return lowered


def parse_quantity(text: str) -> QuantityMatch | None:
    """Extract the first value+unit pair from a declaration.

    Returns None when nothing parses — the caller must then return NO_DATA,
    never FAIL. A quantity we could not read is not a quantity that is wrong.
    """
    if not text:
        return None
    folded = normalise_digits(text)
    m = _VALUE_UNIT.search(folded)
    if not m:
        return None

    raw_value = m.group("value").replace(",", ".")
    try:
        value = float(raw_value)
    except ValueError:  # pragma: no cover - regex guarantees digits
        return None

    written = m.group("unit")
    unit = _canonical_unit(written)
    base = _TO_BASE_G_ML.get(unit)
    return QuantityMatch(
        value=value,
        unit_as_written=written,
        unit=unit,  # type: ignore[arg-type]
        raw=m.group(0),
        base_g_ml=value * base if base is not None else None,
        is_count_or_dimension=unit in _COUNT_OR_DIMENSION,
    )


def parse_all_quantities(text: str) -> list[QuantityMatch]:
    """Every value+unit pair. Used to spot contradicting quantities on one pack."""
    out: list[QuantityMatch] = []
    for m in _VALUE_UNIT.finditer(normalise_digits(text or "")):
        parsed = parse_quantity(m.group(0))
        if parsed:
            out.append(parsed)
    return out


def parse_amount(text: str) -> float | None:
    """Parse a monetary amount, accepting Indian and international grouping.

    `1,250.00`, `2,50,000.00` and `1250` all parse. This is the arithmetic
    behind the MRP locate pattern: an amount regex that rejects separators
    reports every product priced at Rs 1,000 or above as having no MRP.
    """
    if not text:
        return None
    folded = normalise_digits(text)
    m = re.search(r"\d{1,3}(?:[,\s]?\d{2,3})*(?:\.\d{1,2})?", folded)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "").replace(" ", ""))
    except ValueError:  # pragma: no cover
        return None


def compare_to_limit(qty: ParsedQuantity | None, value: float, unit: str) -> bool | None:
    """Is `qty` strictly greater than `value` `unit`?

    Returns None when the comparison is not meaningful (no quantity, or a count
    compared against a mass), so a gate can decline to fire rather than guess.
    """
    if qty is None or qty.base_g_ml is None:
        return None
    limit_unit = unit.lower()
    limit_base = _TO_BASE_G_ML.get(limit_unit)
    if limit_base is None:
        return None
    # Never compare a mass against a volume limit, or vice versa.
    if _DIMENSION.get(qty.unit) != _DIMENSION.get(limit_unit):
        return None
    return qty.base_g_ml > value * limit_base


def within_limit(qty: ParsedQuantity | None, value: float, unit: str) -> bool | None:
    """Is `qty` less than or equal to `value` `unit`? (Rule 26(a) small packs)"""
    greater = compare_to_limit(qty, value, unit)
    return None if greater is None else not greater


__all__ = [
    "QuantityMatch",
    "compare_to_limit",
    "has_non_international_digits",
    "normalise_digits",
    "parse_all_quantities",
    "parse_amount",
    "parse_quantity",
    "within_limit",
]
