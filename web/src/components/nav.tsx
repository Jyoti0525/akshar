import Link from "next/link";
import type { Role } from "@/lib/api/types";
import { ModeToggle } from "./mode-toggle";
import { ConnectionBadge } from "./connection-badge";
import { SignOut } from "./sign-out";
import { BrandLockup } from "./brand";
import { NavLinks, type NavLink } from "./nav-links";

/**
 * Section 11's route table, as navigation, filtered by role.
 *
 * The role comes from a readable cookie and is used for *display only*. Every
 * real authorisation decision is made by `require_role` in `api/deps`, against
 * the signed token. Hiding a link an officer may not use is courtesy; it is not
 * a security control, and it is not treated as one here.
 *
 * ---------------------------------------------------------------------------
 * THE LAYOUT, AND WHY IT IS NOT A SINGLE WRAPPING ROW
 * ---------------------------------------------------------------------------
 * An admin sees eight links. At 390 px those wrapped onto three lines and the
 * masthead alone was 200 px tall — a third of the first screen of a tool whose
 * primary device is a phone held in a shop, spent on navigation, above the one
 * button the officer came to press.
 *
 * So the links get their own full-width row below the brand on a phone
 * (`order-last w-full`) and scroll sideways in it rather than wrapping, and they
 * sit inline on the same row from `md` up. One `<nav>` element either way: the
 * alternative — rendering the list twice and hiding one — puts two landmarks
 * with the same name in the accessibility tree, and a screen-reader user then
 * has to work out which of the two "Main" navigations is the real one.
 */
const LINKS: NavLink[] = [
  { href: "/scan", label: "Scan", roles: ["officer", "supervisor", "admin"] },
  { href: "/products", label: "Products", roles: ["officer", "supervisor", "admin"] },
  { href: "/search", label: "Search", roles: ["officer", "supervisor", "admin"] },
  { href: "/dashboard", label: "Dashboard", roles: ["supervisor", "admin"] },
  { href: "/summary", label: "Summary", roles: ["supervisor", "admin"] },
  { href: "/rules", label: "Rules", roles: ["officer", "supervisor", "admin"] },
  { href: "/queue", label: "Queue", roles: ["officer", "supervisor", "admin"] },
  { href: "/admin", label: "Admin", roles: ["admin"] },
];

export function Nav({ role }: { role: Role | null }) {
  const links = role ? LINKS.filter((link) => link.roles.includes(role)) : [];

  return (
    // Sticky, because the connection badge and the display toggle are the two
    // controls an officer reaches for mid-task — the first when a scan queues,
    // the second when they step out of the shop into the sun — and a masthead
    // that has to be scrolled back to is a masthead they stop using.
    <header className="no-print sticky top-0 z-40 border-b border-border bg-surface/95 backdrop-blur">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2 md:px-6">
        <Link
          href={role ? "/scan" : "/login"}
          className="flex h-touch items-center"
          aria-label="AKSHAR — home"
        >
          <BrandLockup size={26} compact />
        </Link>

        {/*
          `md:order-last` is load-bearing. The links are declared after this
          block so that on a phone they fall onto their own row beneath it; on a
          wide screen that same DOM order would put the connection badge and
          Sign out *before* the navigation, which is not where either belongs.
          Ordering the controls last from `md` up puts them back on the right.
        */}
        <div className="ml-auto flex items-center gap-2 md:order-last">
          <ConnectionBadge />
          <ModeToggle />
          {role ? <SignOut /> : null}
        </div>

        {links.length > 0 ? <NavLinks links={links} /> : null}
      </div>
    </header>
  );
}
