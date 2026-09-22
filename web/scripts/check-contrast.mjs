#!/usr/bin/env node
/**
 * Asserts the contrast claims written in `src/app/globals.css`.
 *
 * AKSHAR.md section 11 asks for 4.5:1 on text and 44 px touch targets, and that
 * file answers with a measured ratio in a comment beside almost every colour. A
 * comment is not a test: the numbers there were correct when they were typed and
 * nothing stopped the next edit from making them fiction. Twice now they had —
 * form-control borders were quoted as adequate at 1.42:1, and the three verdict
 * colours were described as separable by lightness when their luminance ratio is
 * 1.07:1.
 *
 * The values are PARSED OUT OF THE STYLESHEET rather than copied here, so this
 * cannot pass while the real palette fails. Run with `npm run check:contrast`.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "..", "src", "app", "globals.css"), "utf8");

/* ---------------------------------------------------------------- colour --- */

const linear = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);

function luminance(hex) {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? [...h].map((c) => c + c).join("") : h;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255);
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

function ratio(a, b) {
  const [x, y] = [luminance(a), luminance(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

/* ----------------------------------------------------------------- parse --- */

/** The declarations of one selector block, as a plain object of hex values. */
function tokensFor(selector) {
  const start = css.indexOf(selector + " {");
  if (start === -1) throw new Error(`no block for ${selector} in globals.css`);
  const open = css.indexOf("{", start);
  const body = css.slice(open + 1, css.indexOf("\n}", open));
  const out = {};
  // Comments in this file contain `#rrggbb` inside prose, so they are stripped
  // before the declarations are read rather than after.
  for (const line of body.replace(/\/\*[\s\S]*?\*\//g, "").split("\n")) {
    for (const [, name, value] of line.matchAll(/--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,8})/g)) {
      out[name] = value;
    }
  }
  return out;
}

const PALETTES = {
  light: tokensFor(":root"),
  dark: tokensFor(':root[data-mode="dark"]'),
  daylight: tokensFor(':root[data-mode="daylight"]'),
};

/* ---------------------------------------------------------------- assert --- */

let failures = 0;
const quiet = process.argv.includes("--quiet");

function expect(mode, label, fg, bg, floor) {
  const r = ratio(fg, bg);
  const ok = r >= floor;
  if (!ok) failures++;
  if (!ok || !quiet) {
    const mark = ok ? "ok  " : "FAIL";
    console.log(
      `  ${mark} ${r.toFixed(2).padStart(5)}:1  (>=${floor.toFixed(1)})  ${label.padEnd(30)} ${fg} on ${bg}`,
    );
  }
}

for (const [mode, p] of Object.entries(PALETTES)) {
  if (!quiet) console.log(`\n${mode}`);

  // Body text and secondary text, on every ground a surface can be.
  for (const ground of ["bg", "surface", "surface-2", "surface-3"]) {
    expect(mode, `fg on ${ground}`, p.fg, p[ground], 4.5);
    expect(mode, `fg-muted on ${ground}`, p["fg-muted"], p[ground], 4.5);
  }

  // The accent as a link or label, and as a filled control.
  expect(mode, "accent on bg", p.accent, p.bg, 4.5);
  expect(mode, "accent on surface", p.accent, p.surface, 4.5);
  expect(mode, "accent on accent-soft", p.accent, p["accent-soft"], 4.5);
  expect(mode, "accent-fg on accent", p["accent-fg"], p.accent, 4.5);

  // Verdicts: text on its own tint at 4.5:1, the solid as a boundary at 3:1.
  for (const tone of ["pass", "fail", "review", "nodata"]) {
    expect(mode, `${tone}-fg on ${tone}-bg`, p[`${tone}-fg`], p[`${tone}-bg`], 4.5);
    expect(mode, `${tone} edge on ${tone}-bg`, p[tone], p[`${tone}-bg`], 3.0);
  }

  // WCAG 2.1 §1.4.11: a form control's outline must clear 3:1 against both
  // grounds it can sit on. This is the check that was failing.
  expect(mode, "border-strong on surface", p["border-strong"], p.surface, 3.0);
  expect(mode, "border-strong on bg", p["border-strong"], p.bg, 3.0);
}

/*
 * Not an assertion — a standing reminder, printed every run.
 *
 * If this number were ever to reach 3:1 the glyph in `ui/badge.tsx` would
 * become optional. It will not: see the note at the head of globals.css. It is
 * printed so that anyone tempted to drop the glyph sees the cost first.
 */
console.log("\nFAIL vs REVIEW, luminance only (the glyph is what separates them):");
for (const [mode, p] of Object.entries(PALETTES)) {
  console.log(
    `  ${mode.padEnd(9)} solid ${ratio(p.fail, p.review).toFixed(2)}:1` +
      `   tint ${ratio(p["fail-bg"], p["review-bg"]).toFixed(2)}:1` +
      `   text ${ratio(p["fail-fg"], p["review-fg"]).toFixed(2)}:1`,
  );
}

if (failures > 0) {
  console.error(`\n${failures} contrast requirement(s) unmet — see above.`);
  process.exit(1);
}
console.log("\nEvery pairing meets its floor.");
