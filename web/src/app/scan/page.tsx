import type { Metadata } from "next";
import { Scanner } from "@/components/scan/scanner";
import { PageHeader } from "@/components/ui/page-header";

export const metadata: Metadata = { title: "Scan" };

export default function ScanPage() {
  return (
    // A form column, not the full dashboard width the layout allows. Two
    // fields side by side and a heading above them do not improve by being
    // stretched to 1150 px; the eye has to travel the whole width to pair a
    // label with its input.
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
      <PageHeader
        eyebrow="Capture"
        title="Scan a package"
        description="Keep the marker card flat beside the pack and fill the frame with the declaration panel. Three photographs of different faces give the best coverage."
      />
      <Scanner />
    </div>
  );
}
