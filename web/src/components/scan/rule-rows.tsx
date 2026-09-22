import { Badge, toneForStatus } from "@/components/ui/badge";
import {
  PLAIN_STATUS,
  PLAIN_STATUS_MEANING,
  fieldLabel,
  quantity,
  ruleLabel,
  ruleMeaning,
} from "@/lib/format";
import type { Verdict } from "@/lib/api/types";

/**
 * Section 11: *"Below, one row per rule."*
 *
 * ---------------------------------------------------------------------------
 * WRITTEN FOR SOMEONE WHO HAS NEVER SEEN THE SYSTEM
 * ---------------------------------------------------------------------------
 * Rewritten 2026-09-10. The page was correct and unreadable: thirty-seven rows,
 * every one headed with an engine word (`NO_DATA`), a gazette citation, a
 * severity and a respondent. A junior officer in a shop could not tell in two
 * seconds whether the pack was a problem, and a panel of judges reading it over
 * a shoulder saw `NO_DATA` and heard *crash*.
 *
 * Three changes, and none of them removes a fact from the record:
 *
 * **The status is said in words.** `Problem`, `Officer to check`, `OK`,
 * `Not measured`. The engine's own vocabulary stays in the exported report and
 * in the evidence row; this is the label on the screen. `NO_DATA` does not mean
 * failure — it means *we did not have what this check needs, so we did not
 * guess*, and that sentence is now printed where it is read.
 *
 * **Each rule says what it is for.** One sentence of shop language above the
 * gazette reference: "The pack must give a contact for complaints, with a phone
 * number." The citation is still there, one line down, for anyone who wants it.
 *
 * **Unmeasured rules collapse to one line.** At scale tier C, thirty-odd height
 * rules honestly return NO_DATA for one reason — no calibration card in the
 * photograph — and thirty rows saying so buried the one row that mattered. They
 * are now a single line with the reason and a count, and one click still opens
 * every one of them. `@media print` in `globals.css` opens every `<details>`,
 * so a printed record is complete.
 *
 * **`measured` against `threshold` is two numbers, never a sentence.** A notice
 * is written from those two numbers, and re-deriving them from prose is where a
 * transcription error enters an enforcement document.
 */
const ORDER: Record<string, number> = { FAIL: 0, REVIEW: 1, NO_DATA: 2, PASS: 3, NOT_APPLICABLE: 4 };

