import * as React from "react";
import { cn } from "@/lib/cn";

/**
 * A panel. `.card` in `globals.css` supplies the elevation, which differs by
 * palette: a warm drop shadow in light, a one-pixel inner top highlight in
 * dark (a shadow against #15100f is invisible at any opacity worth paying for),
 * and nothing at all in daylight — a soft shadow is the first thing a sunlit
 * screen loses, so that mode separates panels with rule width instead.
 *
 * `p-5` rather than `p-4`. At 16 px body text — section 11's floor — a 16 px
 * gutter puts one line-height between the text and the edge, and the panel
 * reads as a box drawn around content rather than as a surface holding it.
 */
export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("card rounded-lg border border-border bg-surface p-5", className)}
      {...props}
    />
  );
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn("text-lg font-semibold text-fg", className)} {...props} />;
}

export function CardHint({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm leading-snug text-fg-muted", className)} {...props} />;
}
