import type { Metadata } from "next";
import { tryServerFetch } from "@/lib/api/server";
import { parseFilters, filterQuery, filterSearch } from "@/lib/filters";
import { Tiles } from "@/components/dashboard/tiles";
import { ReviewQueue } from "@/components/dashboard/review-queue";
import { TrendChart } from "@/components/charts/trend";
import { RuleBars } from "@/components/charts/rule-bars";
import { Alert } from "@/components/ui/alert";
import { CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import type { Overview } from "@/lib/api/types";

export const metadata: Metadata = { title: "Overview" };

/**
 * Section 11's overview: five tiles, then *"three things and nothing more"* —
 * the trend, the violations-by-rule bars, and the review queue.
 *
 * A Server Component, as section 11 asks. The review queue is the exception it
 * names, and it is the only client component on this page.
 */
export default async function OverviewPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const filters = parseFilters(await searchParams);
  const search = filterSearch(filters).replace(/^\?/, "");
  const overview = await tryServerFetch<Overview>("/dashboard/overview", filterQuery(filters));

  if (!overview) {
    return (
      <Alert tone="review" title="The dashboard could not be loaded">
        Either this account is not a supervisor, or the API is unreachable. Scanning still works
        offline; the dashboard does not.
      </Alert>
    );
  }

  // A dashboard drawn over nothing is five zeroes, two empty chart frames and a
  // blank queue, and the first person to see that screen is whoever has just
  // deployed it. Whether that is a fresh instance or an over-tight filter is
  // the difference between "scan something" and "widen the range", so the two
  // are told apart rather than sharing one vague sentence.
  if (overview.tiles.scans.value === 0) {
    const filtered = search.length > 0;
    return (
      <EmptyState
        title={filtered ? "No scans match these filters" : "Nothing has been scanned yet"}
        action={
          filtered ? (
            <Button asChild variant="outline">
              <Link href="/dashboard">Clear the filters</Link>
            </Button>
          ) : (
            <Button asChild>
              <Link href="/scan">Scan a package</Link>
            </Button>
          )
        }
      >
        {filtered
          ? "Widen the date range, or clear the district and category above. The scans are still there — this view is just looking at a slice with none in it."
          : "Every number on this page is computed from scan records, so it stays empty until the first package is photographed. The rulepack, the reports and the offline queue are all working in the meantime."}
      </EmptyState>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <Tiles overview={overview} search={search} />

      <div className="grid gap-5 xl:grid-cols-2">
        <TrendChart points={overview.trend} />
        <RuleBars rules={overview.violations_by_rule} search={search} />
      </div>

      <section className="flex flex-col gap-3">
        <div>
          <CardTitle>Review queue</CardTitle>
          <p className="text-sm text-fg-muted">
            Q6 — what needs a human decision right now? Oldest first.
          </p>
        </div>
        <ReviewQueue rows={overview.review_queue} />
      </section>
    </div>
  );
}
