"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input, Label, Select } from "@/components/ui/field";
import { FILTER_KEYS, type FilterKey } from "@/lib/filters";

/**
 * Section 11: *"Four global filters sit above every view and persist across
 * navigation: date range, district, category, severity. Each is a URL parameter,
 * so any view can be shared as a link."*
 *
 * They are written into the URL and nowhere else. There is no filter context, no
 * store and no local state holding a copy — which is what makes the address bar
 * the single source of truth and a pasted link reproduce the screen exactly.
 *
 * The drill-down parameters (`brand`, `rule_id`, `status`) are shown as
 * removable chips rather than as controls. They are arrived at by clicking a
 * chart, so the thing an officer needs is a way back out, not another select.
 */
const DRILL_KEYS: FilterKey[] = ["brand", "rule_id", "status"];

export function GlobalFilters({
  districts = [],
  categories = [],
}: {
  districts?: string[];
  categories?: string[];
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const set = useCallback(
    (key: string, value: string) => {
      const next = new URLSearchParams(params.toString());
      if (value) next.set(key, value);
      else next.delete(key);
      // Paging is relative to a filter set; changing the filter and keeping
      // page 4 shows an empty table and looks like a bug.
      next.delete("offset");
      const qs = next.toString();
      router.push(qs ? `${pathname}?${qs}` : pathname);
    },
    [params, pathname, router],
  );

  const clear = useCallback(() => router.push(pathname), [pathname, router]);

  const value = (key: string) => params.get(key) ?? "";
  const active = FILTER_KEYS.filter((key) => params.get(key));

  return (
    <section
      aria-label="Filters"
      className="no-print flex flex-col gap-3 rounded-lg border border-border bg-surface p-3"
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="filter-from">From</Label>
          <Input
            id="filter-from"
            type="date"
            value={value("from")}
            onChange={(event) => set("from", event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="filter-to">To</Label>
          <Input
            id="filter-to"
            type="date"
            value={value("to")}
            onChange={(event) => set("to", event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="filter-district">District</Label>
          <Select
            id="filter-district"
            value={value("district")}
            onChange={(event) => set("district", event.target.value)}
          >
            <option value="">All districts</option>
            {districts.map((district) => (
              <option key={district} value={district}>
                {district}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="filter-category">Category</Label>
          <Select
            id="filter-category"
            value={value("category")}
            onChange={(event) => set("category", event.target.value)}
          >
            <option value="">All categories</option>
            {categories.map((category) => (
              <option key={category} value={category}>
                {category}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="filter-severity">Severity</Label>
          <Select
            id="filter-severity"
            value={value("severity")}
            onChange={(event) => set("severity", event.target.value)}
          >
            <option value="">Any severity</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </Select>
        </div>
      </div>

      {active.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          {active
            .filter((key) => DRILL_KEYS.includes(key))
            .map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => set(key, "")}
                className="inline-flex h-touch items-center gap-2 rounded-full border border-border px-3 text-sm hover:bg-surface-2"
              >
                {key.replace("_", " ")}: {params.get(key)}
                <span aria-hidden="true">✕</span>
                <span className="sr-only">Remove this filter</span>
              </button>
            ))}
          <Button variant="ghost" size="sm" onClick={clear}>
            Clear all filters
          </Button>
        </div>
      ) : null}
    </section>
  );
}
