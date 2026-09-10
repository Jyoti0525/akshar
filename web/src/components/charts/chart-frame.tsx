"use client";

import { useId, useState } from "react";
import { cn } from "@/lib/cn";

/**
 * Section 11: *"Every chart has a matching table view, because officials copy
 * numbers into reports."*
 *
 * So the table is not a fallback and not an accessibility afterthought — it is
 * the other half of every chart, one keystroke away, and it is what actually
 * gets pasted into a notice. Rendering both also means the numbers behind a
 * chart are readable by a screen reader without any ARIA description of a shape.
 *
 * When printed, both appear: the chart illustrates and the table carries the
 * figures, which is the arrangement a departmental report wants.
 */
export function ChartFrame({
  title,
  question,
  chart,
  table,
}: {
  title: string;
  /** Which of section 11's eight questions this answers. If a chart cannot name
   *  one, section 11 says cut it — so the field is required. */
  question: string;
  chart: React.ReactNode;
  table: React.ReactNode;
}) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const id = useId();

  return (
    <section className="card rounded-lg border border-border bg-surface p-4">
      <header className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">{title}</h2>
          <p className="text-sm text-fg-muted">{question}</p>
        </div>
        <div role="tablist" aria-label={`${title} view`} className="no-print flex gap-1">
          {(["chart", "table"] as const).map((option) => (
            <button
              key={option}
              role="tab"
              type="button"
              id={`${id}-${option}-tab`}
              aria-selected={view === option}
              aria-controls={`${id}-${option}`}
              onClick={() => setView(option)}
              className={cn(
                "h-touch rounded-md px-3 text-base",
                view === option
                  ? "bg-accent text-accent-fg"
                  : "border border-border text-fg hover:bg-surface-2",
              )}
            >
              {option === "chart" ? "Chart" : "Table"}
            </button>
          ))}
        </div>
      </header>

      <div
        role="tabpanel"
        id={`${id}-chart`}
        aria-labelledby={`${id}-chart-tab`}
        hidden={view !== "chart"}
        className="print:!block"
      >
        {chart}
      </div>
      <div
        role="tabpanel"
        id={`${id}-table`}
        aria-labelledby={`${id}-table-tab`}
        hidden={view !== "table"}
        className="print:!block"
      >
        {table}
      </div>
    </section>
  );
}
