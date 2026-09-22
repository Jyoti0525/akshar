import * as React from "react";
import { cn } from "@/lib/cn";

/**
 * Form controls.
 *
 * Two things are true of every control in this file and were true of none of
 * them before.
 *
 * **The edge clears 3:1.** WCAG 2.1 §1.4.11 requires that much of "visual
 * information required to identify user interface components". These used
 * `--border`, the decorative hairline, which measures 1.42:1 against the page —
 * so on the phone in direct sunlight that section 11 designs for, an input was
 * an invisible rectangle. They now take `--border-strong`, which is 3.30:1 in
 * light and 3.39:1 in dark. `npm run check:contrast` asserts both.
 *
 * **`suppressHydrationWarning` is set.** Password managers stamp
 * `fdprocessedid` onto inputs before React hydrates; see the long note in
 * `ui/button.tsx` for why this belongs on the leaf and not on a wrapper.
 *
 * Everything shares one shape string so an input, a select and a textarea are
 * the same object at three heights rather than three components that happen to
 * look similar.
 */
const control =
  "w-full rounded-md border border-border-strong bg-surface text-base text-fg transition-colors placeholder:text-fg-muted hover:border-fg-muted disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-fail aria-[invalid=true]:bg-fail-bg";

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input className={cn(control, "h-touch px-3", className)} suppressHydrationWarning {...props} />
  );
}

export function Select({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  // A native `<select>` rather than a Radix listbox. On a phone in a market the
  // native picker is the fastest control there is, it works with no JavaScript,
  // and its keyboard behaviour is the one the officer already knows.
  return (
    <select
      className={cn(control, "h-touch px-2.5", className)}
      suppressHydrationWarning
      {...props}
    />
  );
}

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("block text-sm font-semibold text-fg", className)} {...props} />;
}

export function Textarea({
  className,
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(control, "min-h-24 p-3 leading-relaxed", className)}
      suppressHydrationWarning
      {...props}
    />
  );
}

/**
 * The text under a control. Separated out because every form in this app had
 * written its own, at three different sizes and two different greys, and a hint
 * that looks different on each screen reads as an afterthought on each screen.
 */
export function Hint({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("max-w-prose text-sm leading-snug text-fg-muted", className)} {...props} />;
}
