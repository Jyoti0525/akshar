"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ChartFrame } from "./chart-frame";
import { Table, THead, TR, TH, TD, Num, Empty } from "@/components/ui/table";
import { count, percent } from "@/lib/format";
import type { TrendPoint } from "@/lib/api/types";

/**
 * Q1 — is non-compliance getting better or worse?
 *
 * Weekly buckets. `analytics.weekly_trend` emits a null rate for a week with no
 * scans rather than skipping it, and `connectNulls` is left off so that gap is
 * drawn as a gap. A line that jumps across three empty weeks asserts a trend
 * through data nobody collected.
 */
export function TrendChart({ points }: { points: TrendPoint[] }) {
  const data = points.map((point) => ({
    week: point.week,
    rate:
      point.non_compliance_rate === null
        ? null
        : Number((point.non_compliance_rate * 100).toFixed(2)),
    scans: point.scans,
  }));

  return (
    <ChartFrame
      title="Non-compliance rate over time"
      question="Q1 — is non-compliance getting better or worse?"
      chart={
        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="week"
                tick={{ fill: "var(--fg-muted)", fontSize: 14 }}
                stroke="var(--border)"
              />
              <YAxis
                unit="%"
                domain={[0, 100]}
                tick={{ fill: "var(--fg-muted)", fontSize: 14 }}
                stroke="var(--border)"
              />
              <Tooltip
                contentStyle={{
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  color: "var(--fg)",
                  fontSize: 16,
                }}
                formatter={(value) => [value === null || value === undefined ? "no scans" : `${value}%`, "Rate"]}
              />
              <Line
                type="monotone"
                dataKey="rate"
                stroke="var(--fail)"
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      }
      table={
        <Table>
          <THead>
            <TR>
              <TH>Week</TH>
              <TH className="text-right">Scans</TH>
              <TH className="text-right">Conclusive</TH>
              <TH className="text-right">Non-compliant</TH>
              <TH className="text-right">Rate</TH>
            </TR>
          </THead>
          <tbody>
            {points.length === 0 ? (
              <Empty colSpan={5}>No scans in this period.</Empty>
            ) : (
              points.map((point) => (
                <TR key={point.week}>
                  <TD>{point.week}</TD>
                  <Num>{count(point.scans)}</Num>
                  <Num>{count(point.conclusive)}</Num>
                  <Num>{count(point.non_compliant)}</Num>
                  <Num>{percent(point.non_compliance_rate)}</Num>
                </TR>
              ))
            )}
          </tbody>
        </Table>
      }
    />
  );
}
