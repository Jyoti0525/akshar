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
 */
const MODES = ["system", "light", "dark", "daylight"] as const;
type Mode = (typeof MODES)[number];

const LABEL: Record<Mode, string> = {
  system: "Display: system",
  light: "Display: light",
  dark: "Display: dark",
  daylight: "Display: daylight",
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
    <Button variant="outline" size="sm" onClick={cycle} title={LABEL[mode]}>
      <span aria-hidden="true">{mode === "daylight" ? "☀" : mode === "dark" ? "☾" : "◐"}</span>
      <span className="sr-only">{LABEL[mode]}. Activate to change.</span>
      <span className="hidden md:inline">{mode === "system" ? "Display" : mode}</span>
    </Button>
  );
}
