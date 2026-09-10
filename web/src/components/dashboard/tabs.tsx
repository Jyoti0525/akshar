"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { cn } from "@/lib/cn";

export type DashboardTab = { href: string; label: string; question: string };

/**
 * The six dashboard views, with the current one marked.
 *
 * Two things this fixes, and neither is decoration.
 *
 * **The current view was not indicated at all.** Six identical pills, one of
 * which you are already looking at. On a screen whose whole purpose is slicing
 * the same data six ways, "which slice am I in" is the single most useful piece
 * of state on the page.
 *
 * **The filters were being dropped.** `GlobalFilters` writes the district, the
 * category, the severity and the date range into the query string, and these
 * tabs linked to the bare path — so moving from Brands to Rules silently reset
 * every filter. The layout's own docstring promises the opposite ("moving from
 * Brands to Rules keeps the district you were looking at"), and it was true of
 * the filter component's state and false of the links beside it.
 */
export function DashboardTabs({ tabs }: { tabs: DashboardTab[] }) {
  const pathname = usePathname();
  const search = useSearchParams().toString();

  return (
    <nav aria-label="Dashboard views" className="no-print flex flex-wrap gap-1">
      {tabs.map((tab) => {
        // Exact match only. "/dashboard" is the prefix of all five others, so a
        // `startsWith` test would light Overview on every view.
        const active = pathname === tab.href;
        return (
          <Link
            key={tab.href}
            href={search ? `${tab.href}?${search}` : tab.href}
            title={`Answers ${tab.question}`}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex h-touch items-center rounded-md border px-4 text-base transition-colors",
              active
                ? "border-accent bg-accent text-accent-fg font-semibold"
                : "border-border hover:bg-surface-2 hover:border-accent/40",
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
