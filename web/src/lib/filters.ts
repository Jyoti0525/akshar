/**
 * The four global filters, as URL parameters.
 *
 * Section 11: *"Four global filters sit above every view and persist across
 * navigation: date range, district, category, severity. Each is a URL parameter,
 * so any view can be shared as a link — which matters more than it sounds,
 * because that's how a finding gets escalated to a controller."*
 *
 * The names here are exactly the names `api/routers/dashboard.filters_from_query`
 * accepts, so a link an officer pastes into an email produces the same numbers
 * on the server as it did on their screen. That equality is the whole point, and
 * it is why the filters are never renamed on the way through.
 */
import type { GlobalFilters, Severity } from "./api/types";

export const FILTER_KEYS = [
  "from",
  "to",
  "district",
  "category",
  "severity",
  "brand",
  "rule_id",
  "status",
] as const;

export type FilterKey = (typeof FILTER_KEYS)[number];

/** The four that section 11 calls global; the rest are drill-downs added by
 *  clicking a chart, and are cleared by the "clear" control separately. */
export const GLOBAL_KEYS: FilterKey[] = ["from", "to", "district", "category", "severity"];

const SEVERITIES: Severity[] = ["low", "medium", "high"];
const STATUSES = ["PASS", "FAIL", "REVIEW"] as const;

type RawParams = Record<string, string | string[] | undefined>;

/** Parse a Next `searchParams` object into filters, dropping anything that is
 *  not a value the API would accept. A pasted link with `severity=urgent` should
 *  render the unfiltered view, not a 422. */
export function parseFilters(params: RawParams): GlobalFilters {
  const one = (key: string): string | undefined => {
    const value = params[key];
    const text = Array.isArray(value) ? value[0] : value;
    return text && text.length > 0 ? text : undefined;
  };

  const severity = one("severity");
  const status = one("status");

  return {
    from: isoDate(one("from")),
    to: isoDate(one("to")),
    district: one("district"),
    category: one("category"),
    severity: SEVERITIES.includes(severity as Severity) ? (severity as Severity) : undefined,
    brand: one("brand"),
    rule_id: one("rule_id"),
    status: (STATUSES as readonly string[]).includes(status ?? "")
      ? (status as GlobalFilters["status"])
      : undefined,
  };
}

function isoDate(value: string | undefined): string | undefined {
  if (!value) return undefined;
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : undefined;
}

/** Filters as a query object for the API client — undefined keys are dropped by
 *  `withQuery`, so an unset filter never becomes `?district=undefined`. */
export function filterQuery(filters: GlobalFilters): Record<string, string | undefined> {
  return { ...filters };
}

/** Filters as a query string for a link. Stable key order, so two links to the
 *  same view are the same string and browser history does not fill with
 *  near-duplicates. */
export function filterSearch(filters: GlobalFilters, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    const value = filters[key];
    if (value) params.set(key, String(value));
  }
  for (const [key, value] of Object.entries(extra)) {
    if (value) params.set(key, value);
    else params.delete(key);
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

/** A link that keeps the filters and goes somewhere else — how every drill-down
 *  in section 11's diagram is built. */
export function drill(path: string, filters: GlobalFilters, extra: Record<string, string> = {}) {
  return `${path}${filterSearch(filters, extra)}`;
}

export function activeCount(filters: GlobalFilters): number {
  return FILTER_KEYS.filter((key) => Boolean(filters[key])).length;
}

/** The default window: the last 30 days, expressed as real dates rather than
 *  left blank. A blank range means "all time", which has no previous period, so
 *  every tile would show a null change on first load and the dashboard would
 *  look broken on the morning it is demonstrated. */
export function defaultRange(today = new Date()): { from: string; to: string } {
  const end = new Date(today);
  const start = new Date(today);
  start.setDate(start.getDate() - 29);
  return { from: start.toISOString().slice(0, 10), to: end.toISOString().slice(0, 10) };
}
