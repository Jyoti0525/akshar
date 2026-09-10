import type { Metadata, Viewport } from "next";
import { cookies } from "next/headers";
import "./globals.css";
import { Providers } from "@/components/providers";
import { Nav } from "@/components/nav";
import { BrandDefs } from "@/components/brand";
import { ROLE_COOKIE } from "@/lib/api/session";
import type { Role } from "@/lib/api/types";

export const metadata: Metadata = {
  title: { default: "AKSHAR", template: "%s · AKSHAR" },
  description:
    "Legal Metrology label compliance from a photograph — measured in millimetres, offline, for enforcement.",
  applicationName: "AKSHAR",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "AKSHAR", statusBarStyle: "default" },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Section 11 asks for a 16 px floor and 4.5:1 contrast. Pinching to zoom is
  // part of the same commitment, so `maximumScale` is deliberately not set: an
  // officer must be able to enlarge a measurement they are about to write into
  // a notice.
  //
  // The two `--bg` values. The browser paints the address bar and the
  // task-switcher card with this, so a stale value here is a white seam above a
  // cream masthead on every phone that installs the PWA.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fdfaf7" },
    { media: "(prefers-color-scheme: dark)", color: "#1a0f13" },
  ],
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const jar = await cookies();
  const role = (jar.get(ROLE_COOKIE)?.value ?? null) as Role | null;

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/*
          The display mode is read before first paint. Deferring it to an effect
          would flash the wrong palette, and a white flash is a genuine problem
          for the daylight mode this exists to serve — it is used by someone
          standing in the sun who has already told us the default is unreadable.
        */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var m=localStorage.getItem("akshar-mode");if(m)document.documentElement.setAttribute("data-mode",m);}catch(e){}`,
          }}
        />
      </head>
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <BrandDefs />
        <Providers>
          <div className="flex min-h-dvh flex-col">
            <Nav role={role} />
            <main id="main" className="flex-1 px-4 py-6 md:px-6">
              {children}
            </main>
            <footer className="no-print border-t border-border px-4 py-4 text-xs text-fg-muted md:px-6">
              AKSHAR · verdicts cite the gazette clause that produced them ·
              rules are data, not code
            </footer>
          </div>
        </Providers>
      </body>
    </html>
  );
}
