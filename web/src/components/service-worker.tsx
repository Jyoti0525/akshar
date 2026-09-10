"use client";

import { useEffect } from "react";

/**
 * Registers the service worker built by `scripts/build-sw.mjs`.
 *
 * `workbox-window` rather than a bare `navigator.serviceWorker.register`,
 * because it is the piece that tells us a new build is waiting. An officer with
 * a month-old tab open would otherwise keep running last month's rulepack, and
 * section 13's whole promise is that a new amendment reaches the field as data
 * rather than as a redeploy — which is worth nothing if the client never picks
 * it up.
 */
export function ServiceWorker() {
  useEffect(() => {
    if (typeof window === "undefined" || !("serviceWorker" in navigator)) return;
    if (process.env.NODE_ENV !== "production") return;

    let cancelled = false;
    void (async () => {
      const { Workbox } = await import("workbox-window");
      if (cancelled) return;
      const wb = new Workbox("/sw.js");
      wb.addEventListener("waiting", () => {
        // Not applied silently: a scan in progress must not have its code
        // swapped underneath it. The banner is on `/queue`, where an officer
        // between shops will see it.
        window.dispatchEvent(new CustomEvent("akshar:update-ready"));
      });
      await wb.register();
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return null;
}
