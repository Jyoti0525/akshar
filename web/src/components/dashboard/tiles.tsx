import Link from "next/link";
import { cn } from "@/lib/cn";
import {
  change,
  changeTone,
  count,
  percent,
  type Direction,
} from "@/lib/format";
import type { Overview } from "@/lib/api/types";

/**
 * Section 11: *"Five tiles across the top, each a number someone is accountable
 * for... Each shows the value, the change against the previous period, and
 * clicks through to the filtered list. A number you can't click is a number you
 * can't act on."*
 *
 * So every tile is a link, and each one carries the current filters plus the one
 * extra parameter that makes the destination show exactly the rows behind the
 * number. `High-severity open` goes to search filtered to failures at high
 * severity; it does not go to an unfiltered list where the reader has to
 * reconstruct what they just clicked.
 */
interface TileSpec {
  key: keyof Overview["tiles"];
  label: string;
  href: string;
  extra: Record<string, string>;
  direction: Direction;
  format: "count" | "percent";
}

const TILES: TileSpec[] = [
  {
    key: "scans",
    label: "Scans this period",
    href: "/search",
    extra: {},
    direction: "up-is-good",
    format: "count",
  },
  {
    key: "unique_skus",
    label: "Unique SKUs covered",
    href: "/products",
    extra: {},
    direction: "up-is-good",
    format: "count",
  },
  {
    key: "non_compliance_rate",
    label: "Non-compliance rate",
    href: "/search",
    extra: { status: "FAIL" },
    direction: "up-is-bad",
    format: "percent",
  },
  {
    key: "high_severity_open",
    label: "High-severity open",
    href: "/search",
    extra: { status: "FAIL", severity: "high" },
    direction: "up-is-bad",
    format: "count",
  },
  {
    key: "awaiting_review",
    label: "Awaiting review",
    href: "/queue",
    extra: { status: "REVIEW" },
    direction: "up-is-bad",
    format: "count",
  },
];

export function Tiles({
  overview,
  search,
}: {
  overview: Overview;
  search: string;
}) {
  // Said once, under the grid, rather than five times inside it. With no date
  // range set there is no previous period for any tile, so the per-tile version
  // printed the identical sentence in all five cards — a quarter of the panel
  // spent repeating one fact, which reads as noise and hides the numbers the
  // panel exists to show.
  const comparable = TILES.some((spec) => {
    const tile = overview.tiles[spec.key];
    return (
      (tile.change !== null && tile.change !== undefined) ||
      (tile.previous !== null && tile.previous !== undefined)
    );
  });

  return (
    <div className="flex flex-col gap-2">
      <ul className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {TILES.map((spec) => {
          const tile = overview.tiles[spec.key];
          const params = new URLSearchParams(search);
          for (const [key, value] of Object.entries(spec.extra))
            params.set(key, value);
          const tone = changeTone(tile.change ?? null, spec.direction);

          return (
            <li key={spec.key}>
              <Link
                href={`${spec.href}?${params.toString()}`}
                className="card block h-full rounded-lg border border-border bg-surface p-4 hover:bg-surface-2"
              >
                <p className="text-sm text-fg-muted">{spec.label}</p>
                <p className="mt-1 text-3xl font-semibold tabular-nums">
                  {spec.format === "percent"
                    ? percent(tile.value)
                    : count(tile.value)}
                </p>
                {tile.change !== null && tile.change !== undefined ? (
                  <p
                    className={cn(
                      "mt-1 text-sm tabular-nums",
                      tone === "bad"
                        ? "text-fail"
                        : tone === "good"
                          ? "text-pass"
                          : "text-fg-muted",
                    )}
                  >
                    {change(tile.change)} vs previous period
                  </p>
                ) : tile.previous !== null && tile.previous !== undefined ? (
                  <p className="mt-1 text-sm text-fg-muted tabular-nums">
                    was{" "}
                    {spec.format === "percent"
                      ? percent(tile.previous)
                      : count(tile.previous)}
                  </p>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
      {comparable ? null : (
        <p className="text-sm text-fg-muted">
          No comparison shown: set a date range above and each tile gains its
          change against the period immediately before it.
        </p>
      )}
    </div>
  );
}
