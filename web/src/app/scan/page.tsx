import type { Metadata } from "next";
import { Scanner } from "@/components/scan/scanner";

export const metadata: Metadata = { title: "Scan" };

export default function ScanPage() {
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-semibold">Scan a package</h1>
        <p className="text-sm text-fg-muted">
          Keep the marker card flat beside the pack and fill the frame with the declaration panel.
        </p>
      </div>
      <Scanner />
    </div>
  );
}
