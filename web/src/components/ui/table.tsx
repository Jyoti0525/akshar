import * as React from "react";
import { cn } from "@/lib/cn";

/**
 * Section 11: *"Every table paginates server-side and exports to CSV."* The
 * pagination and the export live in `DataTable`; these are the bare elements.
 *
 * `scope` is set on every header cell because a screen reader reading a
 * fourteen-column brands table without it announces numbers with no idea which
 * column they came from.
 */
export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className={cn("w-full border-collapse text-base", className)} {...props} />
    </div>
  );
}

export function THead(props: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className="bg-surface-2" {...props} />;
}

export function TR({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("border-b border-border last:border-0", className)} {...props} />;
}

export function TH({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="col"
      className={cn("px-3 py-3 text-left font-semibold text-fg align-bottom", className)}
      {...props}
    />
  );
}

export function TD({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("px-3 py-3 align-top text-fg", className)} {...props} />;
}

export function Num({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  // Tabular figures: a column of counts that jitters as digits change is
  // measurably slower to scan, and these tables are read by scanning.
  return <TD className={cn("text-right tabular-nums", className)} {...props} />;
}

export function Empty({ children, colSpan }: { children: React.ReactNode; colSpan: number }) {
  return (
    <TR>
      <TD colSpan={colSpan} className="py-8 text-center text-fg-muted">
        {children}
      </TD>
    </TR>
  );
}
