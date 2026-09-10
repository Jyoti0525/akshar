import type { NextConfig } from "next";

/**
 * AKSHAR.md section 5: inference happens in the browser. Section 15b: *"COOP/COEP
 * headers — without them ONNX Runtime pins `numThreads` to 1 and the WASM path
 * roughly doubles in latency."*
 *
 * `Cross-Origin-Opener-Policy: same-origin` plus
 * `Cross-Origin-Embedder-Policy: require-corp` is what makes `SharedArrayBuffer`
 * available, and `SharedArrayBuffer` is what lets `onnxruntime-web` use more than
 * one WASM thread. They are set here so a `next start` deployment is correct on
 * its own, and repeated in `docs/deployment.md` for anyone terminating TLS in
 * front of it — a reverse proxy that drops them halves L1 silently.
 *
 * The cost of `require-corp` is that every cross-origin subresource must opt in
 * with CORP or CORS. We therefore load nothing cross-origin: models are served
 * from `/models`, and the API is reached through the rewrite below so the
 * browser sees one origin.
 */
const CROSS_ORIGIN_ISOLATION = [
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Cross-Origin-Embedder-Policy", value: "require-corp" },
  { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
];

const SECURITY = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  // Section 18 (privacy): the officer's location goes into the scan record we
  // create, and nowhere else. No third-party script can reach the camera or GPS.
  { key: "Permissions-Policy", value: "camera=(self), geolocation=(self), microphone=()" },
];

const API_ORIGIN = process.env.AKSHAR_API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  typescript: { ignoreBuildErrors: false },
  // Next 16 removed `eslint` from NextConfig; linting is no longer part of
  // `next build`. `npm run lint` runs it, and CI runs that as its own step —
  // which is where it was already being enforced, so nothing is lost but the
  // config key had to go or `tsc` fails on it.
  async headers() {
    return [
      { source: "/:path*", headers: [...CROSS_ORIGIN_ISOLATION, ...SECURITY] },
      {
        // Section 5: models are ~44 MB of the ~50 MB bundle and are versioned in
        // their filename, so they are immutable. The service worker caches them
        // CacheFirst; this header means a cold visit never revalidates either.
        source: "/models/:path*",
        headers: [
          { key: "Cache-Control", value: "public, max-age=31536000, immutable" },
          { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
        ],
      },
      {
        // A service worker that is itself cached cannot ship a fix.
        source: "/sw.js",
        headers: [
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
          { key: "Service-Worker-Allowed", value: "/" },
        ],
      },
    ];
  },
  async rewrites() {
    // `/api/v1/*` is NOT rewritten. It is served by the route handler at
    // `src/app/api/v1/[...path]/route.ts`, which reads the httpOnly session
    // cookie and attaches the bearer token, so no access token is ever
    // reachable from page JavaScript. Filesystem routes take precedence over
    // an `afterFiles` rewrite, which is what an array return from this function
    // produces, so the two could not both apply in any case.
    //
    // `require-corp` above is the other reason everything is same-origin: a
    // response from a separate API host would be blocked unless it carried CORP.
    return [{ source: "/healthz", destination: `${API_ORIGIN}/healthz` }];
  },
};

export default nextConfig;
