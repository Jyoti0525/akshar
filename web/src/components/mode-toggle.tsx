"use client";

import { useSyncExternalStore } from "react";
import { Button } from "./ui/button";

/**
 * Section 11: *"a high-contrast daylight mode — officers work outdoors and the
 * default palette will be unreadable at noon."*
 *
 * Three states rather than the usual two, cycled by one control. Daylight is not
 * a variant of light: it drops every mid-grey, every tint behind a badge and
 * every thin border, because those are exactly the distinctions a phone screen
 * loses in direct sun. The palettes are in `globals.css`.
 *
 * **`data-mode` on `<html>` is the single source of truth, and this component
 * reads it rather than keeping a copy.** The inline script in `layout.tsx`
 * already sets that attribute before first paint, so a `useState` mirror
 * populated from an effect would be a second, briefly-wrong copy of a value the
 * DOM already had — which is a flash of the wrong label on every load, and the
 * cascading render `react-hooks/set-state-in-effect` exists to catch.
 * `useSyncExternalStore` is the shape React provides for exactly this: the
 * document is the external store.
 *
 * ---------------------------------------------------------------------------
 * WHY THE LABEL IS GONE AND THE ICON IS DRAWN RATHER THAN TYPED
 * ---------------------------------------------------------------------------
 * The control used to print the mode name beside the glyph from `md` up. In a
 * masthead that now holds a tier badge and an account menu on the same row,
 * that word was the widest thing on the right-hand side and the first to push
 * the navigation into wrapping on a small laptop. The name is still announced —
 * `title` on hover, and a `sr-only` sentence for a screen reader — so nothing
 * is lost but the pixels.
 *
 * The glyphs are SVG rather than the ☀ ☾ ◐ characters they were. Those three
 * come from three different Unicode blocks, and a device that has no glyph for
 * one of them renders a replacement box in the masthead of an enforcement tool.
 * Devanagari-capable Android builds are a real case here.
 */
const MODES = ["system", "light", "dark", "daylight"] as const;
type Mode = (typeof MODES)[number];

const LABEL: Record<Mode, string> = {
  system: "Display: follows the device",
  light: "Display: light",
  dark: "Display: dark",
  daylight: "Display: daylight — high contrast for direct sun",
};

const CHANGED = "akshar:mode-changed";

function subscribe(onChange: () => void): () => void {
  window.addEventListener(CHANGED, onChange);
  // A second tab is a real case here: an officer with the dashboard open on a
  // laptop and the scanner open beside it should not have two palettes.
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener("storage", onChange);
  };
}

function readMode(): Mode {
  const attribute = document.documentElement.getAttribute("data-mode");
  return (MODES as readonly string[]).includes(attribute ?? "") ? (attribute as Mode) : "system";
}

/** Server render, and the first client render before hydration: no document. */
function serverMode(): Mode {
  return "system";
}

function Icon({ mode }: { mode: Mode }) {
  const common = {
    viewBox: "0 0 20 20",
    className: "h-5 w-5",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true as const,
  };

  if (mode === "dark") {
    return (
      <svg {...common}>
        <path d="M16 12.2A6.8 6.8 0 0 1 7.8 4a6.6 6.6 0 1 0 8.2 8.2Z" />
      </svg>
    );
  }
  if (mode === "light") {
    return (
      <svg {...common}>
        <circle cx="10" cy="10" r="3.4" />
        <path d="M10 2.4v1.8M10 15.8v1.8M2.4 10h1.8M15.8 10h1.8M4.6 4.6l1.3 1.3M14.1 14.1l1.3 1.3M15.4 4.6l-1.3 1.3M5.9 14.1l-1.3 1.3" />
      </svg>
    );
  }
  if (mode === "daylight") {
    // A sun inside a hard-edged frame: the same sun as `light`, boxed, because
    // the difference between the two modes is contrast rather than brightness.
    return (
      <svg {...common}>
        <rect x="2.2" y="2.2" width="15.6" height="15.6" rx="1.4" />
        <circle cx="10" cy="10" r="3" fill="currentColor" stroke="none" />
        <path d="M10 4.4v1.2M10 14.4v1.2M4.4 10h1.2M14.4 10h1.2" />
      </svg>
    );
  }
  // system — a circle half filled, the conventional "follows the device" mark.
  return (
    <svg {...common}>
      <circle cx="10" cy="10" r="7.2" />
      <path d="M10 2.8a7.2 7.2 0 0 1 0 14.4Z" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function ModeToggle() {
  const mode = useSyncExternalStore(subscribe, readMode, serverMode);

  const cycle = () => {
    const next = MODES[(MODES.indexOf(mode) + 1) % MODES.length] ?? "system";
    if (next === "system") {
      document.documentElement.removeAttribute("data-mode");
    } else {
      document.documentElement.setAttribute("data-mode", next);
    }
    try {
      if (next === "system") localStorage.removeItem("akshar-mode");
      else localStorage.setItem("akshar-mode", next);
    } catch {
      // Private mode with site data blocked. The attribute above is already
      // applied, so the choice holds for this session; it just will not be
      // remembered, and that is the correct behaviour rather than an error.
    }
    window.dispatchEvent(new Event(CHANGED));
  };

  return (
    <Button variant="outline" size="icon" onClick={cycle} title={LABEL[mode]}>
      <Icon mode={mode} />
      <span className="sr-only">{LABEL[mode]}. Activate to change.</span>
    </Button>
  );
}
