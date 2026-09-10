"""Score the ruler set. AKSHAR.md sections 18b (U1) and 19.

    python scripts/u1_report.py data/marker_card/u1_ground_truth.csv

**What this answers is not "was that measurement right".** It is "how wrong are
we, in general, and do we say so honestly" — and the second half is the one that
travels to the thousands of packets nobody will ever measure with a rule.

§18b sets U1 as mean absolute error ≤ 0.15 mm and p95 ≤ 0.25 mm. That is
*accuracy*, and accuracy alone is not enough to decide a compliance case,
because the decision is not "what is the height" but "is the height above the
threshold". `rules/checks/min_height_mm.py` makes that decision with a band:

    measured >= threshold                 -> PASS
    measured + tolerance >= threshold     -> REVIEW   (inside our own error)
    otherwise                             -> FAIL

So the tolerance is what stands between a compliant pack and a wrongful FAIL.
If it is systematically too narrow the band is too narrow, and packs that were
inside our error get convicted. If it is enormous everything becomes REVIEW and
the tool is useless. **Neither failure shows up in MAE**, which is why this
reports a third number the plan does not ask for:

    coverage  — the share of frames where |truth - measured| <= tolerance

That is the calibration check. A well-behaved tolerance covers most of the
error; a dishonest one does not, and MAE can look excellent either way.

**Neither number can see a single bad frame, and this file does not pretend
otherwise.** At 40 readings the 95th percentile is the 38th value, so one or two
blunders pass every threshold here. That is not a flaw to be patched with a
fourth gate invented on the spot — it is the resolution of the statistic. So the
per-frame table is printed in full, and any frame whose truth fell outside its
own tolerance is named. A person reads those.

**Frames the pipeline could not measure are reported, never dropped.** Averaging
over the twelve frames that worked and calling it the U1 result would be the
same arithmetic mistake §11 forbids on the dashboard: excluding `NO_DATA` from
the numerator while quietly excluding it from the question too. The summary
prints `measured / total` first, and refuses to declare U1 met when too much of
the set went unread.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MAE_TARGET_MM = 0.15
P95_TARGET_MM = 0.25
"""§18b U1, verbatim. Both must hold; the plan is explicit that the mean alone
is not the criterion, because a mean of 0.14 mm hiding a 2 mm outlier is a tool
that will be wrong in court once."""

COVERAGE_TARGET = 0.90
"""Share of frames whose true height must fall inside the claimed tolerance.

