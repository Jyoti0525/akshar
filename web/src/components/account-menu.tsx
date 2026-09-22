"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { Role } from "@/lib/api/types";
import { Menu, MenuLabel, MenuSeparator, menuItemClass, useMenuClose } from "./ui/menu";
import type { NavLink } from "./nav-links";

/**
 * Everything the masthead used to show as a separate control, in one menu:
 * the signed-in role, the routes that are not a daily destination for it, and
 * sign-out.
 *
 * The role is displayed here rather than hidden because it explains the rest of
 * the screen. An officer who cannot find the dashboard should be able to see,
 * in one press, that this account is an officer account — otherwise a missing
 * link looks like a broken app. It is a label, not a control: the cookie it
 * comes from is readable and unsigned, and `require_role` in `api/deps` is what
 * actually decides anything.
 */

const ROLE_LABEL: Record<Role, string> = {
  officer: "Inspector",
  supervisor: "Supervisor",
  admin: "Administrator",
};

function SignOutItem() {
  const router = useRouter();
  const close = useMenuClose();

  return (
    <button
      type="button"
      role="menuitem"
      suppressHydrationWarning
      className={`${menuItemClass} text-fail-fg`}
      onClick={async () => {
        close();
        await fetch("/api/session", { method: "DELETE" });
        router.replace("/login");
        router.refresh();
      }}
    >
      Sign out
    </button>
  );
}

export function AccountMenu({ role, links }: { role: Role; links: NavLink[] }) {
  const pathname = usePathname();

  return (
    <Menu
      label="Account, and the rest of the sections"
      align="end"
      // The trigger is the role initial rather than a person icon: the masthead
      // already carries two glyph-only controls, and a third would be the point
      // at which they stop being distinguishable at a glance.
      trigger={
        <>
          <span
            aria-hidden="true"
            className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-xs font-bold text-accent-fg"
          >
            {ROLE_LABEL[role].charAt(0)}
          </span>
          <span className="hidden sm:inline">{ROLE_LABEL[role]}</span>
        </>
      }
    >
      <MenuLabel>Signed in as {ROLE_LABEL[role]}</MenuLabel>

      {links.length > 0 ? (
        <>
          <MenuSeparator />
          {links.map((link) => {
            const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
            return (
              <Link
                key={link.href}
                href={link.href}
                role="menuitem"
                aria-current={active ? "page" : undefined}
                className={menuItemClass}
              >
                {link.label}
              </Link>
            );
          })}
        </>
      ) : null}

      <MenuSeparator />
      <SignOutItem />
    </Menu>
  );
}
