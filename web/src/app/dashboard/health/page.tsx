import type { Metadata } from "next";
import { opsHealth, tryServerFetch } from "@/lib/api/server";
import { parseFilters, filterQuery } from "@/lib/filters";
import { Card, CardTitle, CardHint } from "@/components/ui/card";
import { Table, THead, TR, TH, TD, Num, Empty } from "@/components/ui/table";
import { Alert } from "@/components/ui/alert";
import { count, millis, percent } from "@/lib/format";
import type { HealthResponse, HealthView } from "@/lib/api/types";

export const metadata: Metadata = { title: "System health" };

/**
 * Q8 — is the tool itself healthy?
 *
 * Section 11: *"Unusual on an enforcement dashboard, and worth keeping. It shows
 * the department the tool is working, not just that products are failing — and
 * it's where you'd notice OCR quietly degrading after a model update."*
 *
 * Latency is split by cache hit and miss rather than blended, and
 * `analytics.health` explains why in its docstring: a single median moves with
 * the cache rate rather than with performance, so a genuine regression would
 * hide behind a good morning's caching. Section 4's budgets are printed beside
 * the measurements, because a number with no budget next to it is not a health
 * indicator, it is trivia.
 */
const BUDGET = {
  hit: 60,
  miss: 561,
};

const TIER_MEANING: Record<string, string> = {
  L0: "online — full pipeline",
  L1: "offline — scanned on the device",
  L2: "no scale marker — ratio and placement rules only",
  L3: "text partly unread",
  L4: "nothing readable — evidence record only",
};

export default async function HealthPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const filters = parseFilters(await searchParams);
  const [view, ops] = await Promise.all([
    tryServerFetch<HealthView>("/dashboard/health", filterQuery(filters)),
    opsHealth<HealthResponse>(),
  ]);

  if (!view) return <Alert tone="review">This view is for supervisors and above.</Alert>;

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-2xl font-semibold">System health</h1>
        <p className="text-sm text-fg-muted">
          Q8 — latency, coverage, cache rate and sync backlog, measured on production scans rather
          than on a benchmark we ran once.
        </p>
      </div>

      <ul className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Median latency · cache hit"
          value={millis(view.median_latency_ms_cache_hit)}
          budget={`budget ${BUDGET.hit} ms`}
          over={overBudget(view.median_latency_ms_cache_hit, BUDGET.hit)}
        />
        <Stat
          label="Median latency · cache miss"
          value={millis(view.median_latency_ms_cache_miss)}
          budget={`budget ${BUDGET.miss} ms`}
          over={overBudget(view.median_latency_ms_cache_miss, BUDGET.miss)}
        />
        <Stat label="p95 · cache miss" value={millis(view.p95_latency_ms_cache_miss)} />
        <Stat label="Cache hit rate" value={percent(view.cache_hit_rate)} />
        <Stat label="Mean coverage" value={percent(view.mean_coverage)} />
        <Stat label="Awaiting sync" value={count(view.awaiting_sync)} />
        <Stat label="Scans in period" value={count(view.scans)} />
        <Stat
          label="Rulepack"
          value={ops?.rulepack_version ?? "—"}
          budget={ops ? `${ops.rules_loaded} rules loaded` : undefined}
        />
      </ul>

      <Card>
        <CardTitle>Degradation tiers</CardTitle>
        <CardHint>
          Section 5&apos;s ladder, counted. A rising L2 share means marker cards are not making it
          into frame; a rising L3 share is the shape OCR degradation takes.
        </CardHint>
        <div className="mt-3">
          <Table>
            <THead>
              <TR>
                <TH>Tier</TH>
                <TH>What it means</TH>
                <TH className="text-right">Scans</TH>
                <TH className="text-right">Share</TH>
              </TR>
            </THead>
            <tbody>
              {Object.keys(view.degradation_tiers).length === 0 ? (
                <Empty colSpan={4}>No scans in this period.</Empty>
              ) : (
                Object.entries(view.degradation_tiers).map(([tier, n]) => (
                  <TR key={tier}>
                    <TD className="font-medium">{tier}</TD>
                    <TD className="text-fg-muted">{TIER_MEANING[tier] ?? "—"}</TD>
                    <Num>{count(n)}</Num>
                    <Num>{view.scans ? percent(n / view.scans) : "—"}</Num>
                  </TR>
                ))
              )}
            </tbody>
          </Table>
        </div>
      </Card>

      {ops ? (
        <Card>
          <CardTitle>Service</CardTitle>
          <dl className="mt-2 grid gap-2 sm:grid-cols-2">
            <Row label="Status" value={ops.status} />
            <Row label="Storage" value={ops.storage} />
            <Row label="Models present" value={`${ops.models_present} of ${ops.models_expected}`} />
            <Row label="Rules loaded" value={String(ops.rules_loaded)} />
          </dl>
          {(ops.detail ?? []).length > 0 ? (
            <Alert tone="review" className="mt-3">
              {(ops.detail ?? []).join(" · ")}
            </Alert>
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}

function overBudget(value: number | null, budget: number): boolean {
  return value !== null && value > budget;
}

function Stat({
  label,
  value,
  budget,
  over,
}: {
  label: string;
  value: string;
  budget?: string;
  over?: boolean;
}) {
  return (
    <li className="card rounded-lg border border-border bg-surface p-4">
      <p className="text-sm text-fg-muted">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${over ? "text-fail" : ""}`}>
        {value}
      </p>
      {budget ? (
        <p className={`text-xs ${over ? "text-fail" : "text-fg-muted"}`}>
          {budget}
          {over ? " — over" : ""}
        </p>
      ) : null}
    </li>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b border-border pb-1 last:border-0">
      <dt className="text-fg-muted">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
