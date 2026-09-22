/**
 * Types for everything crossing the wire.
 *
 * AKSHAR.md section 15b: *"types generated from the FastAPI OpenAPI schema via
 * `openapi-typescript`, so frontend types cannot drift from `contracts/`."*
 * `schema.gen.ts` is that generated file and is never edited by hand; the
 * aliases below just give its members readable names.
 *
 * The dashboard routes are the exception, and honestly so. They return
 * `dict[str, Any]` — deliberately, because `api/analytics.py` owns those shapes
 * and pinning them into Pydantic models would mean editing two files to add a
 * column. So they are declared here by hand, and each names the function in
 * `api/analytics.py` it must match. If that function changes, this file has to
 * change with it; nothing will tell us automatically.
 */
import type { components } from "./schema.gen";

type S = components["schemas"];

export type Box = S["Box"];
export type Declaration = S["Declaration"];
export type DeclarationSet = S["DeclarationSet"];
export type LabelGeometry = S["LabelGeometry"];
export type Verdict = S["Verdict"];
export type ScanResponse = S["ScanResponse"];
export type EvidenceInfo = S["EvidenceInfo"];
export type BulkAccepted = S["BulkAccepted"];
export type BulkJobStatus = S["BulkJobStatus"];
export type CurrentUser = S["CurrentUser"];
export type TokenPair = S["TokenPair"];
export type SkuSummary = S["SkuSummary"];
export type SkuLookupResponse = S["SkuLookupResponse"];
export type SkuCacheResponse = S["SkuCacheResponse"];
export type SyncItem = S["SyncItem"];
export type SyncRequest = S["SyncRequest"];
export type SyncResponse = S["SyncResponse"];
export type HealthResponse = S["HealthResponse"];
export type ChainStatusResponse = S["ChainStatusResponse"];
export type CorrectionRequest = S["CorrectionRequest"];
export type GeoPoint = S["GeoPoint"];
/** B1's measurement of the photograph. `contracts/quality.py`. */
export type CaptureQuality = S["CaptureQuality"];
/** Whether the declaration panel was in the photograph at all. `contracts/quality.py`. */
export type Framing = S["Framing"];
/** One photograph of a multi-frame scan, and what it contributed. `api/schemas.py`. */
export type FrameInfo = S["FrameInfo"];

export type Role = CurrentUser["role"];
export type VerdictStatus = Verdict["status"];
export type Severity = "low" | "medium" | "high";
export type DegradationTier = ScanResponse["degradation_tier"];

/** Section 11's four global filters, plus the drill-down parameters the
 *  dashboard adds when you click through a chart. All are URL parameters. */
export interface GlobalFilters {
  from?: string;
  to?: string;
  district?: string;
  category?: string;
  severity?: Severity;
  brand?: string;
  rule_id?: string;
  status?: "PASS" | "FAIL" | "REVIEW";
}

/** `dashboard._table` — every paginated view returns this envelope. */
export interface Table<Row> {
  total: number;
  limit: number;
  offset: number;
  rows: Row[];
}

/** `analytics._Bucket.as_row` — the columns shared by brands, categories and
 *  districts, so the three tables can use one renderer. */
export interface BucketRow {
  scans: number;
  skus_checked: number;
  fail_rate: number | null;
  high_severity: number;
  awaiting_review: number;
  worst_rule: string | null;
  last_scanned: string | null;
}

export interface Tile {
  value: number | null;
  previous?: number | null;
  change?: number | null;
}

/** `analytics.weekly_trend` — a null `rate` is a week with no scans, drawn as a
 *  gap rather than interpolated. */
export interface TrendPoint {
  week: string;
  scans: number;
  /** Numerator and denominator of the rate below. `conclusive` excludes scans
   *  whose every verdict was NO_DATA — see `analytics.weekly_trend`. */
  non_compliant: number;
  conclusive: number;
  /** Named exactly as `analytics.weekly_trend` emits it. It was `rate` here for
   *  a while, which is why the chart drew an empty grid: `point.rate` was
   *  `undefined` on every point and Recharts rendered axes with no line. A
   *  hand-declared type that disagrees with the payload fails silently and
   *  looks like "no data". */
  non_compliance_rate: number | null;
}

/** `analytics.by_rule` */
export interface RuleRow {
  rule_id: string;
  rule_ref: string;
  severity: Severity;
  checked: number;
  failed: number;
  fail_rate: number | null;
  /** Set when a rule fails on >95% of at least 20 evaluations. Section 11:
   *  *"more likely a bug in our regex than a national conspiracy."* */
  suspect: boolean;
  top_brands: { brand: string; failures: number }[];
}

