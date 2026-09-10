"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Role } from "@/lib/api/types";
import { cn } from "@/lib/cn";

export type NavLink = { href: string; label: string; roles: Role[] };

/**
 * The main navigation, with the current section marked.
 *
 * Client-only for one reason: `usePathname`. Everything else about the masthead
 * is static and stays on the server, so this is deliberately the smallest
 * component that can know where we are.
 *
 * `aria-current="page"` is the part that matters — the underline is for people
 * who can see it, and a screen reader user navigating a nine-item landmark with
 * no current-item marker has to guess. The colour is not the only cue for the
 * same reason: the active item is also bolder and sits on a tinted ground.
 */
export function NavLinks({ links }: { links: NavLink[] }) {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Main"
      // Phone: its own full-width row under the brand, scrolling sideways
      // rather than wrapping (see the note in `nav.tsx`). `md` and up: inline,
      // taking the space between the brand and the controls.
      //
      // `-mx-4 px-4` bleeds the scroll container to the screen edges so the
      // last link can be swiped fully into view instead of stopping under the
      // page gutter; `[scrollbar-width:none]` hides the bar a touch device
      // never needed and a mouse user does not miss on a row of eight links.
      className="order-last -mx-4 flex w-full flex-nowrap items-center gap-0.5 overflow-x-auto px-4 [scrollbar-width:none] md:order-none md:mx-0 md:w-auto md:flex-1 md:overflow-visible md:px-0"
    >
      {links.map((link) => {
        // `startsWith` so /dashboard/brands still lights "Dashboard", but the
        // exact test comes first or "/scan" would also match "/scan/bulk" and
        // both would light at once.
        const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "relative flex h-touch shrink-0 items-center rounded-md px-3 text-base transition-colors",
              active
                ? "bg-accent-soft font-semibold text-accent"
                : "text-fg hover:bg-surface-2 hover:text-accent",
            )}
          >
            {link.label}
            {active ? (
              <span
                aria-hidden="true"
                className="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-accent"
              />
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}
