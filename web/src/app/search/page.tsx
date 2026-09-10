import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { tryServerFetch } from "@/lib/api/server";
import { parseFilters, filterQuery, filterSearch } from "@/lib/filters";
import { GlobalFilters } from "@/components/dashboard/global-filters";
import { Table, THead, TR, TH, TD, Num, Empty } from "@/components/ui/table";
import { Pager } from "@/components/dashboard/pager";
import { ExportCsv } from "@/components/dashboard/export-csv";
import { Badge, toneForStatus } from "@/components/ui/badge";
import { Alert } from "@/components/ui/alert";
import { dateTime, percent, ruleLabel } from "@/lib/format";
import type { SearchRow, Table as Envelope } from "@/lib/api/types";

export const metadata: Metadata = { title: "Search" };

const LIMIT = 50;

/**
 * Section 12: *"brand, barcode, date, district, rule, status."*
 *
 * `analytics` sorts this newest first, which is the opposite of the review
 * queue, and for the opposite reason: search answers *"what did I just scan"*
 * while the queue answers *"what has waited longest"*.
 *
 * Officer-and-above rather than supervisor-only, because an officer needs to
 * look up a pack they scanned this morning. The role split is enforced on the
 * API; this page merely reflects it.
 */
export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const filters = parseFilters(raw);
  const offset = Number(Array.isArray(raw.offset) ? raw.offset[0] : (raw.offset ?? 0)) || 0;
  const search = new URLSearchParams(filterSearch(filters).replace(/^\?/, ""));

  const table = await tryServerFetch<Envelope<SearchRow>>("/search", {
    ...filterQuery(filters),
    limit: LIMIT,
    offset,
  });

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Search</h1>
          <p className="text-sm text-fg-muted">
            Newest first. Every filter is in the address bar, so this page can be sent to a
            controller as a link.
          </p>
        </div>
        <Suspense fallback={null}>
          <ExportCsv path="/search" filename="scans.csv" />
        </Suspense>
      </div>

      <Suspense fallback={null}>
        <GlobalFilters />
      </Suspense>

      {!table ? (
        <Alert tone="review">Search is unavailable — the API could not be reached.</Alert>
      ) : (
        <>
          <Table>
            <THead>
              <TR>
                <TH>Status</TH>
                <TH>Captured</TH>
                <TH>Brand</TH>
                <TH>Category</TH>
                <TH>District</TH>
                <TH className="text-right">Coverage</TH>
                <TH>Tier</TH>
                <TH>Failed rules</TH>
              </TR>
            </THead>
            <tbody>
              {table.rows.length === 0 ? (
                <Empty colSpan={8}>Nothing matches these filters.</Empty>
              ) : (
                table.rows.map((row) => (
                  <TR key={row.scan_id}>
                    <TD>
                      <Badge tone={toneForStatus(row.status)}>{row.status.replace("_", " ")}</Badge>
                    </TD>
                    <TD>
                      <Link href={`/scan/${row.scan_id}`} className="underline">
                        {dateTime(row.captured_at)}
                      </Link>
                    </TD>
                    <TD>
                      {row.brand ? (
                        <Link
                          href={`/dashboard/brands/${encodeURIComponent(row.brand)}`}
                          className="underline"
                        >
                          {row.brand}
                        </Link>
                      ) : (
                        <span className="text-fg-muted">unidentified</span>
                      )}
                      {row.parent ? (
                        <span className="block text-sm text-fg-muted">{row.parent}</span>
                      ) : null}
                    </TD>
                    <TD>{row.category ?? "—"}</TD>
                    <TD>{row.district ?? "—"}</TD>
                    <Num>{percent(row.coverage)}</Num>
                    <TD>{row.degradation_tier}</TD>
                    <TD className="text-sm">
                      {row.failed_rules
                        ? row.failed_rules.split(";").map(ruleLabel).join(", ")
                        : "—"}
                    </TD>
                  </TR>
                ))
              )}
            </tbody>
          </Table>

          <Pager
            path="/search"
            search={search}
            total={table.total}
            limit={table.limit}
            offset={table.offset}
          />
        </>
      )}
    </div>
  );
}
