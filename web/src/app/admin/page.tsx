import type { Metadata } from "next";
import { opsHealth, tryServerFetch } from "@/lib/api/server";
import { Card, CardTitle, CardHint } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { count } from "@/lib/format";
import type { ChainStatusResponse, HealthResponse, Rulepack } from "@/lib/api/types";

export const metadata: Metadata = { title: "Administration" };

/**
 * Section 11's `/admin`: *"Users, roles, rulepack versions."*
 *
 * Two of the three are here. **User and role administration has no API** — there
 * is no route that lists, creates or reassigns a user, and `api/sql/stores.py`
 * has no write path for one either. Rather than a screen of controls that post
 * nowhere, the section below says what is missing and what an administrator does
 * instead today. A convincing but inert admin panel is worse than none: someone
 * will believe they revoked an account.
 *
 * The chain verification *is* here, and it is the most important thing on the
 * page. Section 18: an evidence chain nobody verifies is a chain nobody can rely
 * on, and this is the button that verifies it.
 */
export default async function AdminPage() {
  const [pack, chain, ops] = await Promise.all([
    tryServerFetch<Rulepack>("/rules"),
    tryServerFetch<ChainStatusResponse>("/chain/status"),
    opsHealth<HealthResponse>(),
  ]);

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-5">
      <h1 className="text-2xl font-semibold">Administration</h1>

      <Card>
        <CardTitle>Evidence chain</CardTitle>
        <CardHint>
          Section 18: every scan record is hashed into an append-only chain. Verification re-walks
          it and reports the head digest, which should be published somewhere outside this database
          — a chain whose only copy lives beside the data it protects proves less than it looks.
        </CardHint>
        {chain ? (
          <div className="mt-3 flex flex-col gap-2">
            <p className="flex flex-wrap items-center gap-2 text-base">
              <Badge tone={chain.ok ? "pass" : "fail"}>{chain.ok ? "intact" : "broken"}</Badge>
              {count(chain.checked)} records checked
            </p>
            <p className="break-all font-mono text-sm">
              head {chain.head_sha256 ?? "—"}
            </p>
            {(chain.failures ?? []).length > 0 ? (
              <Alert tone="fail" title="Chain failures">
                <ul className="list-disc pl-5">
                  {(chain.failures ?? []).map((failure) => (
                    <li key={failure}>{failure}</li>
                  ))}
                </ul>
              </Alert>
            ) : null}
          </div>
        ) : (
          <p className="mt-2 text-base text-fg-muted">
            Chain status is unavailable — supervisor role or above is required.
          </p>
        )}
      </Card>

      <Card>
        <CardTitle>Rulepack version</CardTitle>
        <CardHint>
          Section 2, point 5: a new amendment means a new YAML entry, not a redeploy. Section 6:
          every scan records which rulepack produced it, so a verdict can be re-run exactly.
        </CardHint>
        <dl className="mt-3 grid gap-2 sm:grid-cols-2">
          <Row label="Active version" value={pack?.version ?? "—"} />
          <Row label="Rules loaded" value={ops ? String(ops.rules_loaded) : "—"} />
          <Row label="Authority" value={pack?.authority ?? "—"} />
          <Row
            label="Models present"
            value={ops ? `${ops.models_present} of ${ops.models_expected}` : "—"}
          />
          <Row label="Storage backend" value={ops?.storage ?? "—"} />
          <Row label="Service status" value={ops?.status ?? "unreachable"} />
        </dl>
        {ops && (ops.detail ?? []).length > 0 ? (
          /*
            One item per line, not `join(" · ")`. Six independent facts glued
            into a single amber paragraph is a wall nobody reads, and two of
            them — the DEMONSTRATION lines — are the ones that decide whether
            any number on this deployment may be quoted. A run-on that buries
            those defeats the point of reporting them at all.
          */
          <Alert tone="review" className="mt-3" title="Why the service reports degraded">
            <ul className="mt-1 flex list-disc flex-col gap-1.5 pl-5">
              {(ops.detail ?? []).map((line) => (
                <li key={line} className={line.startsWith("DEMONSTRATION") ? "font-semibold" : ""}>
                  {line}
                </li>
              ))}
            </ul>
          </Alert>
        ) : null}
      </Card>

      <Card>
        <CardTitle>Users and roles</CardTitle>
        <Alert tone="review" className="mt-2" title="No API for this yet">
          The three roles — officer, supervisor, admin — are enforced on every request by
          <code className="mx-1">require_role</code>, but there is no endpoint that lists, creates
          or reassigns a user, so there is nothing this screen could honestly post to. Accounts are
          managed directly against the database today. Building it is a small set of routes plus a
          write path in the user store; it is not built, and a panel that pretended otherwise would
          be worse than this notice.
        </Alert>
      </Card>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5 border-b border-border pb-2 last:border-0">
      <dt className="text-sm text-fg-muted">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