/** `analytics.review_queue` */
export interface ReviewRow {
  scan_id: string;
  captured_at: string;
  brand: string | null;
  /** SKU variant and pack size. Null together with `brand` when no SKU was
   *  matched — see `productName` in `lib/format.ts` for how that is rendered. */
  variant: string | null;
  pack_size: string | null;
  district: string | null;
  category: string | null;
  coverage: number | null;
  degradation_tier: string;
  rules: string[];
}

/** `analytics.overview` */
export interface Overview {
  tiles: {
    scans: Tile;
    unique_skus: Tile;
    non_compliance_rate: Tile;
    high_severity_open: Tile;
    awaiting_review: Tile;
  };
  trend: TrendPoint[];
  violations_by_rule: RuleRow[];
  review_queue: ReviewRow[];
}

/** `analytics.by_brand`. `trend` is null when there were fewer than six scans
 *  or the period could not be split — section 11's Trend column, and null means
 *  "not enough to say" rather than "flat". */
export type Trend = "improving" | "worsening" | "flat" | null;

export interface BrandRow extends BucketRow {
  brand: string;
  parent: string | null;
  trend: Trend;
}

/** `analytics.brand_detail` — Q7, "is this brand improving after notice?" */
export interface BrandDetail extends BucketRow {
  brand: string;
  parent: string | null;
  trend: Trend;
  rules: RuleRow[];
  timeline: {
    scan_id: string;
    captured_at: string;
    sku_id: string | null;
    district: string | null;
    non_compliant: boolean;
    failed_rules: string[];
  }[];
}

/** `analytics.by_category` */
export interface CategoryRow extends BucketRow {
  category: string;
}

/** `analytics.by_district` — `coverage` is null unless an SKU population
 *  estimate was supplied, because a coverage figure with an unknown denominator
 *  is a guess wearing a percentage sign. */
export interface DistrictRow extends BucketRow {
  district: string;
  active_officers: number;
  coverage: number | null;
  sku_population_estimate: number | null;
}

/** `analytics.health` — Q8 */
export interface HealthView {
  scans: number;
  median_latency_ms_cache_hit: number | null;
  median_latency_ms_cache_miss: number | null;
  p95_latency_ms_cache_miss: number | null;
  cache_hit_rate: number | null;
  mean_coverage: number | null;
  awaiting_sync: number;
  degradation_tiers: Record<string, number>;
}

/** `dashboard.search` */
export interface SearchRow {
  scan_id: string;
  captured_at: string;
  brand: string | null;
  parent: string | null;
  category: string | null;
  district: string | null;
  source: string;
  degradation_tier: string;
  coverage: number | null;
  status: "PASS" | "FAIL" | "REVIEW" | "NO_DATA";
  high_severity: number;
  failed_rules: string;
}

/** `analytics.summary` — the dashboard's printable form. Section 13a: the PDF
 *  and DOCX renderings take this exact structure, so a number in the report and
 *  the same number on screen come from one computation. */
export interface SummaryView {
  generated_at: string;
  filters: Record<string, string>;
  scans: number;
  conclusive: number;
  inconclusive: number;
  non_compliant: number;
  non_compliance_rate: number | null;
  unique_skus: number;
  high_severity: number;
  awaiting_review: number;
  mean_coverage: number | null;
  top_violations: RuleRow[];
  repeat_offenders: BrandRow[];
  categories: CategoryRow[];
  districts: DistrictRow[];
}

/** `GET /api/v1/rules` — the active rulepack, readable, and deliberately
 *  unauthenticated: section 5 calls the whole legal logic "40 KB of text, small
 *  enough to email", and the argument for rules-as-data is weakened by hiding
 *  them. */
export interface RuleDoc {
  id: string;
  rule_ref: string;
  severity: Severity;
  check: string;
  fields: string[];
  message: string;
  enabled: boolean;
  /** Whether tier 1 can show the clause text behind this citation. Five rules
   *  cite gazettes this deployment does not carry, and a "why" button that
   *  silently does nothing looks broken. */
  text_held: boolean;
}

export interface Rulepack {
  version: string;
  authority: string | null;
  claims_currency: unknown;
  sources: { id: number; ref: string; scope: string }[];
  amendments_checked: { ref: string; action: string; effect: string }[];
  amendments_unverified: { ref: string; note?: string }[];
  rules: RuleDoc[];
  documents_held: string[];
}
