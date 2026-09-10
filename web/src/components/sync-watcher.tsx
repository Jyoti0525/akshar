"use client";

import { useEffect } from "react";
import { drain } from "@/lib/offline/outbox";

/**
 * Section 5: *"Scans queue in IndexedDB and replay when the network returns."*
 * This is "when the network returns", and it is the only automatic network
 * activity in the application.
 *
 * It listens rather than polls. A timer that wakes every thirty seconds to ask
 * whether the network is back is a timer that runs all day in a pocket; the
 * `online` event fires exactly when there is something to do.
 */
export function SyncWatcher() {
  useEffect(() => {
    if (typeof window === "undefined") return;

    let running = false;
    const run = () => {
      if (running || !navigator.onLine) return;
      running = true;
      void drain()
        .then((result) => {
          if (result.created || result.duplicates) {
            window.dispatchEvent(new CustomEvent("akshar:synced", { detail: result }));
          }
        })
        .finally(() => {
          running = false;
        });
    };

    window.addEventListener("online", run);
    // One attempt on load, for the case where the tab was opened after signal
    // returned and no `online` event was ever fired.
    run();
    return () => window.removeEventListener("online", run);
  }, []);

  return null;
}
