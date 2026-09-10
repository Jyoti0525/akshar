import { Badge, toneForStatus } from "@/components/ui/badge";
import { millimetres, ruleLabel } from "@/lib/format";
import type { Verdict } from "@/lib/api/types";

/**
 * Section 11: *"Below, one row per rule."*
 *
 * Three decisions worth stating.
 *
 * **The rule's name leads, not its message.** The message answers "what went
 * wrong"; on a passing rule there is no wrong, so the row has to answer "which
 * requirement is this" instead — and an officer scanning thirty-odd rows is
 * looking for the requirement, not reading prose.
 *
 * **Every row carries the gazette reference**, because section 2's fifth point
 * is that *"every verdict cites a gazette clause"* and a citation that only
 * appears in the PDF is a citation the officer cannot read while standing in
 * the shop.
 *
 * **`measured` against `threshold` is two numbers, never a sentence.** A notice
 * is written from those two numbers, and re-deriving them from prose is where a
 * transcription error enters an enforcement document.
 *
 * The settled rules are folded into a `<details>`. Not to hide them — the count
 * is in the summary and one click opens the lot, and `@media print` in
 * `globals.css` opens every `<details>` so a printed record is complete. It is
 * because thirty green rows above the fold push the one amber row that needs a
 * decision off the screen, which inverts the whole point of the page.
 */
const ORDER: Record<string, number> = { FAIL: 0, REVIEW: 1, NO_DATA: 2, PASS: 3, NOT_APPLICABLE: 4 };

/** Statuses that need the reader's attention. Everything else is settled. */
const OPEN = new Set(["FAIL", "REVIEW", "NO_DATA"]);

function Row({ verdict }: { verdict: Verdict }) {
  return (
    <li className="rounded-lg border border-border bg-surface p-3">
      <div className="flex flex-wrap items-start gap-3">
        <Badge tone={toneForStatus(verdict.status)}>{verdict.status.replace("_", " ")}</Badge>
        <div className="min-w-0 flex-1">
          <p className="font-medium text-fg">{ruleLabel(verdict.rule_id)}</p>
          <p className="mt-0.5 text-base text-fg-muted">{verdict.message}</p>
          <p className="mt-0.5 text-sm text-fg-muted">
            <span title={verdict.rule_id}>{verdict.rule_ref || verdict.rule_id}</span>
            {verdict.field ? <> · {verdict.field.replace(/_/g, " ")}</> : null}
            {verdict.severity ? <> · {verdict.severity} severity</> : null}
            {verdict.advisory ? (
              <>
                {" "}
                ·{" "}
                <span title="Advisory checks fire often by design and are not, on their own, a violation.">
                  advisory
                </span>
              </>
            ) : null}
            {verdict.respondent ? <> · respondent: {verdict.respondent}</> : null}
          </p>
          {verdict.suppressed_by ? (
            <p className="mt-0.5 text-sm text-fg-muted">
              Not counted: superseded by {verdict.suppressed_by}.
            </p>
          ) : null}
        </div>
        {verdict.measured !== null && verdict.measured !== undefined ? (
          <div className="text-right tabular-nums">
            <p className="text-lg font-semibold">
              {millimetres(verdict.measured)}
              {verdict.tolerance ? (
                <span className="text-sm font-normal text-fg-muted">
                  {" "}
                  ±{verdict.tolerance.toFixed(2)}
                </span>
              ) : null}
            </p>
            {verdict.threshold !== null && verdict.threshold !== undefined ? (
              <p className="text-sm text-fg-muted">required {millimetres(verdict.threshold)}</p>
            ) : null}
          </div>
        ) : null}
      </div>
    </li>
  );
}

export function RuleRows({ verdicts }: { verdicts: Verdict[] | undefined }) {
  if (!verdicts || verdicts.length === 0) {
    return (
      <p className="rounded-lg border border-border bg-surface p-4 text-base text-fg-muted">
        No rule was evaluated. Nothing on this photograph could be read.
      </p>
    );
  }

  const sorted = [...verdicts].sort(
    (a, b) =>
      (ORDER[a.status] ?? 9) - (ORDER[b.status] ?? 9) || a.rule_id.localeCompare(b.rule_id),
  );
  const open = sorted.filter((v) => OPEN.has(v.status));
  const settled = sorted.filter((v) => !OPEN.has(v.status));
  const passed = settled.filter((v) => v.status === "PASS").length;

  return (
    <div className="flex flex-col gap-3">
      {open.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {open.map((verdict) => (
            <Row key={`${verdict.rule_id}:${verdict.field ?? ""}`} verdict={verdict} />
          ))}
        </ul>
      ) : (
        <p className="rounded-lg border border-pass bg-pass-bg p-4 text-base text-pass-fg">
          Nothing on this package needs a decision. All {passed} applicable rules passed.
        </p>
      )}

      {settled.length > 0 ? (
        <details className="rounded-lg border border-border bg-surface-2">
          <summary className="flex min-h-touch cursor-pointer items-center px-3 py-2 text-base font-medium">
            {passed} passed
            {settled.length - passed > 0 ? `, ${settled.length - passed} not applicable` : ""} —
            show the full rule-by-rule record
          </summary>
          <ul className="flex flex-col gap-2 p-2 pt-0">
            {settled.map((verdict) => (
              <Row key={`${verdict.rule_id}:${verdict.field ?? ""}`} verdict={verdict} />
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
