"""Rulepack loading and validation.

All file I/O for the rules layer lives here, so `rules/engine.py` can stay a
pure function. The engine receives an already-loaded `Rulepack`.

Validation is strict on purpose: a rulepack that references a pattern which
does not exist, or uses a check type outside the permitted thirteen, must fail
at load time rather than silently returning NO_DATA on a real inspection.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from rules.models import ALLOWED_CHECKS, Pattern, Rule, Rulepack

DEFAULT_PACK = Path(__file__).parent / "packs" / "lmpc_2011.yaml"

_REF_KEYS = (
    "pattern_ref",
    "locate_ref",
    "phone_ref",
    "email_ref",
    "parse_ref",
)


class RulepackError(ValueError):
    """Raised when a rulepack is structurally unusable."""


def _compile_patterns(raw: dict[str, Any]) -> dict[str, Pattern]:
    patterns: dict[str, Pattern] = {}
    for name, spec in (raw or {}).items():
        if not isinstance(spec, dict):
            raise RulepackError(f"pattern '{name}' must be a mapping of script -> regex")
        compiled: dict[str, re.Pattern[str]] = {}
        for script, expr in spec.items():
            try:
                compiled[script] = re.compile(expr)
            except re.error as exc:  # pragma: no cover - guarded by tests
                raise RulepackError(f"pattern '{name}.{script}' does not compile: {exc}") from exc
        patterns[name] = Pattern(name=name, by_script=compiled)
    return patterns


def _build_rule(raw: dict[str, Any]) -> Rule:
    missing = {"id", "rule_ref", "check", "severity", "message"} - raw.keys()
    if missing:
        raise RulepackError(f"rule {raw.get('id', '<no id>')} is missing keys: {sorted(missing)}")

    check = raw["check"]
    if check not in ALLOWED_CHECKS:
        raise RulepackError(
            f"rule {raw['id']} uses check '{check}', which is outside the thirteen "
            f"permitted types. Section 13: build these and no more."
        )

    fields = raw.get("fields") or ()
    if isinstance(fields, str):
        fields = (fields,)

    # A few rules in the pack write `field:` with a list value; normalise.
    single = raw.get("field")
    if isinstance(single, list):
        fields = tuple(single)
        single = None

    return Rule(
        id=raw["id"],
        rule_ref=raw["rule_ref"],
        check=check,
        severity=raw["severity"],
        message=raw["message"],
        raw=raw,
        field_name=single,
        fields=tuple(fields),
        enabled=raw.get("enabled", True),
        advisory=raw.get("advisory", False),
        scale_free=raw.get("scale_free", False),
        requires=tuple(raw.get("requires", ()) or ()),
        respondent=raw.get("respondent", "manufacturer"),
        suppresses=raw.get("suppresses"),
        on_locate_fail=raw.get("on_locate_fail"),
    )


def _validate(pack: Rulepack) -> None:
    """Fail loudly on references that cannot resolve."""
    ids = {r.id for r in pack.all_rules()}
    problems: list[str] = []

    for rule in pack.all_rules():
        for key in _REF_KEYS:
            ref = rule.opt(key)
            if ref and ref not in pack.patterns:
                problems.append(f"{rule.id}.{key} -> unknown pattern '{ref}'")

        for key in ("table", "fallback_table"):
            ref = rule.opt(key)
            if ref and ref not in pack.tables:
                problems.append(f"{rule.id}.{key} -> unknown table '{ref}'")

        for key in ("proper_name_exceptions_ref", "si_prefixes_ref", "permitted_units_ref",
                    "si_base_ref"):
            ref = rule.opt(key)
            if ref and ref not in pack.tables:
                problems.append(f"{rule.id}.{key} -> unknown table '{ref}'")

        if rule.on_locate_fail and rule.on_locate_fail not in ids:
            problems.append(f"{rule.id}.on_locate_fail -> unknown rule '{rule.on_locate_fail}'")

        if rule.suppresses and rule.suppresses not in ids:
            problems.append(f"{rule.id}.suppresses -> unknown rule '{rule.suppresses}'")

        # Only the rule named by on_locate_fail may report a missing declaration.
        if rule.check == "regex" and rule.opt("locate_ref") and not rule.on_locate_fail:
            problems.append(
                f"{rule.id} validates with a strict pattern but names no on_locate_fail; "
                f"a formatting question could escalate into a missing-declaration verdict"
            )

    duplicates = [i for i in ids if sum(1 for r in pack.all_rules() if r.id == i) > 1]
    if duplicates:
        problems.append(f"duplicate rule ids: {sorted(set(duplicates))}")

    if problems:
        raise RulepackError("rulepack validation failed:\n  - " + "\n  - ".join(problems))


def load_rulepack(path: str | Path | None = None) -> Rulepack:
    """Read, compile and validate a rulepack from disk."""
    p = Path(path) if path else DEFAULT_PACK
    if not p.exists():
        raise RulepackError(f"rulepack not found: {p}")

    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RulepackError(f"rulepack {p} did not parse to a mapping")

    meta = raw.get("meta") or {}
    pack = Rulepack(
        pack_id=meta.get("pack_id", p.stem),
        version=str(meta.get("version", "0")),
        authority=meta.get("authority", ""),
        rules=tuple(_build_rule(r) for r in raw.get("rules") or ()),
        extension_rules=tuple(_build_rule(r) for r in raw.get("extension_rules") or ()),
        patterns=_compile_patterns(raw.get("patterns") or {}),
        tables=raw.get("tables") or {},
        applicability=raw.get("applicability") or {},
        meta=meta,
    )
    _validate(pack)
    return pack


@lru_cache(maxsize=4)
def cached_rulepack(path: str | None = None) -> Rulepack:
    """Process-wide cached load. The pack is immutable, so sharing is safe."""
    return load_rulepack(path)


__all__ = ["DEFAULT_PACK", "RulepackError", "cached_rulepack", "load_rulepack"]