function Row({ verdict }: { verdict: Verdict }) {
  const meaning = ruleMeaning(verdict.rule_id);
  return (
    <li className="rounded-lg border border-border bg-surface p-3">
      <div className="flex flex-wrap items-start gap-3">
        <Badge tone={toneForStatus(verdict.status)}>
          {PLAIN_STATUS[verdict.status] ?? verdict.status.replace("_", " ")}
        </Badge>
        <div className="min-w-0 flex-1">
          <p className="font-medium text-fg">{ruleLabel(verdict.rule_id)}</p>
          {meaning ? <p className="mt-0.5 text-base text-fg">{meaning}</p> : null}
          <p className="mt-0.5 text-base text-fg-muted">{verdict.message}</p>
          <p className="mt-0.5 text-sm text-fg-muted">
            <span title={verdict.rule_id}>{verdict.rule_ref || verdict.rule_id}</span>
            {verdict.field ? <> · {fieldLabel(verdict.field)}</> : null}
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
            {verdict.respondent ? <> · answerable: {verdict.respondent}</> : null}
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
              {quantity(verdict.measured, verdict.unit)}
              {verdict.tolerance ? (
                <span className="text-sm font-normal text-fg-muted">
                  {" "}
                  ±{verdict.tolerance.toFixed(2)}
                </span>
              ) : null}
            </p>
            {verdict.threshold !== null && verdict.threshold !== undefined ? (
              <p className="text-sm text-fg-muted">
                required {quantity(verdict.threshold, verdict.unit)}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </li>
  );
}

/** One collapsed group. The count and the reason are in the summary, so the
 *  reader never has to open it to know what is inside. */
function Group({
  title,
  reason,
  verdicts,
}: {
  title: string;
  reason: string;
  verdicts: Verdict[];
}) {
  if (verdicts.length === 0) return null;
  return (
    <details className="rounded-lg border border-border bg-surface-2">
      {/* The layout goes on a DIV inside the summary, never on the summary.
          `display: flex` takes a `<summary>` out of `list-item`, and Chromium
          then drops the disclosure marker and stops treating the element as the
          toggle — the group renders, says "16 rules passed", and does nothing
          when clicked. `list-item` is restored explicitly rather than left to
          the user agent, because Tailwind's preflight resets it. */}
      <summary className="min-h-touch cursor-pointer list-item px-3 py-2 marker:text-fg-muted">
        <div className="flex flex-col justify-center">
          <span className="text-base font-medium">
            {verdicts.length} {title}
          </span>
          <span className="text-sm text-fg-muted">{reason}</span>
        </div>
      </summary>
      <ul className="flex flex-col gap-2 p-2 pt-0">
        {verdicts.map((verdict) => (
          <Row key={`${verdict.rule_id}:${verdict.field ?? ""}`} verdict={verdict} />
        ))}
      </ul>
    </details>
  );
}

function Heading({ children }: { children: React.ReactNode }) {
  return <h3 className="text-base font-semibold text-fg">{children}</h3>;
}

export function RuleRows({ verdicts }: { verdicts: Verdict[] | undefined }) {
  if (!verdicts || verdicts.length === 0) {
    return (
      <p className="rounded-lg border border-border bg-surface p-4 text-base text-fg-muted">
        No rule was checked. Nothing on this photograph could be read.
      </p>
    );
  }

  const sorted = [...verdicts].sort(
    (a, b) =>
      (ORDER[a.status] ?? 9) - (ORDER[b.status] ?? 9) || a.rule_id.localeCompare(b.rule_id),
  );

  // An advisory failure is a formatting defect — `250 ML` for `250 ml`. It is
  // reported, and it does not sit beside a missing MRP under one heading.
  const problems = sorted.filter((v) => v.status === "FAIL" && !v.advisory);
  const minor = sorted.filter((v) => v.status === "FAIL" && v.advisory);
  const toCheck = sorted.filter((v) => v.status === "REVIEW");
  const passed = sorted.filter((v) => v.status === "PASS");
  const notMeasured = sorted.filter((v) => v.status === "NO_DATA");
  const notApplicable = sorted.filter((v) => v.status === "NOT_APPLICABLE");

  return (
    <div className="flex flex-col gap-4">
      {problems.length > 0 ? (
        <section className="flex flex-col gap-2">
          <Heading>
            {problems.length === 1 ? "1 problem found" : `${problems.length} problems found`}
          </Heading>
          <p className="text-sm text-fg-muted">{PLAIN_STATUS_MEANING.FAIL ?? ""}</p>
          <ul className="flex flex-col gap-2">
            {problems.map((v) => (
              <Row key={`${v.rule_id}:${v.field ?? ""}`} verdict={v} />
            ))}
          </ul>
        </section>
      ) : null}

      {toCheck.length > 0 ? (
        <section className="flex flex-col gap-2">
          <Heading>
            {/* Not "for you to check". Whoever is reading this, the person who
                settles a REVIEW is a supervisor, and on an officer's screen the
                old wording promised an action the role cannot perform. */}
            {toCheck.length === 1
              ? "1 thing a supervisor must settle"
              : `${toCheck.length} things a supervisor must settle`}
          </Heading>
          <p className="text-sm text-fg-muted">{PLAIN_STATUS_MEANING.REVIEW ?? ""}</p>
          <ul className="flex flex-col gap-2">
            {toCheck.map((v) => (
              <Row key={`${v.rule_id}:${v.field ?? ""}`} verdict={v} />
            ))}
          </ul>
        </section>
      ) : null}

      {problems.length === 0 && toCheck.length === 0 ? (
        <p className="rounded-lg border border-pass bg-pass-bg p-4 text-base text-pass-fg">
          No problem found, and nothing needs your decision. {passed.length} rules checked and
          passed.
        </p>
      ) : null}

      <Group
        title="minor formatting points"
        reason="Wrong capitals or spacing in a unit symbol. Reported, but not a violation on their own."
        verdicts={minor}
      />
      <Group
        title="rules passed"
        reason={PLAIN_STATUS_MEANING.PASS ?? ""}
        verdicts={passed}
      />
      <Group
        title="checks we could not measure"
        reason="Mostly the height rules — they need the calibration card in the photograph. We do not guess a measurement."
        verdicts={notMeasured}
      />
      <Group
        title="rules that do not apply"
        reason={PLAIN_STATUS_MEANING.NOT_APPLICABLE ?? ""}
        verdicts={notApplicable}
      />
    </div>
  );
}
