import * as React from "react";
import { cn } from "@/lib/cn";

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-touch w-full rounded-md border border-border bg-bg px-3 text-base text-fg placeholder:text-fg-muted",
        className,
      )}
      {...props}
    />
  );
}

export function Select({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  // A native `<select>` rather than a Radix listbox. On a phone in a market the
  // native picker is the fastest control there is, it works with no JavaScript,
  // and its keyboard behaviour is the one the officer already knows.
  return (
    <select
      className={cn(
        "h-touch w-full rounded-md border border-border bg-bg px-2 text-base text-fg",
        className,
      )}
      {...props}
    />
  );
}

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("block text-sm font-medium text-fg", className)} {...props} />;
}

export function Textarea({
  className,
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "w-full rounded-md border border-border bg-bg p-3 text-base text-fg placeholder:text-fg-muted",
        className,
      )}
      {...props}
    />
  );
}
