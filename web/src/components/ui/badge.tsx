import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";

/**
 * Section 11: *"REVIEW rows render amber, never red, distinguishable at a glance
 * from a definite failure."*
 *
 * The tone is carried by a leading glyph as well as by colour, so the three
 * states stay distinguishable in greyscale, in a photocopy of a printed report,
 * and to a red-green colourblind officer.
 */
const badge = cva(
  "inline-flex items-center gap-1.5 rounded px-2 py-1 text-sm font-semibold border",
  {
    variants: {
      tone: {
        pass: "bg-pass-bg text-pass-fg border-pass",
        fail: "bg-fail-bg text-fail-fg border-fail",
        review: "bg-review-bg text-review-fg border-review",
        nodata: "bg-nodata-bg text-nodata-fg border-nodata",
        neutral: "bg-surface-2 text-fg border-border",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export type Tone = NonNullable<VariantProps<typeof badge>["tone"]>;

const GLYPH: Record<Tone, string> = {
  pass: "✓",
  fail: "✕",
  review: "!",
  nodata: "–",
  neutral: "",
};

export function Badge({
  tone = "neutral",
  glyph = true,
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { tone?: Tone; glyph?: boolean }) {
  return (
    <span className={cn(badge({ tone }), className)} {...props}>
      {glyph && GLYPH[tone] ? <span aria-hidden="true">{GLYPH[tone]}</span> : null}
      {children}
    </span>
  );
}

/** The single place a verdict status becomes a colour. Anything else deriving
 *  its own mapping is how REVIEW ends up red on one screen. */
export function toneForStatus(status: string): Tone {
  switch (status) {
    case "PASS":
      return "pass";
    case "FAIL":
      return "fail";
    case "REVIEW":
      return "review";
    case "NO_DATA":
    case "NOT_APPLICABLE":
      return "nodata";
    default:
      return "neutral";
  }
}
