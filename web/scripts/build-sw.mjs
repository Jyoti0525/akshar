/**
 * Build `public/sw.js` from `src/sw/index.js`.
 *
 * Two steps, and the first one is the part that is easy to get wrong.
 *
 * **Workbox's `injectManifest` does not bundle.** It replaces the
 * `self.__WB_MANIFEST` placeholder and writes the file out; the `import`
 * statements at the top of the source are left exactly as they were. A service
 * worker containing bare specifiers fails at script evaluation, which surfaces
 * as `navigator.serviceWorker.ready` never resolving and nothing else — no
 * error in the page, no failed request, just an app that is quietly not offline
 * any more. So the source is bundled with Rollup into a self-contained IIFE
 * first, and Workbox injects into that.
 *
 * **What is precached, and what is deliberately not.** The App Router emits
 * per-route RSC payloads that are content-negotiated, so precaching HTML by
 * globbing the build directory produces entries the runtime never requests.
 * Instead the shell is the static chunk set, and every route is cached on first
 * visit by the `NetworkFirst` navigation handler in the worker. The result is an
 * app that opens offline once it has been opened online — which is the promise
 * section 5 actually makes — without a precache manifest that lies about what it
 * holds.
 */
import { injectManifest } from "workbox-build";
import { rollup } from "rollup";
import nodeResolve from "@rollup/plugin-node-resolve";
import terser from "@rollup/plugin-terser";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { existsSync, rmSync } from "node:fs";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");

const swSrc = resolve(root, "src/sw/index.js");
const bundled = resolve(root, ".next/sw-bundle.js");
const swDest = resolve(root, "public/sw.js");
const globDirectory = resolve(root, ".next");

if (!existsSync(globDirectory)) {
  console.error("No .next directory — run `next build` first.");
  process.exit(1);
}

// -- 1. bundle -------------------------------------------------------------

const build = await rollup({
  input: swSrc,
  plugins: [
    nodeResolve({ browser: true }),
    terser({
      // The placeholder must survive minification intact, or step 2 cannot find
      // it and the shell is precached as nothing.
      mangle: { reserved: ["__WB_MANIFEST"] },
      format: { comments: false },
    }),
  ],
  // Workbox's modules reference `process.env.NODE_ENV` to pick their dev or
  // production logging. Without this the worker throws on `process` at
  // evaluation, which is the same silent failure described above.
  onwarn(warning, warn) {
    if (warning.code === "CIRCULAR_DEPENDENCY") return;
    warn(warning);
  },
});

await build.write({
  file: bundled,
  format: "iife",
  inlineDynamicImports: true,
  sourcemap: false,
  intro: 'const process = { env: { NODE_ENV: "production" } };',
});
await build.close();

// -- 2. inject the precache manifest ---------------------------------------

const { count, size, warnings } = await injectManifest({
  swSrc: bundled,
  swDest,
  globDirectory,
  // Deliberately one pattern over the whole of `static/`, listing extensions
  // rather than directories. Next 15 emitted stylesheets to `static/css/`;
  // Next 16 emits them into `static/chunks/` beside the JavaScript, so the
  // narrower `static/css/**/*.css` matched nothing after the upgrade — and
  // workbox reports that as a *warning*, then writes a perfectly valid service
  // worker with no stylesheet in it. The only symptom is an offline page
  // rendering unstyled, which nobody notices until the demonstration.
  globPatterns: ["static/**/*.{js,css,woff,woff2,ttf,png,svg,webp,avif}"],
  // The chunk filename already contains a content hash, so a revision would be
  // a second hash of the same bytes and would only make the manifest larger.
  dontCacheBustURLsMatching: /\.[0-9a-f]{8,}\./,
  modifyURLPrefix: { "static/": "/_next/static/" },
  // Section 5 caps the cached bundle at 60 MB and the models are ~44 MB of it,
  // so the shell has to stay small. A single chunk over 4 MB is a build problem
  // to look at, not something to precache quietly.
  maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
});

rmSync(bundled, { force: true });

for (const warning of warnings) console.warn(warning);

console.log(
  `service worker written: ${swDest}\n` +
    `precached ${count} files, ${(size / 1024 / 1024).toFixed(2)} MB`,
);

if (size > 12 * 1024 * 1024) {
  console.warn(
    `The precached shell is ${(size / 1024 / 1024).toFixed(1)} MB. Section 5 budgets ~6 MB ` +
      `outside the models; check what grew before shipping.`,
  );
}
