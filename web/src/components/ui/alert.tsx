import * as React from "react";
import { cn } from "@/lib/cn";

export function Alert({
  tone = "neutral",
  title,
  children,
  className,
}: {
  tone?: "neutral" | "fail" | "review" | "pass";
  title?: string;
  children?: React.ReactNode;
  className?: string;
}) {
  const tones = {
    neutral: "border-border bg-surface-2 text-fg",
    fail: "border-fail bg-fail-bg text-fail-fg",
    review: "border-review bg-review-bg text-review-fg",
    pass: "border-pass bg-pass-bg text-pass-fg",
  } as const;
  return (
    <div role="status" className={cn("rounded-lg border p-4", tones[tone], className)}>
      {title ? <p className="font-semibold">{title}</p> : null}
      {children ? <div className="text-base">{children}</div> : null}
    </div>
  );
}