Not from the plan — it is the criterion the REVIEW band implies and nobody wrote
down. At 90%, roughly one frame in ten has a true value outside our stated
error, which is tolerable for a band that only ever *widens* the benefit of the
doubt. Much below that and the band is a fiction, and the fiction's cost is
falsely failing a compliant manufacturer."""

MIN_MEASURED_SHARE = 0.75
"""Below this, the set is not scored at all. A U1 result computed on half the
frames is a statement about the easy half."""


@dataclass(frozen=True, slots=True)
class Reading:
    """One frame: what the rule said, what we said, and what we claimed to know."""

    filename: str
    truth_mm: float
    measured_mm: float | None = None
    tolerance_mm: float | None = None
    product: str = ""
    """Which packet this is a photograph of. Two frames share it, and that is
    what makes repeatability measurable — see `Report.repeatability_mm`."""

    note: str = ""

    @property
    def error_mm(self) -> float | None:
        return None if self.measured_mm is None else abs(self.measured_mm - self.truth_mm)

    @property
    def covered(self) -> bool | None:
        """Did the truth land inside the tolerance we claimed for that frame?"""
        error = self.error_mm
        if error is None or self.tolerance_mm is None:
            return None
        return error <= self.tolerance_mm


@dataclass(frozen=True, slots=True)
class Report:
    total: int
    measured: int
    mae_mm: float | None
    p95_mm: float | None
    worst_mm: float | None
    coverage: float | None
    median_tolerance_mm: float | None
    bias_mm: float | None
    repeatability_mm: float | None = None
    """Mean spread between the two shots of one packet, in millimetres.

    **The only number here that needs no ground truth at all**, which is exactly
    why the plan asks for 40 photos of 20 SKUs rather than 40 of 40. The ruler
    reading and the AKSHAR reading are two different measurements with two
    different error sources, and a single photo per packet cannot separate them:
    if they disagree by 0.2 mm, that is either our measurement or the hand
    holding the rule, and nothing in the data says which.

    Two shots of the *same* printed digit fix that. The digit's true height did
    not change between them, so any disagreement between the two AKSHAR readings
    is ours alone. Subtract it from the total error and what remains is the
    reading error — and if repeatability is large, no amount of careful ruler
    work will rescue the result."""

    uncovered: tuple[str, ...] = ()
    """Frames whose true height fell outside the tolerance we claimed for them.

    Named rather than counted, because **p95 cannot see a single bad frame.**
    With 40 readings the 95th percentile is the 38th value, so one or two
    blunders — the wrong glyph measured, a card that was not quite flat — sit
    below it and pass. Those frames are exactly the ones worth looking at by
    hand, and a count sends somebody hunting for them.""" 

    @property
    def measured_share(self) -> float:
        return 0.0 if not self.total else self.measured / self.total

    @property
    def scorable(self) -> bool:
        return self.measured_share >= MIN_MEASURED_SHARE and self.measured > 0

    def verdict(self) -> tuple[bool, list[str]]:
        """U1 met, and the reasons it was not. Reasons first, boolean second."""
        problems: list[str] = []
        if not self.scorable:
            problems.append(
                f"only {self.measured}/{self.total} frames were measured "
                f"({self.measured_share:.0%}); a result from the readable subset "
                f"is a statement about the easy half"
            )
            return False, problems

        if self.mae_mm is not None and self.mae_mm > MAE_TARGET_MM:
            problems.append(f"MAE {self.mae_mm:.3f} mm exceeds {MAE_TARGET_MM} mm")
        if self.p95_mm is not None and self.p95_mm > P95_TARGET_MM:
            problems.append(f"p95 {self.p95_mm:.3f} mm exceeds {P95_TARGET_MM} mm")
        if self.coverage is not None and self.coverage < COVERAGE_TARGET:
            problems.append(
                f"coverage {self.coverage:.0%} is under {COVERAGE_TARGET:.0%}: the "
                f"tolerance we report is narrower than our real error, so the "
                f"REVIEW band will convict packs that were inside it"
            )
        return not problems, problems


def summarise(readings: list[Reading]) -> Report:
    """Pure arithmetic over the readings. No images, no models, no files."""
    measured = [r for r in readings if r.error_mm is not None]
    errors = sorted(r.error_mm for r in measured)  # type: ignore[misc]
    covered = [r.covered for r in measured if r.covered is not None]
    tolerances = [r.tolerance_mm for r in measured if r.tolerance_mm is not None]

    # Signed, not absolute: a bias means the scale is off by a constant factor —
    # a mis-sized card, say — which is a different bug from noisy measurement and
    # is invisible in MAE.
    signed = [
        r.measured_mm - r.truth_mm  # type: ignore[operator]
        for r in measured
        if r.measured_mm is not None
    ]

    return Report(
        total=len(readings),
        measured=len(measured),
        mae_mm=statistics.fmean(errors) if errors else None,
        p95_mm=_percentile(errors, 0.95) if errors else None,
        worst_mm=errors[-1] if errors else None,
        coverage=(sum(covered) / len(covered)) if covered else None,
        repeatability_mm=_repeatability(measured),
        uncovered=tuple(r.filename for r in measured if r.covered is False),
        median_tolerance_mm=statistics.median(tolerances) if tolerances else None,
        bias_mm=statistics.fmean(signed) if signed else None,
    )


def _repeatability(measured: list[Reading]) -> float | None:
    """Mean within-packet spread. None when no packet was shot twice.

    The spread is max-minus-min rather than a standard deviation because there
    are two samples per group: with n=2 a standard deviation is the range
    divided by a constant, and the range is the thing a person can actually
    picture ("the two shots differed by 0.06 mm").
    """
    groups: dict[str, list[float]] = {}
    for reading in measured:
        if reading.product and reading.measured_mm is not None:
            groups.setdefault(reading.product, []).append(reading.measured_mm)

    spreads = [max(values) - min(values) for values in groups.values() if len(values) > 1]
    return statistics.fmean(spreads) if spreads else None


def _percentile(ordered: list[float], q: float) -> float:
    """Nearest-rank percentile on an already-sorted list.

    Nearest-rank rather than interpolated, deliberately: with 40 samples the p95
    is the 38th value, and interpolating between two real measurements invents a
    number that no frame produced. For a figure that decides a go/no-go, an
    actual observation is worth more than a smoother estimate.
    """
    if not ordered:
        raise ValueError("no values")
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


# ---------------------------------------------------------------------------
# Reading the set
# ---------------------------------------------------------------------------


def load_ground_truth(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.DictReader(handle) if row.get("filename")]


def measure_frame(image_path: Path, field: str) -> tuple[float | None, float | None, str]:
    """Run the real pipeline and pull out the declaration this row names.

    Returns `(height_mm, tolerance_mm, note)`. The note is why a frame went
    unmeasured, in words — "no scale recovered (tier C)" and "declaration not
    read" are different failures with different fixes, and a bare `None` would
    hide which one happened on which frame.
    """
    import cv2

    from vision.pipeline import scan

    image = cv2.imread(str(image_path))
    if image is None:
        return None, None, "file could not be read"

    outcome = scan(image, source="photo")
    if outcome.declarations is None:
        return None, None, f"nothing legible ({outcome.degradation.tier})"

    matches = [d for d in outcome.declarations.declarations if d.field == field]
    if not matches:
        return None, None, f"no {field} declaration was read"

    # The best-supported reading, not the biggest one. Ranking by `height_mm`
    # picks whichever candidate measured tallest, which on a pack with two
    # price-shaped fragments is a scoring rule that walks the benchmark's
    # error upward on purpose.
    measured = [d for d in matches if d.height_mm is not None]
    if not measured:
        tier = outcome.scale.tier if outcome.scale else "C"
        if tier == "C":
            return None, None, "no scale recovered (tier C); card in frame?"
        # Scale is fine; the figure is what is missing. Reporting this as a
        # scale failure sent seven frames of the ruler set to the wrong
        # diagnosis, and a benchmark that misnames its own failures is worse
        # than one that only counts them.
        return None, None, f"{field} found but its figure was not measurable (tier {tier})"

    best = max(measured, key=lambda d: (d.field_confidence, d.ocr_confidence))
    return best.height_mm, best.height_mm_tolerance, ""


def collect(rows: list[dict[str, str]], images_dir: Path) -> list[Reading]:
    readings: list[Reading] = []
    for row in rows:
        filename = row["filename"].strip()
        truth = float(row["measured_mm"])
        field = (row.get("field") or "mrp").strip()
        measured, tolerance, note = measure_frame(images_dir / filename, field)
        readings.append(
            Reading(
                filename=filename,
                truth_mm=truth,
                measured_mm=measured,
                tolerance_mm=tolerance,
                # `product` plus `pack_size` is the grouping key, not `product`
                # alone: section 10 is emphatic that 30 g and 100 g of one
                # product are different SKUs with different height thresholds,
                # and averaging their shots together would be the same mistake
                # in the scoring that it is in the database.
                product=f"{row.get('product', '').strip()} {row.get('pack_size', '').strip()}".strip(),
                note=note,
            )
        )
    return readings


def render(readings: list[Reading], report: Report) -> str:
    lines = [
        f"{'frame':<34} {'ruler':>8} {'AKSHAR':>8} {'error':>8} {'+/-tol':>8}  in?",
        "-" * 78,
    ]
    for r in readings:
        if r.measured_mm is None:
            lines.append(f"{r.filename:<34} {r.truth_mm:>8.2f} {'-':>8} {'-':>8} {'-':>8}  {r.note}")
            continue
        mark = {True: "yes", False: "NO", None: "-"}[r.covered]
        tol = "-" if r.tolerance_mm is None else f"{r.tolerance_mm:.3f}"
        lines.append(
            f"{r.filename:<34} {r.truth_mm:>8.2f} {r.measured_mm:>8.2f} "
            f"{r.error_mm:>8.3f} {tol:>8}  {mark}"
        )

    ok, problems = report.verdict()
    lines += [
        "",
        f"frames measured   : {report.measured}/{report.total} ({report.measured_share:.0%})",
    ]
    if report.mae_mm is not None:
        lines += [
            f"MAE               : {report.mae_mm:.3f} mm   (U1 target <= {MAE_TARGET_MM})",
            f"p95               : {report.p95_mm:.3f} mm   (U1 target <= {P95_TARGET_MM})",
            f"worst             : {report.worst_mm:.3f} mm",
            f"systematic bias   : {report.bias_mm:+.3f} mm   (a constant offset means the "
            f"card size is wrong, not that the measurement is noisy)",
        ]
    if report.repeatability_mm is not None:
        lines.append(
            f"repeatability     : {report.repeatability_mm:.3f} mm   (spread between the two "
            f"shots of one packet - ours alone, no ruler involved)"
        )
    if report.coverage is not None:
        lines.append(
            f"tolerance coverage: {report.coverage:.0%}     (target >= {COVERAGE_TARGET:.0%}; "
            f"median claimed tolerance {report.median_tolerance_mm:.3f} mm)"
        )
    lines += ["", "U1: MET" if ok else "U1: NOT MET"]
    lines += [f"  - {problem}" for problem in problems]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ground_truth", type=Path)
    parser.add_argument(
        "--images",
        type=Path,
        default=None,
        help="directory holding the frames (default: beside the CSV)",
    )
    args = parser.parse_args()

    rows = load_ground_truth(args.ground_truth)
    if not rows:
        print(f"{args.ground_truth} has no rows with a filename")
        return 1

    images = args.images or args.ground_truth.parent
    readings = collect(rows, images)
    report = summarise(readings)
    print(render(readings, report))
    return 0 if report.verdict()[0] else 1


if __name__ == "__main__":
    raise SystemExit(main())
