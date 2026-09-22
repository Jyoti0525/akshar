import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";

/**
 * Section 11: 44 px touch targets. `h-touch` is 2.75rem, defined once in
 * `globals.css`, so no variant can quietly ship a 32 px control that an officer
 * cannot hit with a thumb in a market.
 *
 * `outline` takes `--border-strong`, not `--border`. WCAG 2.1 §1.4.11 asks 3:1
 * of anything that identifies a control, and the hairline this used to use
 * measured 1.42:1 — the button had no visible edge at all in bright light,
 * which is the condition this app was built for.
 *
 * The press feedback is a 1 px downward shift rather than a scale transform:
 * scaling resamples the text, and at 16 px on a phone that reads as a flicker.
 * `prefers-reduced-motion` neutralises the transition globally in `globals.css`;
 * the shift itself is instant and stays, because it is feedback rather than
 * decoration.
 */
const button = cva(
  "inline-flex items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap transition-[background-color,border-color,color,box-shadow,translate] active:translate-y-px disabled:pointer-events-none disabled:opacity-50 disabled:active:translate-y-0",
  {
    variants: {
      variant: {
        primary:
          "bg-accent text-accent-fg shadow-[var(--shadow-sm)] hover:brightness-110 active:brightness-95",
        outline:
          "border border-border-strong bg-surface text-fg hover:bg-surface-2 active:bg-surface-3",
        ghost: "text-fg hover:bg-surface-2 active:bg-surface-3",
        danger: "bg-fail text-white shadow-[var(--shadow-sm)] hover:brightness-110 active:brightness-95",
      },
      size: {
        default: "h-touch px-4 text-base",
        sm: "h-touch px-3 text-sm",
        icon: "h-touch w-touch",
      },
    },
    defaultVariants: { variant: "primary", size: "default" },
  },
);

/**
 * Exported so a control that cannot be a `<button>` can still be one visually.
 * The file-upload trigger has to be a `<label>` wrapping a hidden `<input
 * type="file">` — a button cannot open a file picker — and it had been
 * hand-copying an approximation of these classes, which is how it ended up with
 * the decorative hairline border while every real outline button moved to
 * `--border-strong`.
 */
export { button as buttonVariants };

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {
  asChild?: boolean;
}

export function Button({ className, variant, size, asChild, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      className={cn(button({ variant, size }), className)}
      /*
       * Password managers and form-filler extensions (LastPass and its
       * relatives) stamp a `fdprocessedid` attribute onto every button and
       * input in the document *before* React hydrates. React then compares the
       * DOM it finds against the tree it rendered, sees an attribute it never
       * emitted, and reports a hydration mismatch — an error overlay in
       * development, on a page where nothing is actually wrong.
       *
       * The attribute never comes from us: `grep -r fdprocessedid src` is
       * empty. Suppressing the warning on the primitives an extension targets
       * is the documented remedy, and it is deliberately applied HERE rather
       * than higher up: `suppressHydrationWarning` on `<html>` covers that one
       * element, not its descendants, and putting it on a wrapper would hide
       * real mismatches in everything inside it. Scoped to the leaf, it hides
       * exactly the attributes an extension adds to this one control.
       */
      suppressHydrationWarning
      {...props}
    />
  );
}
