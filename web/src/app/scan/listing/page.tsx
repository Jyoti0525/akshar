import type { Metadata } from "next";
import { ListingScanner } from "@/components/scan/listing-scanner";

export const metadata: Metadata = { title: "Check a listing" };

/**
 * The third input channel. Section 2, point 7: *"Photo, bulk images, and listing
 * text with no image at all. The PS names all three; most teams read only
 * 'images'."*
 *
 * And section 3 explains why this page took an afternoon rather than a rewrite:
 * *"The rules engine receives a dictionary of extracted facts and never sees an
 * image... If OCR is wired straight into the rules, that third channel becomes a
 * rewrite."* The same rulepack decides here as decides on a photograph.
 *
 * What is missing on this channel is geometry, and the page says so rather than
 * returning a quieter verdict: an e-commerce listing has no font height and no
 * panel, so the millimetre and placement rules are `NOT_APPLICABLE`, not `PASS`.
 */
export default function ListingPage() {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5">
      <div>
        <h1 className="text-2xl font-semibold">Check an e-commerce listing</h1>
        <p className="mt-1 text-base text-fg-muted">
          Paste the declaration block from a product page. The same rulepack applies, minus the
          rules that need geometry — a listing has no font height and no principal display panel,
          so those return <em>not applicable</em> rather than a pass.
        </p>
      </div>
      <ListingScanner />
    </div>
  );
}
