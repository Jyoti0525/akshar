import type { Metadata } from "next";
import { tryServerFetch } from "@/lib/api/server";
import { Card, CardTitle, CardHint } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Table, THead, TR, TH, TD, Empty } from "@/components/ui/table";
import { count } from "@/lib/format";
import type { Rulepack } from "@/lib/api/types";

export const metadata: Metadata = { title: "Rulepack" };

/**
 * The whole legal logic of the system, readable.
 *
 * Section 5: *"the entire legal logic of the system is 40 KB of text — small
 * enough to email. That's the payoff of rules-as-data."* Section 2, point 5:
 * *"Every verdict cites a gazette clause. A new amendment means a new YAML
 * entry, not a redeploy."*
 *
 * `text_held` is shown per rule rather than quietly ignored. Five rules in the
 * pack cite the National Standards and Numeration Rules, whose text this
 * deployment does not carry, and `api/routers/ops.py` says why it is reported:
 * *"a 'why' button that silently does nothing looks broken."* An officer is told
 * the citation is sound and the full text is elsewhere.
 */
export default async function RulesPage() {
  const pack = await tryServerFetch<Rulepack>("/rules");

  if (!pack) {
    return <Alert tone="review">The rulepack could not be loaded.</Alert>;
  }

  const enabled = pack.rules.filter((rule) => rule.enabled);
  const disabled = pack.rules.filter((rule) => !rule.enabled);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5">
      <div>
        <h1 className="text-2xl font-semibold">Active rulepack</h1>
        <p className="mt-1 text-base text-fg-muted">
          Version {pack.version} · {count(enabled.length)} rules active
          {disabled.length > 0 ? `, ${count(disabled.length)} disabled` : ""}
        </p>
        {pack.authority ? (
          <p className="mt-1 text-base">{pack.authority}</p>
        ) : null}
      </div>

      <Card>
        <CardTitle>Sources</CardTitle>
        <CardHint>
          Section 13a&apos;s register: every value in the pack traces to one of these documents.
        </CardHint>
        <ul className="mt-2 list-disc pl-5 text-base">
          {pack.sources.map((source) => (
            <li key={source.id}>
              <span className="font-medium">{source.ref}</span> — {source.scope}
            </li>
          ))}
        </ul>
      </Card>

      {pack.amendments_checked.length > 0 || pack.amendments_unverified.length > 0 ? (
        <Card>
          <CardTitle>Amendments</CardTitle>
          <CardHint>
            Checked, with the effect on the rules we encode stated either way. An amendment that
            changes nothing here is recorded as changing nothing, rather than left off the list.
          </CardHint>
          <ul className="mt-2 flex flex-col gap-2 text-base">
            {pack.amendments_checked.map((amendment) => (
              <li key={amendment.ref}>
                <span className="font-medium">{amendment.ref}</span> — {amendment.action}.{" "}
                <span className="text-fg-muted">{amendment.effect}</span>
              </li>
            ))}
            {pack.amendments_unverified.map((amendment) => (
              <li key={amendment.ref}>
                <Badge tone="review" className="mr-2">
                  unverified
                </Badge>
                {amendment.ref}
                {amendment.note ? <span className="text-fg-muted"> — {amendment.note}</span> : null}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <Card>
        <CardTitle>Rules</CardTitle>
        <div className="mt-3">
          <Table>
            <THead>
              <TR>
                <TH>Rule</TH>
                <TH>Clause</TH>
                <TH>Check</TH>
                <TH>Severity</TH>
                <TH>Applies to</TH>
                <TH>Message</TH>
              </TR>
            </THead>
            <tbody>
              {pack.rules.length === 0 ? (
                <Empty colSpan={6}>The pack is empty.</Empty>
              ) : (
                pack.rules.map((rule) => (
                  <TR key={rule.id} id={rule.id} className={rule.enabled ? undefined : "opacity-60"}>
                    <TD className="font-mono text-sm">{rule.id}</TD>
                    <TD>
                      {rule.rule_ref}
                      {rule.text_held ? null : (
                        <span
                          className="ml-2 text-xs text-fg-muted"
                          title="The citation is sound; this deployment does not carry the gazette text to quote from."
                        >
                          text not held
                        </span>
                      )}
                    </TD>
                    <TD className="font-mono text-sm">{rule.check}</TD>
                    <TD>{rule.severity}</TD>
                    <TD className="text-sm">{rule.fields.join(", ") || "—"}</TD>
                    <TD className="text-sm">{rule.message}</TD>
                  </TR>
                ))
              )}
            </tbody>
          </Table>
        </div>
      </Card>

      <Card>
        <CardTitle>Documents held</CardTitle>
        <CardHint>
          What the citation lookup can quote from. Anything not listed here is cited by gazette
          reference only.
        </CardHint>
        <ul className="mt-2 list-disc pl-5 text-base">
          {pack.documents_held.map((document) => (
            <li key={document}>{document}</li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
