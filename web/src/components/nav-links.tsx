"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Role } from "@/lib/api/types";
import { cn } from "@/lib/cn";

export type NavLink = {
  href: string;
  label: string;
  /** Roles permitted to see the link at all. Display only — see `nav.tsx`. */
  roles: Role[];
  /** Roles for which this is a daily destination, and so sits inline. */
  primaryFor: Role[];
};

/**
 * The primary navigation, with the current section marked.
 *
 * Client-only for one reason: `usePathname`. Everything else about the masthead
 * is static and stays on the server, so this is deliberately the smallest
 * component that can know where we are.
 *
 * `aria-current="page"` is the part that matters — the underline is for people
 * who can see it, and a screen-reader user navigating a landmark with no
 * current-item marker has to guess. Colour is not the only cue for the same
 * reason: the active item is bolder, sits on a tinted ground, and carries a
 * rule along the masthead's own bottom edge.
 */
export function NavLinks({ links }: { links: NavLink[] }) {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Main"
      // Phone: its own full-width row under the brand, scrolling sideways
      // rather than wrapping (see the note in `nav.tsx`). `md` and up: inline.
      //
      // `-mx-4 px-4` bleeds the scroll container to the screen edges so a link
      // can be swiped fully into view instead of stopping under the page
      // gutter; `[scrollbar-width:none]` hides a bar a touch device never
      // needed and a mouse user does not miss on a row of three.
      className="order-last -mx-4 flex w-full min-w-0 items-center gap-0.5 overflow-x-auto px-4 [scrollbar-width:none] md:order-none md:mx-0 md:w-auto md:overflow-visible md:px-0"
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
              // `px-2.5` on a phone and `px-3.5` from `sm` up: three labels plus
              // the brand plus three controls is tight at 390 px, and the touch
              // target is held at 44 px by `h-touch` regardless of the padding.
              "relative flex h-touch shrink-0 items-center rounded-md px-2.5 text-base transition-colors sm:px-3.5",
              active
                ? "bg-accent-soft font-semibold text-accent"
                : "text-fg-muted hover:bg-surface-2 hover:text-fg",
            )}
          >
            {link.label}
            {active ? (
              // Sits on the masthead's bottom border, not the link's, so the
              // marker reads as a tab rather than an underlined word.
              <span
                aria-hidden="true"
                className="absolute inset-x-2.5 -bottom-2.75 h-0.5 rounded-full bg-accent sm:inset-x-3.5"
              />
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}
