import type { Metadata } from "next";
import Link from "next/link";
import { tryServerFetch } from "@/lib/api/server";
import { Card, CardTitle, CardHint } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { count, millimetres } from "@/lib/format";
import type { SkuCacheResponse, SkuSummary } from "@/lib/api/types";

export const metadata: Metadata = { title: "Product" };

/**
 * One SKU, and its history.
 *
 * **The API has no route for a single SKU by id.** `GET /skus/lookup` takes a
 * barcode or a pHash, not an id, and there is no repository endpoint. So this
 * page finds the SKU inside the same warming list the index uses, which is
 * correct but capped — a SKU outside the warmed window will not be found here,
 * and the page says so rather than showing "not found" as though the SKU did not
 * exist. Closing that is one endpoint, not a redesign.
 *
 * The scan history links out to search by brand for the same reason: the search
 * filters (`api/routers/dashboard.filters_from_query`) do not include a SKU id.
 */
const WINDOW = 5000;

export default async function ProductPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await tryServerFetch<SkuCacheResponse>("/skus/cache", { n: WINDOW });
  const sku: SkuSummary | undefined = response?.skus.find((row) => String(row.id) === id);

  if (!sku) {
    return (
      <Alert tone="review" title="Not in the warmed window">
        This SKU is not among the {count(WINDOW)} most-scanned, which is as far as the available
        endpoint reaches. It may still exist. Search by brand instead.
      </Alert>
    );
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-5">
      <div>
        <Link href="/products" className="text-sm underline">
          ← All products
        </Link>
        <h1 className="mt-1 text-2xl font-semibold">{sku.brand}</h1>
        <p className="text-base text-fg-muted">
          {[sku.variant, sku.pack_size, sku.category].filter(Boolean).join(" · ")}
        </p>
      </div>

      <Card>
        <CardTitle>Identity</CardTitle>
        <CardHint>
          Section 12: a readable EAN-13 makes identification a single indexed lookup — faster and
          more reliable than image matching, and the fastest path to a cache hit we have.
        </CardHint>
        <dl className="mt-3 grid gap-2 sm:grid-cols-2">
          <Row label="Parent company" value={sku.brand_group ?? "—"} />
          <Row label="Barcode" value={sku.barcode ?? "none read"} mono />
          <Row label="Perceptual hash" value={sku.phash ?? "—"} mono />
          <Row label="Times scanned" value={count(sku.scan_count)} />
          <Row
            label="Label size"
            value={
              sku.label_w_mm && sku.label_h_mm
                ? `${millimetres(sku.label_w_mm)} × ${millimetres(sku.label_h_mm)}`
                : "not measured"
            }
          />
        </dl>
      </Card>

      <div className="flex flex-wrap gap-2">
        <Button asChild variant="outline">
          <Link href={`/search?brand=${encodeURIComponent(sku.brand)}`}>
            Every scan of this brand
          </Link>
        </Button>
        <Button asChild variant="outline">
          <Link href={`/dashboard/brands/${encodeURIComponent(sku.brand)}`}>Brand detail</Link>
        </Button>
      </div>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5 border-b border-border pb-2 last:border-0">
      <dt className="text-sm text-fg-muted">{label}</dt>
      <dd className={mono ? "break-all font-mono text-sm" : "font-medium"}>{value}</dd>
    </div>
  );
}
