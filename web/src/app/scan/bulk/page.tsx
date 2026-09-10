import type { Metadata } from "next";
import { BulkUploader } from "@/components/scan/bulk-uploader";

export const metadata: Metadata = { title: "Bulk upload" };

/**
 * Section 8c: bulk returns `202 Accepted` and a job id, because *"nobody is
 * waiting on this"*. The screen is therefore a job monitor, not a scanner: it
 * hands over the files and then reports progress, and closing it does not cancel
 * anything.
 */
export default function BulkPage() {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5">
      <div>
        <h1 className="text-2xl font-semibold">Bulk upload</h1>
        <p className="mt-1 text-base text-fg-muted">
          A season&apos;s photographs, queued and processed in the background. Up to 500 files per
          request; send several requests for more. You can close this page — the job continues.
        </p>
      </div>
      <BulkUploader />
    </div>
  );
}
