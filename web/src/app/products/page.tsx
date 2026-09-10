import type { Metadata } from "next";
import Link from "next/link";
import { tryServerFetch } from "@/lib/api/server";
import { parseFilters } from "@/lib/filters";
import { Table, THead, TR, TH, TD, Num, Empty } from "@/components/ui/table";
import { Alert } from "@/components/ui/alert";
import { count } from "@/lib/format";
import type { SkuCacheResponse } from "@/lib/api/types";

export const metadata: Metadata = { title: "Products" };

/**
 * The SKU repository. Section 3, fourth principle: *"Never pay twice for the
 * same label. A violation is printed at design time, so it's identical on every
 * packet of that SKU across the country."* This is the list of labels already
 * settled.
 *
 * It is served by `GET /skus/cache`, which exists for offline cache warming and
 * happens to be the only endpoint that enumerates SKUs. Two consequences are
 * stated rather than hidden: the list is capped at the warming size, and it is
 * ordered by scan count — most-scanned first — not alphabetically. A dedicated
 * paginated repository endpoint is a small API addition and is not here yet.
 */
const PAGE = 200;

export default async function ProductsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const filters = parseFilters(await searchParams);
  const response = await tryServerFetch<SkuCacheResponse>("/skus/cache", {
    district: filters.district ?? null,
    n: PAGE,
  });

  if (!response) {
    return <Alert tone="review">The SKU repository could not be reached.</Alert>;
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Products</h1>
        <p className="text-sm text-fg-muted">
          {count(response.count)} SKUs already settled
          {response.district ? ` in ${response.district}` : ""} — most-scanned first. A repeat SKU
          returns in about 60 ms because no model runs.
        </p>
      </div>

      <Table>
        <THead>
          <TR>
            <TH>Brand</TH>
            <TH>Parent</TH>
            <TH>Variant</TH>
            <TH>Pack size</TH>
            <TH>Category</TH>
            <TH>Barcode</TH>
            <TH className="text-right">Scans</TH>
          </TR>
        </THead>
        <tbody>
          {response.skus.length === 0 ? (
            <Empty colSpan={7}>No SKU has been settled yet.</Empty>
          ) : (
            response.skus.map((sku) => (
              <TR key={String(sku.id)}>
                <TD>
                  <Link href={`/products/${String(sku.id)}`} className="underline">
                    {sku.brand}
                  </Link>
                </TD>
                <TD className="text-fg-muted">{sku.brand_group ?? "—"}</TD>
                <TD>{sku.variant ?? "—"}</TD>
                <TD>{sku.pack_size}</TD>
                <TD>{sku.category}</TD>
                <TD className="font-mono text-sm">{sku.barcode ?? "—"}</TD>
                <Num>{count(sku.scan_count)}</Num>
              </TR>
            ))
          )}
        </tbody>
      </Table>
    </div>
  );
}
