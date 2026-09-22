import { IBM_Plex_Mono, IBM_Plex_Sans, IBM_Plex_Sans_Devanagari, IBM_Plex_Serif } from "next/font/google";

/**
 * The type system, self-hosted.
 *
 * `next/font/google` downloads each face at build time and serves it from our
 * own origin as `/_next/static/media/*.woff2`. That is the whole reason it is
 * used here rather than a `<link>` to fonts.googleapis.com: AKSHAR.md section 5
 * puts the officer at tier L1 — no network, in a shop — and a stylesheet that
 * has to reach a CDN before the page has type is a stylesheet that fails at
 * exactly the moment the app is supposed to keep working. Self-hosted files sit
 * in the service worker's precache with everything else under `_next/static`.
 *
 * ---------------------------------------------------------------------------
 * WHY PLEX, AND WHY FOUR CUTS
 * ---------------------------------------------------------------------------
 * `IBM_Plex_Sans_Devanagari` is the decisive one. This app puts a Hindi
 * declaration and its English twin in the same table cell — Rule 9 requires
 * both, and `bilingual_group` judges them together — so the two scripts are
 * read side by side constantly. Pairing a Latin face with whatever Devanagari
 * the device happens to have gives two different weights, two different
 * x-heights and two different greys on one line, and an officer comparing the
 * two halves of a declaration is the last person who should be asked to ignore
 * that. Plex is the one technical superfamily whose Devanagari was drawn as a
 * companion to its Latin rather than found later.
 *
 * The serif is for headings only, and it is a deliberate register choice: the
 * artefact this tool produces is a statutory notice, and a serif masthead over
 * a technical sans is what that document already looks like on paper.
 *
 * The mono is for measurements, rule ids and latency figures — every number an
 * officer might read aloud or copy into a notice. Its slashed zero matters:
 * rule ids like `LMPC.MRP.NUMERAL_HEIGHT` and `L0`/`L1` tier labels put O and 0
 * in the same string.
 *
 * Weights are enumerated rather than taken as a variable axis because each
 * extra weight is bytes in a precache that also holds ~50 MB of models. Only
 * the weights actually used are listed; adding one here is a deliberate act.
 *
 * ---------------------------------------------------------------------------
 * WHAT IS PRELOADED, AND WHY MOST OF IT IS NOT
 * ---------------------------------------------------------------------------
 * `next/font` emits a `<link rel="preload">` for every weight of every subset it
 * is given. Declared naively that was **thirteen** woff2 files racing the page,
 * and the browser said so: thirteen "preloaded but not used within a few seconds
 * of load" warnings on a screen that paints two faces.
 *
 * A preload is a promise that the file is needed for the first paint. It is true
 * of the sans, which sets every label on the capture form, and of the serif,
 * which sets the heading above it.
 *
 * It is true of the mono as well, which is not what a first guess says. The
 * obvious reading is that monospace is for measurements and measurements only
 * exist once a scan has returned — but the tier pill in the masthead sets `L0`
 * in it, on every page, on every load, precisely so the letter and the digit
 * cannot be confused. Leaving it unpreloaded put a font swap in the chrome of
 * every cold load.
 *
 * It is false of the Devanagari, which appears only on a pack that carries a
 * Hindi declaration. That one is still self-hosted, still cached by the service
 * worker and still there offline; it is simply fetched when something asks for
 * it rather than ahead of a screen that may never show it.
 *
 * `latin-ext` is dropped for the same reason. It carries the accented Central
 * and Eastern European letters, and nothing in an Indian enforcement tool is
 * going to ask for a Hungarian double acute.
 */

export const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex-sans",
  display: "swap",
});

export const plexSerif = IBM_Plex_Serif({
  subsets: ["latin"],
  // Headings only, and `globals.css` sets exactly one weight on h1/h2/h3.
  weight: ["600"],
  variable: "--font-plex-serif",
  display: "swap",
});

export const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "600"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const plexDevanagari = IBM_Plex_Sans_Devanagari({
  subsets: ["devanagari"],
  weight: ["400", "600"],
  variable: "--font-plex-devanagari",
  display: "swap",
  // Only a pack carrying a Hindi declaration ever needs it.
  preload: false,
});

/** Applied to `<html>`; the four `--font-plex-*` variables come from these. */
export const fontVariables = [
  plexSans.variable,
  plexSerif.variable,
  plexMono.variable,
  plexDevanagari.variable,
].join(" ");
