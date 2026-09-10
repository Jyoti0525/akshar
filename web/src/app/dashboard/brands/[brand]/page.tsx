import type { Metadata } from "next";
import Link from "next/link";
import { tryServerFetch } from "@/lib/api/server";
import { parseFilters, filterQuery, filterSearch } from "@/lib/filters";
import { Table, THead, TR, TH, TD, Num, Empty } from "@/components/ui/table";
import { Card, CardTitle, CardHint } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { count, dateTime, percent, ruleLabel } from "@/lib/format";
import type { BrandDetail } from "@/lib/api/types";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ brand: string }>;
}): Promise<Metadata> {
  return { title: decodeURIComponent((await params).brand) };
}

/**
 * Q7 — is a specific brand improving after being notified?
 *
 * Section 11: *"Brand detail is where an investigation actually happens: every
 * SKU of that brand, which rules each fails, a timeline of scans, and — the
 * important part — a marker for when the brand was notified, so the department
 * can see whether behaviour changed afterwards. That before-and-after view is
 * the most persuasive artefact this system can produce."*
 *
 * **The notification marker is not drawn, and that is deliberate.**
 * `analytics.brand_detail` says why in its own docstring: the notice date is a
 * departmental action, not a scan fact, and nothing in the database holds one
 * yet. Drawing a plausible line on this timeline would be fabricating the exact
 * artefact the section calls persuasive. The timeline is rendered ready for it —
 * ordered, dated, with each scan's failures — and the note below says what is
 * missing and where it would come from.
 */
export default async function BrandDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ brand: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const brand = decodeURIComponent((await params).brand);
  const filters = parseFilters(await searchParams);
  const detail = await tryServerFetch<BrandDetail>(
    `/dashboard/brands/${encodeURIComponent(brand)}`,
    filterQuery(filters),
  );

  if (!detail) {
    return <Alert tone="review">No scans for this brand, or this view needs a supervisor.</Alert>;
  }

  return (
    <div className="flex flex-col gap-5">
      <div>
        <Link href={`/dashboard/brands${filterSearch(filters)}`} className="text-sm underline">
          ← All brands
        </Link>
        <h1 className="mt-1 text-2xl font-semibold">{detail.brand}</h1>
        {detail.parent ? (
          <p className="text-base text-fg-muted">
            Part of {detail.parent} — the entity a legal notice is addressed to.
          </p>
        ) : null}
      </div>

      <ul className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Scans" value={count(detail.scans)} />
        <Stat label="SKUs checked" value={count(detail.skus_checked)} />
        <Stat label="Fail rate" value={percent(detail.fail_rate)} />
        <Stat label="High-severity" value={count(detail.high_severity)} />
        <Stat
          label="Trend"
          value={detail.trend ?? "not enough data"}
          hint={detail.trend === null ? "fewer than six scans in this period" : undefined}
        />
      </ul>

      <Card>
        <CardTitle>Rules this brand fails</CardTitle>
        <CardHint>Ordered by how often, which is the order a notice should list them in.</CardHint>
        <div className="mt-3">
          <Table>
            <THead>
              <TR>
                <TH>Rule</TH>
                <TH>Clause</TH>
                <TH className="text-right">Checked</TH>
                <TH className="text-right">Failed</TH>
                <TH className="text-right">Fail rate</TH>
              </TR>
            </THead>
            <tbody>
              {detail.rules.length === 0 ? (
                <Empty colSpan={5}>Nothing failed.</Empty>
              ) : (
                detail.rules.map((rule) => (
                  <TR key={rule.rule_id}>
                    <TD title={rule.rule_id}>{ruleLabel(rule.rule_id)}</TD>
                    <TD className="text-sm text-fg-muted">{rule.rule_ref}</TD>
                    <Num>{count(rule.checked)}</Num>
                    <Num>{count(rule.failed)}</Num>
                    <Num>{percent(rule.fail_rate)}</Num>
                  </TR>
                ))
              )}
            </tbody>
          </Table>
        </div>
      </Card>

      <Card>
        <CardTitle>Timeline</CardTitle>
        <CardHint>
          Every scan of this brand, oldest first. The notification marker section 11 asks for is
          not drawn: no notice date is stored anywhere yet, and inventing one would fabricate the
          before-and-after this view exists to prove.
        </CardHint>
        <ol className="mt-3 flex flex-col gap-2">
          {detail.timeline.length === 0 ? (
            <li className="text-fg-muted">No scans in this period.</li>
          ) : (
            detail.timeline.map((entry) => (
              <li
                key={entry.scan_id}
                className="flex flex-wrap items-center gap-3 border-b border-border pb-2 last:border-0"
              >
                <Badge tone={entry.non_compliant ? "fail" : "pass"}>
                  {entry.non_compliant ? "FAIL" : "PASS"}
                </Badge>
                <Link href={`/scan/${entry.scan_id}`} className="underline">
                  {dateTime(entry.captured_at)}
                </Link>
                {entry.district ? (
                  <span className="text-sm text-fg-muted">{entry.district}</span>
                ) : null}
                {entry.failed_rules.length > 0 ? (
                  <span className="text-sm text-fg-muted">
                    {entry.failed_rules.map((rule) => ruleLabel(rule)).join(", ")}
                  </span>
                ) : null}
              </li>
            ))
          )}
        </ol>
      </Card>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <li className="card rounded-lg border border-border bg-surface p-4">
      <p className="text-sm text-fg-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {hint ? <p className="text-xs text-fg-muted">{hint}</p> : null}
    </li>
  );
}
