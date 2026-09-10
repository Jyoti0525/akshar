"""The L0-L4 ladder — AKSHAR.md section 5.

    "The system must never simply fail. It degrades, and always reports which
     tier produced the answer."

    | L0 | Online                | Everything: full cache, explainer, live sync |
    | L1 | No network            | Full local scan, local cache, queued sync    |
    | L2 | No marker, unknown SKU| Ratio checks, presence, format, placement    |
    | L3 | OCR partly failed     | Coverage % reported; verdicts on what was read |
    | L4 | Nothing readable      | Photo stored with geo and timestamp, queued  |

    "L4 is the one people forget. Even in the worst case the officer walks away
     with a timestamped evidence record. **A tool that returns nothing when it
     can't read is worse than a notebook.**"

**These are not one axis.** L1 is about the network, L2 about scale recovery,
L3 about recognition. All three can be true at once — an officer in a basement
market, with no marker, photographing a crumpled foil pack. So the reported tier
is the *worst* condition present, and every condition that applies is listed
alongside it. Reporting only "L2" would hide from the officer that the label
was also half-unreadable.

**The tier is a promise about what was checked, not an excuse.** It tells the
reader which of the thirty-one rules could run. That is why it is stored on the
scan and printed on the report rather than being an internal log line.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from contracts import DegradationTier, ScaleTier

_WORD_SHAPE = re.compile(r"[A-Za-z\u0900-\u097F]{3,}|\d{2,}")
"""What a read line looks like when reading worked. See `legible_fraction`."""

COVERAGE_FLOOR = 0.60
"""Below this fraction of proposed text regions read, the scan is L3.

Not zero: a label with a large ingredients panel proposes regions we correctly
decline to read, so partial coverage is normal. 0.60 is the point at which
enough of the *declarations* are likely missing that the officer should be told
the verdict rests on an incomplete reading."""

MIN_LINES_FOR_A_VERDICT = 2
"""One recognised line is not a label. At or below this we are at L4: store the
photograph, the timestamp and the location, and queue it for a human."""

LEGIBLE_FLOOR = 0.50
"""Below this share of read lines carrying word-shaped text, the scan is L3.

**`coverage` was never a measure of whether recognition worked**, and treating
it as one is what let a badly-read label reach the rules engine as L2. It is the
fraction of proposed regions the recogniser was *run on*, and we run it on
nearly everything we propose, so it sits near 1.0 whatever comes back. Measured
on 2026-09-09 over fourteen frames, one pack returned three lines of pure noise
at coverage 1.00 and median recogniser confidence 0.995 — CTC is confidently
wrong, so neither number separates a label we read from one we did not.

What does separate them is whether the output has the *shape* of language. A
frame that reads `'wYVNOvr 9I'`, `'DCLA'`, `'CFRO'`, `'A EA'` has not been read,
whatever the confidence says.

The floor is a round half rather than a fitted value, and it is deliberately not
tuned: `data/test_split/` is sealed, and a threshold chosen to make a particular
photograph pass is exactly the fitting that seal exists to prevent. What it must
be is *some* honest bar below which we decline to allege an absence."""


def legible_fraction(texts: Sequence[str]) -> float:
    """Share of read lines that look like language rather than scattered glyphs.

    A line counts as legible if it carries a run of three or more letters in
    either script, or two or more consecutive digits. That is a **shape** test,
    not a lexicon: a dictionary would need one per language and would mark a
    correctly-read brand name or a batch code as noise. `'MRP'`, `'242'` and
    `'निर्माता'` all pass; `'A EA'`, `'D'` and `'8]'` do not.

    Returns 1.0 for an empty input rather than 0.0. No lines read is L4's
    business, decided by `MIN_LINES_FOR_A_VERDICT`, and returning 0.0 here would
    put a second condition on the same fact and report it twice.
    """
    if not texts:
        return 1.0
    legible = sum(1 for text in texts if _WORD_SHAPE.search(text))
    return legible / len(texts)


@dataclass(frozen=True, slots=True)
class Degradation:
    """Which tier answered, and everything that pushed it there."""

    tier: DegradationTier
    reasons: tuple[str, ...] = ()
    """Every condition that applied, worst first. Printed on the report."""

    checks_available: str = ""
    """One sentence an officer can read: what this scan could and could not
    decide. The report shows this verbatim."""

    @property
    def is_usable(self) -> bool:
        """False only at L4, where there are no verdicts — just evidence."""
        return self.tier != "L4"


_AVAILABLE: dict[DegradationTier, str] = {
    "L0": "All checks ran, with live rule explanations and sync.",
    "L1": "All checks ran locally; the record is queued and will sync when a network returns.",
    "L2": (
        "No scale was recovered, so the three absolute height rules returned NO_DATA. "
        "Presence, format, placement, unit-symbol and the two ratio rules all ran."
    ),
    "L3": (
        "Part of the label could not be read. Verdicts cover only what was read, "
        "and the coverage figure is shown beside them."
    ),
    "L4": (
        "Nothing legible was recovered. No verdicts were issued. The photograph, "
        "timestamp and location are stored as an evidence record for review."
    ),
}


def assign(
    *,
    online: bool = True,
    scale_tier: ScaleTier | None = None,
    coverage: float = 1.0,
    lines_read: int = 0,
    detector_ran: bool = True,
    legible: float = 1.0,
) -> Degradation:
    """Worst applicable tier, with every applicable reason.

    `detector_ran` is False when the model weights were absent. That is a real
    operational state — a browser that evicted its model cache mid-inspection —
    and it degrades the scan rather than failing it, because geometry, regex
    classification and every textual rule still work without the detector.

    `legible` is `legible_fraction` over the lines that were read, and it is the
    condition `coverage` was wrongly being asked to carry. Both push to L3, and
    both are reported, because "we read most of the regions and none of them
    were words" and "we skipped most of the regions" are different failures with
    different fixes — one is a recogniser problem and the other is a budget one.
    """
    reasons: list[str] = []

    nothing_readable = lines_read < MIN_LINES_FOR_A_VERDICT
    illegible = legible < LEGIBLE_FLOOR
    partly_failed = coverage < COVERAGE_FLOOR or illegible
    no_scale = scale_tier is None or scale_tier == "C"

    if nothing_readable:
        reasons.append(f"only {lines_read} legible line(s) recovered")
    if coverage < COVERAGE_FLOOR:
        reasons.append(f"coverage {coverage:.0%} of proposed text regions")
    if illegible:
        reasons.append(f"only {legible:.0%} of the lines read carry word-shaped text")
    if no_scale:
        reasons.append("no reference object and no stored dimensions for this SKU")
    if not detector_ran:
        reasons.append("detector weights unavailable; geometry-only region proposal")
    if not online:
        reasons.append("no network; the scan is queued for sync")

    # Worst condition wins. Checked in severity order, not in the order the
    # facts were gathered.
    if nothing_readable:
        tier: DegradationTier = "L4"
    elif partly_failed:
        tier = "L3"
    elif no_scale:
        tier = "L2"
    elif not online:
        tier = "L1"
    else:
        tier = "L0"

    return Degradation(
        tier=tier,
        reasons=tuple(reasons),
        checks_available=_AVAILABLE[tier],
    )


__all__ = [
    "COVERAGE_FLOOR",
    "LEGIBLE_FLOOR",
    "MIN_LINES_FOR_A_VERDICT",
    "Degradation",
    "assign",
    "legible_fraction",
]
