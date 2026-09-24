import type { Metadata } from "next";
import { Suspense } from "react";
import { LoginForm } from "./login-form";
import { opsHealth } from "@/lib/api/server";
import type { HealthResponse } from "@/lib/api/types";
import { BrandLockup } from "@/components/brand";

export const metadata: Metadata = { title: "Sign in" };

/**
 * The one page in the application that has to explain what it is.
 *
 * Everything past sign-in is used by someone who already knows; this is the
 * screen an inspector opens for the first time, and the three lines on the left
 * are the three things that separate this from a label-reading OCR demo. They
 * are claims the rest of the app then has to keep, which is why they are worded
 * as facts about behaviour rather than as features.
 */
const CLAIMS: { title: string; body: string }[] = [
  {
    title: "It measures, it does not guess",
    body: "Cap height in millimetres against Rule 7(2) Table I, recovered from a printed marker in the frame. Where there is no scale, the height rules return NO_DATA — never a verdict.",
  },
  {
    title: "Rules decide, models never",
    body: "A neural network extracts the text and its geometry. A versioned YAML rulepack issues the verdict, and every verdict carries the gazette clause it came from.",
  },
  {
    title: "It works with the radio off",
    body: "Scans are recorded on the device and sync when there is signal. Even when nothing is legible the photograph, its time and its place are kept.",
  },
];

/**
 * The seeded accounts, and what each one is for.
 *
 * Printed with the role rather than as three bare addresses, because the
 * navigation is role-scoped now: an officer does not see the dashboard at all,
 * and someone signing in as one and looking for it would reasonably conclude
 * the app was broken. `api/demo.py` owns these; if they change there they are
 * wrong here.
 */
const DEMO_ACCOUNTS: { email: string; role: string; sees: string }[] = [
  { email: "officer@akshar.demo", role: "Inspector", sees: "Capture, products, search" },
  { email: "supervisor@akshar.demo", role: "Supervisor", sees: "The dashboard and the review queue" },
  { email: "admin@akshar.demo", role: "Administrator", sees: "Users, roles and rulepack versions" },
];

const DEMO_PASSWORD = "akshar-demo";

/**
 * The demonstration panel, deliberately NOT part of the page's own render.
 *
 * It awaits `/healthz`, and that made it the slowest thing on the screen by two
 * orders of magnitude. Measured against an API that had stopped answering:
 * time-to-first-byte 2589 ms of a 2772 ms load, with the response body itself
 * taking 3 ms and every script chunk about 115 ms. The browser was idle for
 * 2.5 seconds waiting for the server to finish a request the page did not need
 * in order to be useful.
 *
 * The 2.5 s is the `HEALTH_TIMEOUT_MS` deadline in `lib/api/server.ts` doing its
 * job — before it, the same call blocked on undici's multi-minute default. But
 * capping a wait is the wrong fix for a wait that should not be on the critical
 * path at all. An optional panel beside a sign-in form has no business deciding
 * when the sign-in form is allowed to appear.
 *
 * Wrapped in `<Suspense>` by the caller, so the page streams its shell and its
 * form immediately and this arrives when the API answers — or never, if it
 * does not. Nothing above it waits.
 */
