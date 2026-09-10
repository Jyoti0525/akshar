import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { tryServerFetch } from "@/lib/api/server";
import { parseFilters, filterQuery, filterSearch } from "@/lib/filters";
import { Table, THead, TR, TH, TD, Num, Empty } from "@/components/ui/table";
import { Pager } from "@/components/dashboard/pager";
import { ExportCsv } from "@/components/dashboard/export-csv";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { count, day, percent, ruleLabel } from "@/lib/format";
import type { BrandRow, Table as Envelope } from "@/lib/api/types";

export const metadata: Metadata = { title: "Brands" };

const LIMIT = 50;

/**
 * Q3 — which brands are repeat offenders?
 *
 * Section 11: *"Sortable on any column, but it defaults to high-severity count,
 * not fail rate."* The default order comes from `analytics.by_brand`, which is
 * where the reasoning lives, so the screen, the CSV and the PDF are ordered
 * identically and nobody has to ask which list they are looking at.
 */
export default async function BrandsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const filters = parseFilters(raw);
  const offset = Number(Array.isArray(raw.offset) ? raw.offset[0] : (raw.offset ?? 0)) || 0;
  const search = new URLSearchParams(filterSearch(filters).replace(/^\?/, ""));

  const table = await tryServerFetch<Envelope<BrandRow>>("/dashboard/brands", {
    ...filterQuery(filters),
    limit: LIMIT,
    offset,
  });

  if (!table) {
    return <Alert tone="review">This view is for supervisors and above.</Alert>;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Brands</h1>
          <p className="text-sm text-fg-muted">
            Q3 — sorted by high-severity count, because a two-SKU brand at 100% is noise and a
            national brand at 30% across forty SKUs is a case worth opening.
          </p>
        </div>
        <Suspense fallback={null}>
          <ExportCsv path="/dashboard/brands" filename="brands.csv" />
        </Suspense>
      </div>

      <Table>
        <THead>
          <TR>
            <TH>Brand</TH>
            <TH>Parent</TH>
            <TH className="text-right">SKUs checked</TH>
            <TH className="text-right">Fail rate</TH>
            <TH className="text-right">High-sev</TH>
            <TH>Worst rule</TH>
            <TH>Trend</TH>
            <TH>Last scanned</TH>
          </TR>
        </THead>
        <tbody>
          {table.rows.length === 0 ? (
            <Empty colSpan={8}>No brand was scanned in this period.</Empty>
          ) : (
            table.rows.map((row) => (
              <TR key={row.brand}>
                <TD>
                  <Link
                    href={`/dashboard/brands/${encodeURIComponent(row.brand)}${filterSearch(filters)}`}
                    className="underline"
                  >
                    {row.brand}
                  </Link>
                </TD>
                <TD className="text-fg-muted">{row.parent ?? "—"}</TD>
                <Num>{count(row.skus_checked)}</Num>
                <Num>{percent(row.fail_rate)}</Num>
                <Num>{count(row.high_severity)}</Num>
                <TD title={row.worst_rule ?? undefined}>
                  {row.worst_rule ? ruleLabel(row.worst_rule) : "—"}
                </TD>
                <TD>
                  <TrendCell trend={row.trend} />
                </TD>
                <TD>{day(row.last_scanned)}</TD>
              </TR>
            ))
          )}
        </tbody>
      </Table>

      <Pager
        path="/dashboard/brands"
        search={search}
        total={table.total}
        limit={table.limit}
        offset={table.offset}
      />
    </div>
  );
}

/** Null is its own answer: fewer than six scans, or a period that cannot be
 *  split. Section 11's Trend column must not imply a direction we do not have. */
function TrendCell({ trend }: { trend: BrandRow["trend"] }) {
  if (trend === null) {
    return (
      <span className="text-sm text-fg-muted" title="Fewer than six scans — not enough to say.">
        not enough data
      </span>
    );
  }
  if (trend === "improving") return <Badge tone="pass">improving</Badge>;
  if (trend === "worsening") return <Badge tone="fail">worsening</Badge>;
  return <Badge tone="neutral">flat</Badge>;
}
