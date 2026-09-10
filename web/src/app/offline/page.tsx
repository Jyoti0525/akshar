import type { Metadata } from "next";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/alert";

export const metadata: Metadata = { title: "Offline" };

/**
 * The page the service worker falls back to when a navigation cannot be served.
 *
 * Section 5, tier L4: *"A tool that returns nothing when it can't read is worse
 * than a notebook."* The same principle applies to a page that cannot load — it
 * should say what still works, not show a browser error.
 */
export default function OfflinePage() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-5 py-8">
      <h1 className="text-2xl font-semibold">No network</h1>
      <p className="text-base">
        This page has not been opened on this device before, so there is no copy to show. The parts
        of AKSHAR that do not need a network still work.
      </p>

      <Alert tone="review" title="What still works">
        <ul className="mt-1 list-disc pl-5">
          <li>Scanning. The photograph, its time and its location are recorded on this device.</li>
          <li>The offline queue, including everything already waiting to sync.</li>
          <li>Any screen you have opened before on this device.</li>
        </ul>
      </Alert>

      <p className="text-base text-fg-muted">
        Verdicts arrive when signal returns. Nothing is lost in the meantime, and replaying the
        queue never duplicates a record.
      </p>

      <div className="flex flex-wrap gap-2">
        <Button asChild>
          <Link href="/scan">Scan a package</Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/queue">Open the queue</Link>
        </Button>
      </div>
    </div>
  );
}
