import type { Metadata } from "next";
import { Suspense } from "react";
import { tryServerFetch } from "@/lib/api/server";
import { parseFilters, filterQuery } from "@/lib/filters";
import { GlobalFilters } from "@/components/dashboard/global-filters";
import { Table, THead, TR, TH, TD, Num, Empty } from "@/components/ui/table";
import { Card, CardTitle, CardHint } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { SummaryExport } from "@/components/dashboard/summary-export";
import { count, dateTime, percent, ruleLabel } from "@/lib/format";
import type { SummaryView } from "@/lib/api/types";

export const metadata: Metadata = { title: "Violation summary" };

/**
 * Section 13a: *"The dashboard is the live view; the summary is its printable
 * form."*
 *
 * Every number on this page comes from `analytics.summary`, which is the same
 * function the PDF and DOCX renderings call. That is the whole design: the
 * screen and the report cannot disagree, because there is one computation and
 * three renderings of it — and a department given two different
 * non-compliance rates for one morning stops trusting both.
 *
 * The page also prints properly. `@media print` in `globals.css` drops the
 * navigation and the controls, so a supervisor without WeasyPrint installed
 * still has a usable document.
 */
export default async function SummaryPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const filters = parseFilters(await searchParams);
  const summary = await tryServerFetch<SummaryView>("/summary", filterQuery(filters));

  if (!summary) {
    return <Alert tone="review">The summary is for supervisors and above.</Alert>;
  }

  const applied = Object.entries(summary.filters);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Violation summary</h1>
          <p className="text-sm text-fg-muted">Generated {dateTime(summary.generated_at)}</p>
        </div>
        <Suspense fallback={null}>
          <SummaryExport />
        </Suspense>
      </div>

      <div className="no-print">
        <Suspense fallback={null}>
          <GlobalFilters />
        </Suspense>
      </div>

      <Card>
        <CardTitle>Scope</CardTitle>
        <CardHint>
          The filters this summary was produced under, printed with it. A figure quoted from a
          report whose scope is not on the page is a figure that will be misquoted.
        </CardHint>
        <p className="mt-2 text-base">
          {applied.length === 0
            ? "All scans, all districts, all categories, all time."
            : applied.map(([key, value]) => `${key.replace(/_/g, " ")}: ${value}`).join(" · ")}
        </p>
      </Card>

      <ul className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Scans" value={count(summary.scans)} />
        <Stat label="Unique SKUs" value={count(summary.unique_skus)} />
        <Stat label="Non-compliance rate" value={percent(summary.non_compliance_rate)} />
        <Stat label="High-severity failures" value={count(summary.high_severity)} />
        <Stat label="Conclusive" value={count(summary.conclusive)} />
        <Stat
          label="Inconclusive"
          value={count(summary.inconclusive)}
          hint="nothing readable enough to decide — not a pass"
        />
        <Stat label="Awaiting review" value={count(summary.awaiting_review)} />
        <Stat label="Mean coverage" value={percent(summary.mean_coverage)} />
      </ul>

      <Card>
        <CardTitle>Most-broken rules</CardTitle>
        <div className="mt-3">
          <Table>
            <THead>
              <TR>
                <TH>Rule</TH>
                <TH>Clause</TH>
                <TH className="text-right">Checked</TH>
                <TH className="text-right">Failed</TH>
                <TH className="text-right">Fail rate</TH>
              </TR>
            </THead>
            <tbody>
              {summary.top_violations.length === 0 ? (
                <Empty colSpan={5}>Nothing failed in this period.</Empty>
              ) : (
                summary.top_violations.map((rule) => (
                  <TR key={rule.rule_id}>
                    <TD title={rule.rule_id}>{ruleLabel(rule.rule_id)}</TD>
                    <TD className="text-sm text-fg-muted">{rule.rule_ref}</TD>
                    <Num>{count(rule.checked)}</Num>
                    <Num>{count(rule.failed)}</Num>
                    <Num>{percent(rule.fail_rate)}</Num>
                  </TR>
                ))
              )}
            </tbody>
          </Table>
        </div>
      </Card>

      <Card>
        <CardTitle>Repeat offenders</CardTitle>
        <CardHint>
          By high-severity count, because that is the list a case is opened from.
        </CardHint>
        <div className="mt-3">
          <Table>
            <THead>
              <TR>
                <TH>Brand</TH>
                <TH>Parent</TH>
                <TH className="text-right">SKUs</TH>
                <TH className="text-right">Fail rate</TH>
                <TH className="text-right">High-sev</TH>
                <TH>Trend</TH>
              </TR>
            </THead>
            <tbody>
              {summary.repeat_offenders.length === 0 ? (
                <Empty colSpan={6}>No brand failed in this period.</Empty>
              ) : (
                summary.repeat_offenders.map((brand) => (
                  <TR key={brand.brand}>
                    <TD>{brand.brand}</TD>
                    <TD className="text-fg-muted">{brand.parent ?? "—"}</TD>
                    <Num>{count(brand.skus_checked)}</Num>
                    <Num>{percent(brand.fail_rate)}</Num>
                    <Num>{count(brand.high_severity)}</Num>
                    <TD>{brand.trend ?? "not enough data"}</TD>
                  </TR>
                ))
              )}
            </tbody>
          </Table>
        </div>
      </Card>

      <Card>
        <CardTitle>By category</CardTitle>
        <div className="mt-3">
          <Table>
            <THead>
              <TR>
                <TH>Category</TH>
                <TH className="text-right">Scans</TH>
                <TH className="text-right">Fail rate</TH>
                <TH>Worst rule</TH>
              </TR>
            </THead>
            <tbody>
              {summary.categories.length === 0 ? (
                <Empty colSpan={4}>Nothing scanned.</Empty>
              ) : (
                summary.categories.map((row) => (
                  <TR key={row.category}>
                    <TD>{row.category}</TD>
                    <Num>{count(row.scans)}</Num>
                    <Num>{percent(row.fail_rate)}</Num>
                    <TD>{row.worst_rule ? ruleLabel(row.worst_rule) : "—"}</TD>
                  </TR>
                ))
              )}
            </tbody>
          </Table>
        </div>
      </Card>

      <Card>
        <CardTitle>By district</CardTitle>
        <div className="mt-3">
          <Table>
            <THead>
              <TR>
                <TH>District</TH>
                <TH className="text-right">Scans</TH>
                <TH className="text-right">Officers</TH>
                <TH className="text-right">Fail rate</TH>
                <TH className="text-right">Coverage</TH>
              </TR>
            </THead>
            <tbody>
              {summary.districts.length === 0 ? (
                <Empty colSpan={5}>Nothing scanned.</Empty>
              ) : (
                summary.districts.map((row) => (
                  <TR key={row.district}>
                    <TD>{row.district}</TD>
                    <Num>{count(row.scans)}</Num>
                    <Num>{count(row.active_officers)}</Num>
                    <Num>{percent(row.fail_rate)}</Num>
                    <Num>{row.coverage === null ? "no estimate" : percent(row.coverage)}</Num>
                  </TR>
                ))
              )}
            </tbody>
          </Table>
        </div>
      </Card>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <li className="card rounded-lg border border-border bg-surface p-4">
      <p className="text-sm text-fg-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {hint ? <p className="text-xs text-fg-muted">{hint}</p> : null}
    </li>
  );
}
