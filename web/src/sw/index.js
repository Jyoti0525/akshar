/**
 * The service worker. Section 15b: *"PWA: Workbox 7. Models cached `CacheFirst`
 * with explicit versioning; API `NetworkFirst`; app shell precached."*
 *
 * Written as a Workbox `injectManifest` source rather than assembled by
 * `generateSW`, because the three caching decisions below are not defaults and
 * each has a reason that belongs next to it. `scripts/build-sw.mjs` bundles this
 * file and writes `public/sw.js`.
 *
 * This file runs in a worker, not in the page: no DOM, no `window`, and it is
 * excluded from the app's TypeScript project (`tsconfig.json`).
 */
import { clientsClaim } from "workbox-core";
import { precacheAndRoute, cleanupOutdatedCaches } from "workbox-precaching";
import { registerRoute, setDefaultHandler, setCatchHandler } from "workbox-routing";
import { CacheFirst, NetworkFirst, StaleWhileRevalidate } from "workbox-strategies";
import { CacheableResponsePlugin } from "workbox-cacheable-response";
import { ExpirationPlugin } from "workbox-expiration";

// The app shell. The placeholder below is replaced at build time with the file
// list `scripts/build-sw.mjs` collects; Workbox requires exactly one occurrence
// of it in this file, so it must not be named anywhere else, comments included.
precacheAndRoute(self.__WB_MANIFEST);
cleanupOutdatedCaches();
clientsClaim();

/**
 * Models — `CacheFirst`, and the reason it is safe is the filename.
 *
 * Section 5 puts ~44 MB of weights in the browser. Revalidating those on every
 * scan would defeat the entire offline design, so they are served from the cache
 * without asking. That is only correct because every model file carries its
 * version in its name (`src/lib/ocr/models.ts`): a new model is a new URL, and
 * the old entry ages out rather than being silently replaced.
 */
registerRoute(
  ({ url }) => url.pathname.startsWith("/models/"),
  new CacheFirst({
    cacheName: "akshar-models-v1",
    plugins: [
      new CacheableResponsePlugin({ statuses: [0, 200] }),
      // A year, and only as many entries as the bundle has. The cap matters:
      // section 5 budgets the cached bundle under 60 MB, and an unbounded model
      // cache across two model versions would quietly double that.
      new ExpirationPlugin({ maxEntries: 12, maxAgeSeconds: 365 * 24 * 60 * 60 }),
    ],
  }),
);

/**
 * The API — `NetworkFirst`.
 *
 * A verdict from four hours ago is worse than no verdict, because an officer
 * cannot tell it is stale. So the network wins whenever there is one, and the
 * cache is a fallback that exists for the dashboard and the rulepack rather than
 * for scanning. Scanning offline does not read this cache at all: it writes to
 * the outbox (`src/lib/offline/outbox.ts`), which is a queue, not a cache.
 *
 * `POST /scans` and `/scans/sync` are excluded — a cached mutation is a
 * duplicated inspection record.
 */
registerRoute(
  ({ url, request }) => url.pathname.startsWith("/api/v1/") && request.method === "GET",
  new NetworkFirst({
    cacheName: "akshar-api-v1",
    networkTimeoutSeconds: 6,
    plugins: [
      new CacheableResponsePlugin({ statuses: [200] }),
      new ExpirationPlugin({ maxEntries: 200, maxAgeSeconds: 24 * 60 * 60 }),
    ],
  }),
);

/** Next's build output is content-hashed, so it can be revalidated in the
 *  background without ever showing a stale asset for a URL that changed. */
registerRoute(
  ({ url }) => url.pathname.startsWith("/_next/static/"),
  new StaleWhileRevalidate({ cacheName: "akshar-static-v1" }),
);

registerRoute(
  ({ request }) => request.destination === "font" || request.destination === "image",
  new StaleWhileRevalidate({
    cacheName: "akshar-assets-v1",
    plugins: [new ExpirationPlugin({ maxEntries: 60, maxAgeSeconds: 30 * 24 * 60 * 60 })],
  }),
);

/**
 * Navigations — network first, then the cached page, then `/offline`.
 *
 * Section 5, tier L1: *"the scan runs locally by default and syncs when it
 * can."* An officer who opens the app in a basement market must land on
 * something usable, and `/offline` explains what still works rather than showing
 * the browser's dinosaur.
 */
const PAGES = "akshar-pages-v1";

const navigations = new NetworkFirst({
  cacheName: PAGES,
  networkTimeoutSeconds: 4,
  plugins: [new CacheableResponsePlugin({ statuses: [200] })],
});

registerRoute(({ request }) => request.mode === "navigate", navigations);

/**
 * Three pages are fetched at install rather than on first visit.
 *
 * The App Router renders these on demand — the root layout reads a cookie — so
 * they are not static files and cannot be precached by globbing the build
 * output. But an officer who installs the app in the office and walks into a
 * basement market has never visited `/queue`, and "cached on first visit" would
 * mean it is not there the one time it is needed. So the worker fetches them
 * while it still has the network it was installed with.
 *
 * `/scan` and `/queue` are the two screens that work with no server at all.
 * `/offline` is the fallback everything else lands on.
 */
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(PAGES).then(async (cache) => {
      for (const url of ["/offline", "/scan", "/queue"]) {
        // Individually, and forgiving: one page that 401s or 404s must not fail
        // the whole installation and leave the app with no worker at all.
        try {
          await cache.add(new Request(url, { credentials: "same-origin" }));
        } catch {
          /* left uncached; the navigation handler will try the network */
        }
      }
    }),
  );
});

setDefaultHandler(new StaleWhileRevalidate({ cacheName: "akshar-default-v1" }));

setCatchHandler(async ({ request }) => {
  if (request.mode === "navigate") {
    const cache = await caches.open(PAGES);
    const offline = await cache.match("/offline");
    if (offline) return offline;
  }
  return Response.error();
});

/** The page asks for this when the officer chooses to apply an update, so a
 *  new build never swaps itself in underneath a scan in progress. */
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
});
