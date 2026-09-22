import Link from "next/link";
import type { Role } from "@/lib/api/types";
import { ModeToggle } from "./mode-toggle";
import { ConnectionBadge } from "./connection-badge";
import { BrandLockup } from "./brand";
import { NavLinks, type NavLink } from "./nav-links";
import { AccountMenu } from "./account-menu";

/**
 * Section 11's route table, as navigation, filtered by role.
 *
 * The role comes from a readable cookie and is used for *display only*. Every
 * real authorisation decision is made by `require_role` in `api/deps`, against
 * the signed token. Hiding a link an officer may not use is courtesy; it is not
 * a security control, and it is not treated as one here.
 *
 * ---------------------------------------------------------------------------
 * WHY THERE ARE THREE LINKS HERE AND NOT EIGHT
 * ---------------------------------------------------------------------------
 * Every route in section 11's table used to be a top-level tab. An admin saw
 * eight of them, plus a connection badge, a display toggle and a sign-out
 * button: eleven controls in a masthead, above the one button the officer
 * actually came to press. A row of eight peers also says all eight matter
 * equally, and they do not — an officer opens `/scan` fifty times a day and
 * `/rules` when something surprises them.
 *
 * So each route declares the roles that may *see* it and, separately, the roles
 * for which it is a *daily* destination. Daily destinations sit inline; the
 * rest live behind one menu. Nothing is removed, and no role loses a route it
 * had — a supervisor still reaches Summary, an officer still reaches the
 * outbox. They are one press further away, which is the correct distance for
 * something used weekly.
 *
 * The result is three inline links for an officer, three for a supervisor and
 * two for an admin, with the menu holding whatever is left over for that role.
 *
 * The outbox is the deliberate omission from both lists. It has a permanent
 * indicator of its own — `ConnectionBadge` already reports the tier and the
 * queue depth, because section 5 requires an officer to know *before* pressing
 * the shutter whether this scan will come back with a verdict or be queued. A
 * separate "Queue" tab beside a badge that already carries the number is the
 * same fact twice, so the badge is the link.
 */
const LINKS: NavLink[] = [
  {
    href: "/scan",
    label: "Scan",
    roles: ["officer", "supervisor", "admin"],
    primaryFor: ["officer"],
  },
  {
    href: "/dashboard",
    label: "Dashboard",
    roles: ["supervisor", "admin"],
    primaryFor: ["supervisor", "admin"],
  },
  {
    href: "/products",
    label: "Products",
    roles: ["officer", "supervisor", "admin"],
    primaryFor: ["officer", "supervisor", "admin"],
  },
  {
    href: "/search",
    label: "Search",
    // Section 11 scopes faceted search to officer and supervisor. An admin
    // keeps it reachable from the menu rather than losing it, since an admin
    // debugging a rulepack is exactly who needs to find the failing SKUs.
    roles: ["officer", "supervisor", "admin"],
    primaryFor: ["officer", "supervisor"],
  },
  { href: "/summary", label: "Violation summary", roles: ["supervisor", "admin"], primaryFor: [] },
  { href: "/rules", label: "Rulepack", roles: ["officer", "supervisor", "admin"], primaryFor: [] },
  { href: "/queue", label: "Offline outbox", roles: ["officer", "supervisor", "admin"], primaryFor: [] },
  { href: "/admin", label: "Administration", roles: ["admin"], primaryFor: [] },
];

export function Nav({ role }: { role: Role | null }) {
  const visible = role ? LINKS.filter((link) => link.roles.includes(role)) : [];
  const primary = role ? visible.filter((link) => link.primaryFor.includes(role)) : [];
  const secondary = role ? visible.filter((link) => !link.primaryFor.includes(role)) : [];

  return (
    // Sticky, because the connection badge and the display toggle are the two
    // controls an officer reaches for mid-task — the first when a scan queues,
    // the second when they step out of the shop into the sun — and a masthead
    // that has to be scrolled back to is a masthead they stop using.
    <header className="no-print sticky top-0 z-40 border-b border-border bg-surface/85 backdrop-blur-md">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-x-2 gap-y-1 px-4 py-2.5 md:flex-nowrap md:gap-x-4 md:px-6">
        <Link
          href={role ? "/scan" : "/login"}
          className="flex h-touch shrink-0 items-center rounded-md"
          aria-label="AKSHAR — home"
        >
          <BrandLockup size={26} compact />
        </Link>

        {/*
          MEASURED, NOT ASSUMED: three links do not fit beside the controls on a
          phone. At 390 px the mark, three labels, the tier pill, the display
          toggle and the account button come to roughly 430 px, and the links
          end up sitting underneath the pill. So on a phone they keep their own
          full-width band below the brand (`order-last w-full`) and go inline
          from `md` up.

          That is the same structure the eight-link version used, and the reason
          it is acceptable now is the count. Eight labels wrapped onto three
          lines and made the masthead 200 px tall — a third of the first screen
          of a phone-first tool spent on navigation. Three labels are one 44 px
          row, and the band scrolls sideways rather than wrapping so that stays
          true if a role is ever given a fourth.

          One `<nav>` element either way: rendering the list twice and hiding
          one would put two landmarks with the same name in the accessibility
          tree, and a screen-reader user would then have to work out which of
          the two "Main" navigations is the real one.
        */}
        {primary.length > 0 ? <NavLinks links={primary} /> : null}

        <div className="ml-auto flex shrink-0 items-center gap-1.5 md:gap-2">
          <ConnectionBadge />
          <ModeToggle />
          {role ? <AccountMenu role={role} links={secondary} /> : null}
        </div>
      </div>
    </header>
  );
}
