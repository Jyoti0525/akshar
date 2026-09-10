"use client";

import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";

/**
 * Section 13a: the summary in the two formats a department files, plus HTML.
 *
 * The filters travel with the export, so what is filed is what was on screen.
 * The routes render inline — `violation_summary_report` explains why it does not
 * defer the way the per-scan PDF does — so these are plain links.
 */
export function SummaryExport() {
  const params = useSearchParams();

  const href = (format: string) => {
    const query = new URLSearchParams(params.toString());
    query.set("format", format);
    query.delete("offset");
    return `/api/v1/summary/report?${query.toString()}`;
  };

  return (
    <div className="no-print flex flex-wrap gap-2">
      <Button asChild variant="outline" size="sm">
        <a href={href("pdf")} download="violation-summary.pdf">
          PDF
        </a>
      </Button>
      <Button asChild variant="outline" size="sm">
        <a href={href("docx")} download="violation-summary.docx">
          DOCX
        </a>
      </Button>
      <Button asChild variant="outline" size="sm">
        <a href={href("html")} target="_blank" rel="noreferrer">
          HTML
        </a>
      </Button>
      <Button variant="outline" size="sm" onClick={() => window.print()}>
        Print
      </Button>
    </div>
  );
}
