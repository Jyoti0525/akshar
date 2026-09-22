"use client";

import * as React from "react";
import { cn } from "@/lib/cn";

/**
 * A small dropdown menu, hand-rolled rather than pulled from Radix.
 *
 * Two reasons, and the second is the real one. The bundle sits in a service
 * worker precache beside ~50 MB of models on a phone that may be tethered to a
 * 2G signal, so a dependency has to earn its bytes. And this menu holds
 * navigation an officer reaches maybe twice a day — the primary destinations
 * are inline in the masthead — so it does not need submenus, typeahead,
 * collision detection or a portal. It needs to open, to be operable from a
 * keyboard, and to close.
 *
 * What it does implement, because these are not optional:
 *
 * - `aria-haspopup="menu"` / `aria-expanded` on the trigger, `role="menu"` on
 *   the panel and `role="menuitem"` on each child, so a screen reader announces
 *   a menu rather than a div full of links.
 * - Arrow keys move between items, Home/End jump to the ends, Escape closes and
 *   **returns focus to the trigger** — without that last part a keyboard user
 *   who dismisses the menu is dropped at the top of the document.
 * - A pointer press outside closes it, and so does a focus landing outside,
 *   which is the case a plain click-outside handler misses when someone tabs
 *   past the last item.
 *
 * The panel is not portalled. It is inside the sticky masthead, which already
 * establishes the stacking context everything here needs, and a portal would
 * cost the focus-containment code that nothing on this screen requires.
 */

const MenuCloseContext = React.createContext<() => void>(() => {});

/** Dismisses the menu from inside an item — used by the sign-out button. */
export function useMenuClose(): () => void {
  return React.useContext(MenuCloseContext);
}

export function Menu({
  trigger,
  label,
  align = "end",
  children,
  className,
}: {
  /** The button's contents. The button chrome itself is supplied here. */
  trigger: React.ReactNode;
  /** Accessible name for the trigger, e.g. "Account and more". */
  label: string;
  align?: "start" | "end";
  children: React.ReactNode;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const root = React.useRef<HTMLDivElement>(null);
  const triggerRef = React.useRef<HTMLButtonElement>(null);

  const close = React.useCallback(() => setOpen(false), []);

  // Close on a press or a focus that lands outside. `pointerdown` rather than
  // `click` so the menu is already gone by the time the press resolves on
  // whatever was underneath it.
  React.useEffect(() => {
    if (!open) return;
    const outside = (event: Event) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("focusin", outside);
    };
  }, [open]);

  const items = () =>
    Array.from(root.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);

  const focusItem = (index: number) => {
    const all = items();
    if (all.length === 0) return;
    const wrapped = ((index % all.length) + all.length) % all.length;
    all[wrapped]?.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
      return;
    }
    if (!open) {
      // ArrowDown on a closed trigger opens it and lands on the first item,
      // which is the behaviour a keyboard user expects from a menu button.
      if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
        if (event.key === "ArrowDown") {
          event.preventDefault();
          setOpen(true);
          requestAnimationFrame(() => focusItem(0));
        }
      }
      return;
    }
    const all = items();
    const current = all.indexOf(document.activeElement as HTMLElement);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusItem(current + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      focusItem(current <= 0 ? all.length - 1 : current - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusItem(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusItem(all.length - 1);
    }
  };

  return (
    <div ref={root} className="relative" onKeyDown={onKeyDown}>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        onClick={() => setOpen((v) => !v)}
        // Password managers and autofill extensions stamp their own attributes
        // onto buttons before React hydrates; see the note in `ui/button.tsx`.
        suppressHydrationWarning
        className={cn(
          "inline-flex h-touch items-center justify-center gap-1.5 rounded-md border border-border-strong bg-surface px-3 text-sm font-medium text-fg transition-colors hover:bg-surface-2",
          open && "bg-surface-2",
          className,
        )}
      >
        {trigger}
        <svg
          aria-hidden="true"
          viewBox="0 0 12 12"
          className={cn("h-3 w-3 transition-transform", open && "rotate-180")}
        >
          <path d="M2 4.5 6 8.5 10 4.5" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open ? (
        <MenuCloseContext.Provider value={close}>
          <div
            role="menu"
            aria-label={label}
            // Any activation inside the panel dismisses it. Every item here
            // either navigates or signs out, so there is no case where the menu
            // should survive a press.
            onClick={close}
            className={cn(
              "absolute top-[calc(100%+0.5rem)] z-50 min-w-56 overflow-hidden rounded-lg border border-border bg-surface py-1.5 shadow-[var(--shadow-lg)]",
              align === "end" ? "right-0" : "left-0",
            )}
          >
            {children}
          </div>
        </MenuCloseContext.Provider>
      ) : null}
    </div>
  );
}

/** A non-interactive heading inside the panel. */
export function MenuLabel({ children }: { children: React.ReactNode }) {
  return <p className="eyebrow px-3 pb-1 pt-2">{children}</p>;
}

export function MenuSeparator() {
  return <hr className="my-1.5 border-0 border-t border-border" aria-hidden="true" />;
}

/**
 * The shared chrome for anything inside the panel. `asChild`-free on purpose:
 * the two things that go in here are a `next/link` and a button, and both are
 * happy to take a className.
 */
export const menuItemClass =
  "flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-base text-fg transition-colors hover:bg-surface-2 focus-visible:bg-surface-2 aria-[current=page]:font-semibold aria-[current=page]:text-accent";
