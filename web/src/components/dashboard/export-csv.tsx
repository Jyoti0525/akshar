"use client";

import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";

/**
 * Section 11: *"Every table paginates server-side and exports to CSV."*
 *
 * The export deliberately ignores the page. `api/routers/dashboard._table` says
 * why in its own docstring: *"An export that returns only the page you are
 * looking at is the export people complain about."* So the link carries the
 * filters and drops `offset` and `limit`.
 *
 * It is an anchor, not a fetch. The response is a file with a
 * `Content-Disposition`, and letting the browser handle it means no blob is held
 * in memory and the download survives navigating away.
 */
export function ExportCsv({ path, filename }: { path: string; filename: string }) {
  const params = useSearchParams();
  const query = new URLSearchParams(params.toString());
  query.set("format", "csv");
  query.delete("offset");
  query.delete("limit");

  return (
    <Button asChild variant="outline" size="sm">
      <a href={`/api/v1${path}?${query.toString()}`} download={filename}>
        Export CSV
      </a>
    </Button>
  );
}
