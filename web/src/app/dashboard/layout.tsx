import { Suspense } from "react";
import { GlobalFilters } from "@/components/dashboard/global-filters";
import { DashboardTabs, type DashboardTab } from "@/components/dashboard/tabs";

/**
 * Section 11's information architecture: one filter bar above every view, and
 * five sibling entry points into the same scan data sliced differently.
 *
 * The filters are in the layout rather than in each page so they survive
 * navigation between the tabs without a remount — which is what "persist across
 * navigation" means in practice, and it is why moving from Brands to Rules keeps
 * the district you were looking at.
 */
const TABS: DashboardTab[] = [
  { href: "/dashboard", label: "Overview", question: "Q1, Q6, Q8" },
  { href: "/dashboard/brands", label: "Brands", question: "Q3, Q7" },
  { href: "/dashboard/rules", label: "Rules", question: "Q2" },
  { href: "/dashboard/categories", label: "Categories", question: "Q4" },
  { href: "/dashboard/districts", label: "Districts", question: "Q5" },
  { href: "/dashboard/health", label: "Health", question: "Q8" },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5">
      {/* Suspense because `DashboardTabs` reads the query string, and a
          component that calls `useSearchParams` opts its whole subtree out of
          static rendering unless it is inside one. */}
      <Suspense fallback={null}>
        <DashboardTabs tabs={TABS} />
      </Suspense>

      <Suspense fallback={null}>
        <GlobalFilters />
      </Suspense>

      {children}
    </div>
  );
}
