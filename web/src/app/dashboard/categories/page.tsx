import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { tryServerFetch } from "@/lib/api/server";
import { parseFilters, filterQuery, filterSearch } from "@/lib/filters";
import { Table, THead, TR, TH, TD, Num, Empty } from "@/components/ui/table";
import { Pager } from "@/components/dashboard/pager";
import { ExportCsv } from "@/components/dashboard/export-csv";
import { Alert } from "@/components/ui/alert";
import { count, day, percent, ruleLabel } from "@/lib/format";
import type { CategoryRow, Table as Envelope } from "@/lib/api/types";

export const metadata: Metadata = { title: "Categories" };

const LIMIT = 50;

/**
 * Q4 — which product categories are worst?
 *
 * Section 11: *"This view makes a point as much as it informs. Competing tools
 * are food-first because they come from FSSAI. A category chart showing cement
 * and phone chargers alongside biscuits is proof we're implementing the right
 * law."*
 *
 * Which is why the empty state below names the commodities rather than saying
 * "no data": an empty categories table on a food-only corpus is itself the
 * finding.
 */
export default async function CategoriesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const filters = parseFilters(raw);
  const offset = Number(Array.isArray(raw.offset) ? raw.offset[0] : (raw.offset ?? 0)) || 0;
  const search = new URLSearchParams(filterSearch(filters).replace(/^\?/, ""));

  const table = await tryServerFetch<Envelope<CategoryRow>>("/dashboard/categories", {
    ...filterQuery(filters),
    limit: LIMIT,
    offset,
  });

  if (!table) return <Alert tone="review">This view is for supervisors and above.</Alert>;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Categories</h1>
          <p className="text-sm text-fg-muted">
            Q4 — the Legal Metrology rules cover every commodity, not only food.
          </p>
        </div>
        <Suspense fallback={null}>
          <ExportCsv path="/dashboard/categories" filename="categories.csv" />
        </Suspense>
      </div>

      <Table>
        <THead>
          <TR>
            <TH>Category</TH>
            <TH className="text-right">Scans</TH>
            <TH className="text-right">SKUs checked</TH>
            <TH className="text-right">Fail rate</TH>
            <TH className="text-right">High-sev</TH>
            <TH>Worst rule</TH>
            <TH>Last scanned</TH>
          </TR>
        </THead>
        <tbody>
          {table.rows.length === 0 ? (
            <Empty colSpan={7}>
              Nothing scanned. Cement, footwear, phone chargers and medical devices are all in
              scope — a corpus with only food in it is a gap in coverage, not a compliant market.
            </Empty>
          ) : (
            table.rows.map((row) => (
              <TR key={row.category}>
                <TD>
                  <Link
                    href={`/search${filterSearch(filters, { category: row.category })}`}
                    className="underline"
                  >
                    {row.category}
                  </Link>
                </TD>
                <Num>{count(row.scans)}</Num>
                <Num>{count(row.skus_checked)}</Num>
                <Num>{percent(row.fail_rate)}</Num>
                <Num>{count(row.high_severity)}</Num>
                <TD title={row.worst_rule ?? undefined}>
                  {row.worst_rule ? ruleLabel(row.worst_rule) : "—"}
                </TD>
                <TD>{day(row.last_scanned)}</TD>
              </TR>
            ))
          )}
        </tbody>
      </Table>

      <Pager
        path="/dashboard/categories"
        search={search}
        total={table.total}
        limit={table.limit}
        offset={table.offset}
      />
    </div>
  );
}
