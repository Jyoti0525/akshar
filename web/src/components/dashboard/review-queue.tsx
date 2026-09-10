"use client";

import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiFetch } from "@/lib/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/alert";
import { dateTime, percent, ruleLabel } from "@/lib/format";
import type { ReviewRow } from "@/lib/api/types";

/**
 * Section 11: *"The review queue... It's a worklist, not a chart, and it belongs
 * on the front page because it's the only thing there representing work owed by
 * the person looking at it."* Section 8b adds: *"every REVIEW verdict lands
 * there, one-click resolve, resolution stored as a labelled example for
 * retraining."*
 *
 * ---------------------------------------------------------------------------
 * ONE QUESTION PER RULE, NOT ONE PER SCAN
 * ---------------------------------------------------------------------------
 * This used to be a single "Confirm as read" button that posted a correction
 * with a guessed field name, because `POST /scans/{id}/review` did not exist and
 * inventing a status change on the client would have been a lie told in a
 * progress indicator. The endpoint exists now, and it refuses a rule that never
 * asked for review — so the button had to become as specific as the question.
 *
 * A scan reaches this list because one or more *named rules* came back REVIEW. A
 * marginal MRP height and an unreadable net quantity are two different
 * judgements and one click cannot settle both, so each outstanding rule gets its
 * own row of choices. Answering one leaves the scan here with the rest of its
 * rules; answering the last one removes it.
 *
 * ---------------------------------------------------------------------------
 * WHY THERE ARE THREE CHOICES AND NOT TWO
 * ---------------------------------------------------------------------------
 * Section 8b issues REVIEW when a measurement lands inside tolerance of a
 * threshold — 1.96 mm against a 2.00 mm minimum. The honest answer to that is
 * very often neither verdict: it is *photograph it again with the card flat*.
 * Offering only Complies and Does not comply would push a coin-flip into an
 * enforcement record, and then feed the coin-flip back into training as a
 * labelled example.
 *
 * The scan itself is never edited. Section 5 makes it an immutable fact whose
 * hash is in the evidence chain, so the verdict still reads REVIEW afterwards
 * and the resolution is a separate append-only row beside it.
 */

type Decision = "complies" | "does_not_comply" | "recapture";

const CHOICES: { decision: Decision; label: string; title: string }[] = [
  {
    decision: "complies",
    label: "Complies",
    title: "The declaration meets the rule. Recorded against your name.",
  },
  {
    decision: "does_not_comply",
    label: "Does not",
    title: "The declaration breaches the rule. Recorded against your name.",
  },
  {
    decision: "recapture",
    label: "Re-photograph",
    title: "The frame is not good enough to decide. Sends it back for another photograph.",
  },
];

export function ReviewQueue({ rows }: { rows: ReviewRow[] }) {
  const client = useQueryClient();
  // Keyed `scanId:ruleId`, because the unit of work is the rule. Local, and
  // only until the refetch lands: the server is what decides what is still
  // outstanding, and this set exists so a supervisor working down a list of
  // nine does not watch each row flicker back before it goes.
  const [settled, setSettled] = useState<Set<string>>(new Set());

  const resolve = useMutation({
    mutationFn: async ({
      scanId,
      ruleId,
      decision,
    }: {
      scanId: string;
      ruleId: string;
      decision: Decision;
    }) =>
      apiFetch(`/scans/${scanId}/review`, {
        method: "POST",
        body: { rule_id: ruleId, decision, note: "" },
      }),
    onSuccess: (_data, variables) => {
      setSettled((previous) => new Set(previous).add(`${variables.scanId}:${variables.ruleId}`));
      void client.invalidateQueries();
    },
  });

  if (rows.length === 0) {
    return (
      <Alert tone="pass" title="Nothing awaiting review">
        Every scan in this period was decided without a human call.
      </Alert>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col gap-2">
        {rows.map((row) => {
          const outstanding = row.rules.filter(
            (rule) => !settled.has(`${row.scan_id}:${rule}`),
          );
          const done = outstanding.length === 0;
          return (
            <li
              key={row.scan_id}
              className={`rounded-lg border border-border bg-surface p-3 ${done ? "opacity-60" : ""}`}
            >
              <div className="flex flex-wrap items-start gap-3">
                <Badge tone="review">REVIEW</Badge>
                <div className="min-w-0 flex-1">
                  <p className="font-medium">
                    <Link href={`/scan/${row.scan_id}`} className="underline">
                      {row.brand ?? "Unidentified brand"}
                    </Link>
                    {row.category ? <span className="text-fg-muted"> · {row.category}</span> : null}
                  </p>
                  <p className="text-sm text-fg-muted">
                    {dateTime(row.captured_at)}
                    {row.district ? ` · ${row.district}` : ""} · coverage {percent(row.coverage)} ·{" "}
                    {row.degradation_tier}
                  </p>
                </div>
                {/* Open is the primary and it is the only primary. A queue of
                    nine rows drew nine solid buttons whose job was to make the
                    row go away, and they were the loudest thing on the overview
                    — louder than the failure bars above them. The action this
                    screen asks for is to look at the scan; deciding without
                    opening it is the one thing it must not encourage. */}
                <Button asChild size="sm">
                  <Link href={`/scan/${row.scan_id}`}>Open</Link>
                </Button>
              </div>

              {done ? (
                <p className="mt-2 text-sm text-fg-muted">
                  Recorded. This scan leaves the queue on the next refresh.
                </p>
              ) : (
                <ul className="mt-2 flex flex-col gap-1.5 border-t border-border pt-2">
                  {outstanding.map((rule) => (
                    <li key={rule} className="flex flex-wrap items-center gap-2">
                      <span className="min-w-0 flex-1 text-sm">{ruleLabel(rule)}</span>
                      <div className="flex gap-1.5">
                        {CHOICES.map((choice) => (
                          <Button
                            key={choice.decision}
                            variant="outline"
                            size="sm"
                            title={choice.title}
                            disabled={resolve.isPending}
                            onClick={() =>
                              resolve.mutate({
                                scanId: row.scan_id,
                                ruleId: rule,
                                decision: choice.decision,
                              })
                            }
                          >
                            {choice.label}
                          </Button>
                        ))}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>

      {resolve.isError ? <Alert tone="fail">{(resolve.error as Error).message}</Alert> : null}

      <p className="text-sm text-fg-muted">
        A decision is stored beside the scan, never over it — the verdict still reads REVIEW
        afterwards, because the scan is hashed into the evidence chain. Each is also a labelled
        training example under section 14, recorded against your name and the time you made it.
      </p>
    </div>
  );
}
