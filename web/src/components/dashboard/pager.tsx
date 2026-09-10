import Link from "next/link";
import { Button } from "@/components/ui/button";
import { count } from "@/lib/format";

/**
 * Server-side pagination, section 11's build rule.
 *
 * Links rather than buttons, so a page of a table is itself addressable — the
 * same reason the filters live in the URL. It also means the pager works with
 * JavaScript disabled and can be opened in a new tab, which is how someone
 * comparing two districts actually works.
 */
export function Pager({
  path,
  search,
  total,
  limit,
  offset,
}: {
  path: string;
  search: URLSearchParams;
  total: number;
  limit: number;
  offset: number;
}) {
  const href = (value: number) => {
    const next = new URLSearchParams(search);
    if (value > 0) next.set("offset", String(value));
    else next.delete("offset");
    const qs = next.toString();
    return qs ? `${path}?${qs}` : path;
  };

  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, total);
  const hasPrevious = offset > 0;
  const hasNext = last < total;

  return (
    <nav
      aria-label="Pagination"
      className="no-print flex flex-wrap items-center justify-between gap-3 text-base"
    >
      <p className="text-fg-muted">
        {total === 0
          ? "No rows"
          : `Showing ${count(first)}–${count(last)} of ${count(total)}`}
      </p>
      <div className="flex gap-2">
        <Button asChild variant="outline" size="sm" aria-disabled={!hasPrevious}>
          <Link
            href={hasPrevious ? href(Math.max(0, offset - limit)) : "#"}
            tabIndex={hasPrevious ? undefined : -1}
            className={hasPrevious ? "" : "pointer-events-none opacity-50"}
          >
            Previous
          </Link>
        </Button>
        <Button asChild variant="outline" size="sm" aria-disabled={!hasNext}>
          <Link
            href={hasNext ? href(offset + limit) : "#"}
            tabIndex={hasNext ? undefined : -1}
            className={hasNext ? "" : "pointer-events-none opacity-50"}
          >
            Next
          </Link>
        </Button>
      </div>
    </nav>
  );
}
