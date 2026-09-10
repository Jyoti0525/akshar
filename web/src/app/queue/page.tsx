import type { Metadata } from "next";
import { OutboxPanel } from "@/components/offline/outbox-panel";

export const metadata: Metadata = { title: "Offline queue" };

/**
 * Section 11's `/queue` route: *"Offline outbox status."*
 *
 * It is the officer's view of section 5 — what is waiting, what is cached, and
 * what this device can actually do without a network. Everything on it is read
 * from the browser, so it works with no connection at all, which is the one
 * condition under which it matters.
 */
export default function QueuePage() {
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-5">
      <div>
        <h1 className="text-2xl font-semibold">Offline queue</h1>
        <p className="mt-1 text-base text-fg-muted">
          What this device is holding, and what it can do without a network.
        </p>
      </div>
      <OutboxPanel />
    </div>
  );
}
