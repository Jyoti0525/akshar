import * as React from "react";
import { cn } from "@/lib/cn";

/**
 * The top of every page: an eyebrow, the title, one line of orientation, and
 * whatever actions the page owns.
 *
 * It exists because each route had been inventing its own. The scan screen put
 * a hint in a `text-sm` paragraph baseline-aligned to the right of an `h1`, so
 * at a narrow width the sentence wrapped under the heading and looked like a
 * subtitle it had not been written as; the dashboard used a different size
 * again. A tool whose pages each start differently reads as several tools
 * stapled together, and an officer moving between capture and review should not
 * have to re-find the title each time.
 *
 * The description sits *below* the title and is capped at a readable measure.
 * The actions sit on the right from `sm` up and wrap beneath on a phone, where
 * there is no room for them beside a serif heading.
 */
export function PageHeader({
  title,
  description,
  eyebrow,
  actions,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  /** A short uppercase label above the title — usually the section. */
  eyebrow?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-4 border-b border-border pb-5 sm:flex-row sm:items-start sm:justify-between sm:gap-6",
        className,
      )}
    >
      <div className="min-w-0">
        {eyebrow ? <p className="eyebrow mb-1.5">{eyebrow}</p> : null}
        <h1 className="text-2xl text-fg">{title}</h1>
        {description ? (
          <p className="mt-2 max-w-prose text-base leading-relaxed text-fg-muted">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
