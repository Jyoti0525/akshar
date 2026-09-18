import type { Metadata } from "next";
import Link from "next/link";
import { tryServerFetchResult } from "@/lib/api/server";
import { VerdictHeader } from "@/components/scan/verdict-header";
import { RuleRows } from "@/components/scan/rule-rows";
import { DeclarationTable } from "@/components/scan/declaration-table";
import { CorrectionForm } from "@/components/scan/correction-form";
import { Card, CardTitle, CardHint } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { dateTime } from "@/lib/format";
import type { DeclarationSet, ScanResponse, Verdict } from "@/lib/api/types";

export const metadata: Metadata = { title: "Scan record" };

/** `GET /scans/{id}` returns the stored row and its verdicts separately, rather
 *  than a `ScanResponse`, because the row is what the hash chain covers. */
interface ScanRecord {
  scan: Record<string, unknown>;
  verdicts: Verdict[];
}

/**
 * The full record — the thing attached to a notice.
 *
 * Section 6: *"a finding with no photograph is an allegation, not evidence."*
 * The photograph is in the evidence bucket under its own retention rule and is
 * not served through this API, so this page shows the digest and the object key
 * rather than the image. That is stated in words on the page, because an officer
 * looking for a photograph deserves to be told where it is rather than shown an
 * empty frame.
 */
export default async function ScanDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { data: record, status } = await tryServerFetchResult<ScanRecord>(`/scans/${id}`);

  if (!record) {
    // A 401 is not a 404, and saying so is the difference between an officer
    // signing in again and an officer believing the record was lost. The
    // middleware only checks that the session cookie is *present*, so an
    // expired token reaches this page and the API answers 401 — which read as
    // "not on the server" until 2026-09-18.
    if (status === 401 || status === 403) {
      return (
        <Alert tone="review" title="Your session has ended">
          The record is still on the server — this browser is no longer signed in.{" "}
          <Link href={`/login?next=/scan/${id}`} className="underline">
            Sign in again
          </Link>{" "}
          to open it.
        </Alert>
      );
    }
    if (status === null) {
      return (
        <Alert tone="review" title="The server could not be reached">
          This is a connection problem, not a missing record. The scan is still on the server if it
          was taken online. Try again in a moment.
        </Alert>
      );
    }
    return (
      <Alert tone="review" title="Not found on the server">
        This scan is not on the server. If it was taken offline it is still in the outbox on the
        device that took it — see <Link href="/queue" className="underline">the queue</Link>.
      </Alert>
    );
  }

  const row = record.scan;
  const declarations = (row.declaration_set ?? null) as DeclarationSet | null;

  const scan: ScanResponse = {
    id,
    exit_path: (row.exit_path as ScanResponse["exit_path"]) ?? "full",
    source: (row.source as ScanResponse["source"]) ?? "photo",
    degradation_tier: (row.degradation_tier as ScanResponse["degradation_tier"]) ?? "L0",
    coverage: Number(row.coverage ?? 0),
    latency_ms: Number(row.latency_ms ?? 0),
    cache_hit: Boolean(row.cache_hit),
    declarations,
    verdicts: record.verdicts,
    message: "",
    model_versions: (row.model_versions as Record<string, string>) ?? {},
    rulepack_version: String(row.rulepack_version ?? ""),
    record_sha256: (row.record_sha256 as string | null) ?? null,
    chain_seq: (row.chain_seq as number | null) ?? null,
    report_status: "not_requested",
    evidence: null,
  };

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Scan record</h1>
          <p className="text-sm text-fg-muted">
            {dateTime(row.captured_at as string)}
            {row.district ? ` · ${String(row.district)}` : ""}
          </p>
        </div>
        <div className="no-print flex flex-wrap gap-2">
          <Button asChild variant="outline">
            <a href={`/api/v1/scans/${id}/report?format=pdf`} download={`scan-${id}.pdf`}>
              Report (PDF)
            </a>
          </Button>
          <Button asChild variant="outline">
            <a href={`/api/v1/scans/${id}/report?format=docx`} download={`scan-${id}.docx`}>
              Report (DOCX)
            </a>
          </Button>
        </div>
      </div>

      <VerdictHeader scan={scan} />

      <RuleRows verdicts={record.verdicts} />

      <Card>
        <CardTitle>What was read</CardTitle>
        <CardHint>
          Every declaration the pipeline extracted, with its measured height and the confidence
          behind it. A field that is absent is absent — nothing here is inferred.
        </CardHint>
        <div className="mt-3">
          <DeclarationTable declarations={declarations} />
        </div>
      </Card>

      <Card>
        <CardTitle>Correct a field</CardTitle>
        <CardHint>
          Section 5: corrections are append-only rows, never edits — the scan itself is immutable.
          Section 14: each correction is also a labelled training example.
        </CardHint>
        <div className="mt-3">
          <CorrectionForm scanId={id} declarations={declarations} />
        </div>
      </Card>

      <Card>
        <CardTitle>Provenance</CardTitle>
        <CardHint>
          Section 6: a measurement disputed six months later has to be re-runnable exactly, which
          takes the original image plus the pinned versions below.
        </CardHint>
        <dl className="mt-3 grid gap-2 text-base sm:grid-cols-2">
          <Row label="Scan id" value={id} mono />
          <Row label="Chain sequence" value={scan.chain_seq === null ? "—" : String(scan.chain_seq)} />
          <Row label="Record digest" value={scan.record_sha256 ?? "—"} mono />
          <Row label="Rulepack" value={scan.rulepack_version || "—"} />
          <Row label="Evidence object" value={(row.image_key as string) ?? "not stored"} mono />
          <Row label="Image digest" value={(row.image_sha256 as string) ?? "—"} mono />
          {Object.entries(scan.model_versions ?? {}).map(([name, version]) => (
            <Row key={name} label={name} value={version} mono />
          ))}
        </dl>
        <p className="mt-3 text-sm text-fg-muted">
          The photograph itself lives in the evidence bucket under a seven-year retention rule and
          is not served through this API. Retrieve it by the object key above.
        </p>
      </Card>
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
