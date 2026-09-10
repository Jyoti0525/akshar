"use client";

import Link from "next/link";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartFrame } from "./chart-frame";
import { Table, THead, TR, TH, TD, Num, Empty } from "@/components/ui/table";
import { count, percent, ruleLabel } from "@/lib/format";
import type { RuleRow } from "@/lib/api/types";

/**
 * Q2 — which rule is broken most often?
 *
 * Section 11 calls this *"the most useful chart in the system — if 60% of
 * failures are MRP font height, the department's next move is a public advisory
 * to manufacturers, not more inspections."*
 *
 * Horizontal bars, descending, top eight. A bar for a rule flagged `suspect` is
 * drawn amber rather than red, because section 11's second, quieter purpose for
 * this view is that it audits our own rulepack: *"A rule failing on 95% of
 * products is more likely a bug in our regex than a national conspiracy."*
 * Colouring it as a confirmed violation would be us believing our own bug.
 */
export function RuleBars({
  rules,
  search,
}: {
  rules: RuleRow[];
  /** The current filters, so clicking a bar drills without losing them. */
  search: string;
}) {
  const top = rules.slice(0, 8);
  const data = top.map((rule) => ({
    name: ruleLabel(rule.rule_id),
    rule_id: rule.rule_id,
    failed: rule.failed,
    suspect: rule.suspect,
  }));

  const drill = (ruleId: string) => {
    const params = new URLSearchParams(search);
    params.set("rule_id", ruleId);
    return `/dashboard/rules?${params.toString()}`;
  };

  return (
    <ChartFrame
      title="Violations by rule"
      question="Q2 — which rule is broken most often, and is it really the pack or our regex?"
      chart={
        <div className="h-96 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={data}
              layout="vertical"
              margin={{ top: 8, right: 24, bottom: 8, left: 8 }}
            >
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" tick={{ fill: "var(--fg-muted)", fontSize: 14 }} stroke="var(--border)" />
              <YAxis
                type="category"
                dataKey="name"
                width={160}
                tick={{ fill: "var(--fg-muted)", fontSize: 14 }}
                stroke="var(--border)"
              />
              <Tooltip
                cursor={{ fill: "var(--surface-2)" }}
                contentStyle={{
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  color: "var(--fg)",
                  fontSize: 16,
                }}
              />
              <Bar dataKey="failed" name="Failures" isAnimationActive={false}>
                {data.map((entry) => (
                  <Cell
                    key={entry.rule_id}
                    fill={entry.suspect ? "var(--review)" : "var(--fail)"}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      }
      table={
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
            {rules.length === 0 ? (
              <Empty colSpan={5}>No rule failed in this period.</Empty>
            ) : (
              rules.map((rule) => (
                <TR key={rule.rule_id}>
                  <TD>
                    <Link href={drill(rule.rule_id)} className="underline" title={rule.rule_id}>
                      {ruleLabel(rule.rule_id)}
                    </Link>
                    {rule.suspect ? (
                      <span
                        className="ml-2 rounded bg-review-bg px-1.5 py-0.5 text-xs text-review-fg"
                        title="Fails on over 95% of the packs it is evaluated against. Check the rule before citing it."
                      >
                        check this rule
                      </span>
                    ) : null}
                  </TD>
                  <TD className="text-sm text-fg-muted">{rule.rule_ref}</TD>
                  <Num>{count(rule.checked)}</Num>
                  <Num>{count(rule.failed)}</Num>
                  <Num>{percent(rule.fail_rate)}</Num>
                </TR>
              ))
            )}
          </tbody>
        </Table>
      }
    />
  );
}
