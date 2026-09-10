import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { tryServerFetch } from "@/lib/api/server";
import { parseFilters, filterQuery, filterSearch } from "@/lib/filters";
import { Table, THead, TR, TH, TD, Num, Empty } from "@/components/ui/table";
import { Pager } from "@/components/dashboard/pager";
import { ExportCsv } from "@/components/dashboard/export-csv";
import { Alert } from "@/components/ui/alert";
import { count, percent } from "@/lib/format";
import type { DistrictRow, Table as Envelope } from "@/lib/api/types";

export const metadata: Metadata = { title: "Districts" };

const LIMIT = 50;

/**
 * Q5 — which districts are actually being covered, and which are dark?
 *
 * Section 11: *"coverage against an estimated SKU population — that last column
 * identifies districts that are dark rather than compliant. A choropleth map is
 * optional and should be the first thing cut; the table carries all the
 * information."* The map is cut.
 *
 * Coverage is null unless someone supplies a population estimate, and it renders
 * as "no estimate" rather than 0%. `analytics.by_district` puts it bluntly: a
 * coverage figure computed against an unknown denominator is a guess wearing a
 * percentage sign — and this is the one column on the dashboard whose whole
 * purpose is to distinguish "we did not look" from "we looked and it was fine".
 */
export default async function DistrictsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const filters = parseFilters(raw);
  const offset = Number(Array.isArray(raw.offset) ? raw.offset[0] : (raw.offset ?? 0)) || 0;
  const search = new URLSearchParams(filterSearch(filters).replace(/^\?/, ""));

  const table = await tryServerFetch<Envelope<DistrictRow>>("/dashboard/districts", {
    ...filterQuery(filters),
    limit: LIMIT,
    offset,
  });

  if (!table) return <Alert tone="review">This view is for supervisors and above.</Alert>;

  const unestimated = table.rows.filter((row) => row.coverage === null).length;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Districts</h1>
          <p className="text-sm text-fg-muted">
            Q5 — which districts are covered, and which are dark rather than compliant.
          </p>
        </div>
        <Suspense fallback={null}>
          <ExportCsv path="/dashboard/districts" filename="districts.csv" />
        </Suspense>
      </div>

      {unestimated > 0 ? (
        <Alert tone="neutral">
          {unestimated === table.rows.length ? "No district has" : `${unestimated} districts have`}{" "}
          an SKU population estimate, so coverage cannot be computed for them. A district with no
          scans and no denominator is unmeasured, not clean.
        </Alert>
      ) : null}

      <Table>
        <THead>
          <TR>
            <TH>District</TH>
            <TH className="text-right">Scans</TH>
            <TH className="text-right">Unique SKUs</TH>
            <TH className="text-right">Active officers</TH>
            <TH className="text-right">Fail rate</TH>
            <TH className="text-right">Coverage</TH>
          </TR>
        </THead>
        <tbody>
          {table.rows.length === 0 ? (
            <Empty colSpan={6}>No scans in this period.</Empty>
          ) : (
            table.rows.map((row) => (
              <TR key={row.district}>
                <TD>
                  <Link
                    href={`/search${filterSearch(filters, { district: row.district })}`}
                    className="underline"
                  >
                    {row.district}
                  </Link>
                </TD>
                <Num>{count(row.scans)}</Num>
                <Num>{count(row.skus_checked)}</Num>
                <Num>{count(row.active_officers)}</Num>
                <Num>{percent(row.fail_rate)}</Num>
                <Num title={row.sku_population_estimate ? `of an estimated ${row.sku_population_estimate}` : undefined}>
                  {row.coverage === null ? (
                    <span className="text-fg-muted">no estimate</span>
                  ) : (
                    percent(row.coverage)
                  )}
                </Num>
              </TR>
            ))
          )}
        </tbody>
      </Table>

      <Pager
        path="/dashboard/districts"
        search={search}
        total={table.total}
        limit={table.limit}
        offset={table.offset}
      />
    </div>
  );
}
