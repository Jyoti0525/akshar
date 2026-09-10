import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { tryServerFetch } from "@/lib/api/server";
import { parseFilters, filterQuery, filterSearch } from "@/lib/filters";
import { Table, THead, TR, TH, TD, Num, Empty } from "@/components/ui/table";
import { Pager } from "@/components/dashboard/pager";
import { ExportCsv } from "@/components/dashboard/export-csv";
import { Alert } from "@/components/ui/alert";
import { count, percent, ruleLabel } from "@/lib/format";
import type { RuleRow, Table as Envelope } from "@/lib/api/types";

export const metadata: Metadata = { title: "Rules" };

const LIMIT = 50;

/**
 * Q2 — which rule is broken most often? And section 11's second, quieter
 * purpose: *"it audits our own rules. A rule failing on 95% of products is more
 * likely a bug in our regex than a national conspiracy."*
 *
 * That audit is the reason `checked` sits beside `failed`. A failure count on
 * its own cannot distinguish a rule that fires constantly from one that is
 * merely evaluated constantly, and the whole point of the view is telling those
 * two apart before the department publishes an advisory about the wrong thing.
 */
export default async function RulesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const filters = parseFilters(raw);
  const offset = Number(Array.isArray(raw.offset) ? raw.offset[0] : (raw.offset ?? 0)) || 0;
  const search = new URLSearchParams(filterSearch(filters).replace(/^\?/, ""));

  const table = await tryServerFetch<Envelope<RuleRow>>("/dashboard/rules", {
    ...filterQuery(filters),
    limit: LIMIT,
    offset,
  });

  if (!table) return <Alert tone="review">This view is for supervisors and above.</Alert>;

  const suspect = table.rows.filter((row) => row.suspect);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Rules</h1>
          <p className="text-sm text-fg-muted">
            Q2 — what to publicise, and whether our own regex is the reason.
          </p>
        </div>
        <Suspense fallback={null}>
          <ExportCsv path="/dashboard/rules" filename="rules.csv" />
        </Suspense>
      </div>

      {suspect.length > 0 ? (
        <Alert tone="review" title="Check these rules before citing them">
          {suspect.map((row) => ruleLabel(row.rule_id)).join(", ")} fail on over 95% of the packs
          they are evaluated against. On a national corpus that is far more likely to be our
          pattern than the market.
        </Alert>
      ) : null}

      <Table>
        <THead>
          <TR>
            <TH>Rule</TH>
            <TH>Clause</TH>
            <TH>Severity</TH>
            <TH className="text-right">Checked</TH>
            <TH className="text-right">Failed</TH>
            <TH className="text-right">Fail rate</TH>
            <TH>Brands failing it most</TH>
          </TR>
        </THead>
        <tbody>
          {table.rows.length === 0 ? (
            <Empty colSpan={7}>No rule failed in this period.</Empty>
          ) : (
            table.rows.map((row) => (
              <TR key={row.rule_id} className={row.suspect ? "bg-review-bg" : undefined}>
                <TD>
                  <Link href={`/rules#${row.rule_id}`} className="underline" title={row.rule_id}>
                    {ruleLabel(row.rule_id)}
                  </Link>
                </TD>
                <TD className="text-sm text-fg-muted">{row.rule_ref}</TD>
                <TD>{row.severity}</TD>
                <Num>{count(row.checked)}</Num>
                <Num>{count(row.failed)}</Num>
                <Num>{percent(row.fail_rate)}</Num>
                <TD className="text-sm">
                  {row.top_brands.length === 0
                    ? "—"
                    : row.top_brands.map((entry) => (
                        <Link
                          key={entry.brand}
                          href={`/dashboard/brands/${encodeURIComponent(entry.brand)}${filterSearch(filters)}`}
                          className="mr-2 underline"
                        >
                          {entry.brand} ({entry.failures})
                        </Link>
                      ))}
                </TD>
              </TR>
            ))
          )}
        </tbody>
      </Table>

      <Pager
        path="/dashboard/rules"
        search={search}
        total={table.total}
        limit={table.limit}
        offset={table.offset}
      />
    </div>
  );
}
