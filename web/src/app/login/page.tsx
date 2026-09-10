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

export default async function LoginPage() {
  // Only shown when the API reports demonstration accounts or a demonstration
  // shelf. It is impossible for this panel to appear against a real deployment:
  // both lines require the in-memory backend, and `api/main.py` refuses to boot
  // on that backend in production.
  const health = await opsHealth<HealthResponse>();
  const detail = health?.detail ?? [];
  const demo = detail.some((line) => line.startsWith("DEMONSTRATION"));
  const seeded = detail.some((line) => line.startsWith("DEMONSTRATION DATA"));

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

        {demo ? (
          <div className="rounded-lg border border-review bg-review-bg p-4 text-sm text-review-fg">
            <p className="font-medium">Demonstration instance</p>
            <p className="mt-1">
              {seeded
                ? "This API was started with a synthetic shelf. The packets are invented; the verdicts are not — every one comes from the rulepack."
                : "This API is empty and holds nothing in a database. Scan or upload a photograph to put the first record in it."}
            </p>
            <ul className="mt-2 flex flex-col gap-0.5 font-mono text-sm">
              <li>officer@akshar.demo</li>
              <li>supervisor@akshar.demo</li>
              <li>admin@akshar.demo</li>
            </ul>
            <p className="mt-2">
              Password <span className="font-mono">akshar-demo</span> for all three.
            </p>
          </div>
        ) : null}
      </section>
    </div>
  );
}