async function DemonstrationPanel() {
  // The panel prints working credentials, so what turns it on matters. Three
  // gates, none of which can fire on a real deployment.
  //
  // 1. `dev` — `next dev`. This is the one that serves the common case. The
  //    API's own report is not enough on its own: both "DEMONSTRATION" lines
  //    require the in-memory backend, and the ordinary local stack runs against
  //    Postgres, where the API correctly says nothing about demonstrations. So
  //    the panel that exists to help someone sign in was invisible on exactly
  //    the setup most people run. A production build sets NODE_ENV=production,
  //    so this gate cannot follow the app into one.
  //
  // 2. `demo` — the API vouching for itself. The gate that works for a deployed
  //    demonstration instance, where NODE_ENV *is* production. It requires the
  //    in-memory backend, which `api/main.py` refuses to boot on in production.
  //
  // 3. `forced` — `AKSHAR_DEMO_CREDENTIALS=1`, a deliberate act by whoever
  //    started this web process. The escape hatch for a deployed demonstration
  //    whose API is not answering yet, since a `null` health report is
  //    indistinguishable from "not a demo".
  const health = await opsHealth<HealthResponse>();
  const detail = health?.detail ?? [];
  const apiAnswered = health !== null;
  const dev = process.env.NODE_ENV !== "production";
  const demo = detail.some((line) => line.startsWith("DEMONSTRATION"));
  const seeded = detail.some((line) => line.startsWith("DEMONSTRATION DATA"));
  const forced = process.env.AKSHAR_DEMO_CREDENTIALS === "1";
  const showCredentials = dev || demo || forced;

  if (showCredentials) {
    return (
      <div className="rounded-lg border border-review bg-review-bg p-4 text-sm text-review-fg">
        <p className="font-semibold">Demonstration instance</p>
        <p className="mt-1">
          {!apiAnswered
            ? "The API is not answering, so signing in will fail until it is up. These are the accounts to use once it is."
            : !demo
              ? dev
                ? "These accounts exist only if the database has been seeded with them — see api/demo.py. Shown because this is a development build."
                : // `forced` on a production build: a hosted demonstration
                  // against a real database. The development sentence above
                  // was the only one this branch had, and it told a reviewer on
                  // the public link that they were looking at a dev build.
                  "A demonstration deployment for review. Each account sees the application as that role would; the verdicts come from the real rulepack."
              : seeded
                ? "This API was started with a synthetic shelf. The packets are invented; the verdicts are not — every one comes from the rulepack."
                : "This API is empty and holds nothing in a database. Scan or upload a photograph to put the first record in it."}
        </p>

        {/*
          A list, not a table. Three rows of three columns is a table on a
          laptop and an unreadable squeeze at 390 px, and this is the one
          screen guaranteed to be opened on an unfamiliar device.
        */}
        <ul className="mt-3 flex flex-col gap-2.5">
          {DEMO_ACCOUNTS.map((account) => (
            <li key={account.email} className="border-l-2 border-review/50 pl-3">
              <p className="numeric font-semibold break-all">{account.email}</p>
              <p className="mt-0.5 text-xs">
                {account.role} · {account.sees}
              </p>
            </li>
          ))}
        </ul>

        <p className="mt-3">
          Password <span className="numeric font-semibold">{DEMO_PASSWORD}</span> for all three.
        </p>
      </div>
    );
  }

  if (!apiAnswered) {
    // Not a credentials panel — an explanation. Without this the page is a
    // sign-in form that rejects every attempt for no stated reason, and the
    // first guess is always that the password is wrong.
    return (
      <div className="rounded-lg border border-review bg-review-bg p-4 text-sm text-review-fg">
        <p className="font-semibold">The API is not answering</p>
        <p className="mt-1">
          Sign-in will fail until it is. Nothing is wrong with your credentials.
        </p>
      </div>
    );
  }

  return null;
}

export default function LoginPage() {


  return (
    <div className="mx-auto grid w-full max-w-5xl gap-10 py-8 lg:grid-cols-[1.1fr_minmax(20rem,1fr)] lg:gap-16 lg:py-16">
      <section className="flex flex-col gap-6">
        <div>
          {/* The one screen where the mark gets to be the full logo — ring,
              leaf and caliper lens. Everywhere else it is 26 px in a masthead,
              where the lens is three grey pixels. */}
          <BrandLockup size={56} detail tagline />
          <p className="mt-7 text-sm font-medium tracking-wide text-accent uppercase">
            Legal Metrology (Packaged Commodities) Rules, 2011
          </p>
          <h1 className="mt-2 text-3xl font-semibold text-balance sm:text-4xl">
            Is the declaration on this packet large enough to be lawful?
          </h1>
          <p className="mt-3 max-w-prose text-base text-fg-muted">
            Existing tools read font size out of artwork files before printing, for brands. AKSHAR
            measures it in a photograph after the product reaches the shelf, for enforcement.
          </p>
        </div>

        <dl className="flex flex-col gap-4">
          {CLAIMS.map((claim) => (
            <div key={claim.title} className="border-l-[3px] border-accent/35 pl-4">
              <dt className="font-semibold text-fg">{claim.title}</dt>
              <dd className="mt-1 max-w-prose text-sm text-fg-muted">{claim.body}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="flex flex-col gap-4">
        <div>
          <h2 className="text-2xl font-semibold">Sign in</h2>
          <p className="mt-1 text-base text-fg-muted">
            Officers, supervisors and controllers. Every action is recorded against your name.
          </p>
        </div>
        <Suspense fallback={null}>
          <LoginForm />
        </Suspense>

        {/*
          Streamed, not awaited. See `DemonstrationPanel` — this call goes to
          the API, and an API that has stopped answering must not decide when
          the sign-in form is allowed to render. `fallback={null}` because the
          panel is supplementary: there is nothing useful to show in its place
          and a skeleton would only promise something that may never arrive.
        */}
        <Suspense fallback={null}>
          <DemonstrationPanel />
        </Suspense>
      </section>
    </div>
  );
}
