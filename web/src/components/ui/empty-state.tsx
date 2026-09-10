import * as React from "react";
import { AksharMark } from "@/components/brand";

/**
 * What a page shows before anybody has used it.
 *
 * A fresh deployment shows five zeroes, two blank chart frames and an empty
 * table, which is indistinguishable from a broken one — and the first person to
 * see that screen is whoever has just installed the thing. The `<Empty>` row
 * inside a table handles "this query matched nothing"; this handles the larger
 * case of "there is nothing here yet, and here is the one thing to do about it".
 *
 * `action` is a single call to action and not a row of them. If there were two
 * equally good next steps this screen would not need to exist.
 */
export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border bg-surface px-6 py-12 text-center">
      <AksharMark size={44} className="opacity-30" />
      <h2 className="text-xl font-semibold text-fg">{title}</h2>
      {children ? <div className="max-w-prose text-base text-fg-muted">{children}</div> : null}
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
