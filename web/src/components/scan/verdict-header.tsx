import { Badge, toneForStatus } from "@/components/ui/badge";
import { millis, percent } from "@/lib/format";
import type { ScanResponse } from "@/lib/api/types";

/**
 * Section 11: *"Everything above the fold is the verdict."* And three details
 * there are called non-negotiable:
 *
 *   - the latency figure is displayed on every scan, because we make a speed
 *     claim and showing it makes the claim verifiable;
 *   - the scale tier badge and coverage percentage are always visible, because
 *     an officer must know how much the system understood before trusting it;
 *   - REVIEW renders amber, never red.
 *
 * All three are here, and none of them is behind a disclosure.
 */

/** The overall call, from the individual verdicts. FAIL wins over REVIEW wins
 *  over PASS: a pack with one definite failure is non-compliant whatever else is
 *  uncertain, and a pack with nothing decided is not a pass.
 *
 *  An *advisory* failure does not carry the headline. The unit-symbol and
 *  numeration rules ship `advisory: true` so that `250 ML` is not reported at
 *  the weight of a missing MRP; `rules.engine.is_compliant` excludes them and
 *  so does every violation count on the dashboard. This function did not, so
 *  the same scan could read "Non-compliant" here and sit outside the violation
 *  tables there. An advisory finding is still listed — it just does not decide
 *  the verdict. */
export function overallStatus(scan: ScanResponse): "FAIL" | "REVIEW" | "PASS" | "NO_DATA" {
  const verdicts = scan.verdicts ?? [];
  const statuses = verdicts.map((verdict) => verdict.status);
  if (verdicts.some((verdict) => verdict.status === "FAIL" && !verdict.advisory)) return "FAIL";
  // An advisory failure still owes someone a look, so it lands amber rather
  // than green. What it must not do is turn the headline red.
  if (statuses.includes("REVIEW") || statuses.includes("FAIL")) return "REVIEW";
  if (statuses.includes("PASS")) return "PASS";
  return "NO_DATA";
}

const HEADLINE: Record<string, string> = {
  FAIL: "Not compliant",
  REVIEW: "You need to decide",
  PASS: "Compliant",
  NO_DATA: "Could not read this photo",
};

/** One sentence under the headline saying what it means and what happens next.
 *
 * Added 2026-09-10. The badge alone was being read wrong in both directions: a
 * junior officer took amber for a failure, and a reader who had never seen the
 * system took "Nothing could be read" for a crash rather than for the record it
 * actually is. The headline is the verdict; this is the instruction. */
const HEADLINE_MEANING: Record<string, string> = {
  FAIL: "At least one rule is broken. The details are listed below and go into the notice.",
  REVIEW: "No rule is broken. Something could not be judged from a photograph alone — check it by hand and record what you decide.",
  PASS: "Every rule that applies to this package was checked and passed.",
  NO_DATA: "The photograph could not be read, so nothing was judged. The photo, its time and place are still saved. Take it again, closer.",
};

/** Section 5's ladder, in the words an officer needs rather than the tier code.
 *  The code is kept in the title attribute for anyone reading the record later. */
const TIER_MEANING: Record<string, string> = {
  L0: "online, full pipeline",
  L1: "offline, scanned on this device",
  L2: "no scale marker — ratio and placement rules only",
  L3: "text partly unread — verdicts cover what was read",
  L4: "nothing readable — evidence record only",
};

export function VerdictHeader({ scan, wallMs }: { scan: ScanResponse; wallMs?: number }) {
  const status = overallStatus(scan);
  const tone = toneForStatus(status);
  const geometry = scan.declarations?.geometry ?? null;
  const scaleTier = geometry?.scale_tier ?? null;

  return (
    <section aria-labelledby="verdict-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Badge tone={tone} className="px-3 py-2 text-xl">
          <span id="verdict-heading">{HEADLINE[status]}</span>
        </Badge>
        {scan.cache_hit ? (
          <Badge tone="neutral" glyph={false} title="This SKU was scanned before; no model ran.">
            Cache hit
          </Badge>
        ) : null}
      </div>

      <p className="max-w-prose text-base text-fg">{HEADLINE_MEANING[status] ?? ""}</p>

      <dl className="flex flex-wrap gap-x-6 gap-y-2 text-base">
        <Fact
          label="Latency"
          value={millis(scan.latency_ms)}
          hint={wallMs === undefined ? undefined : `${millis(wallMs)} on this device`}
        />
        <Fact
          label="Text read"
          value={percent(scan.coverage)}
          hint="share of the detected text regions the recogniser returned text for"
        />
        <Fact
          label="Scale"
          value={scaleTier ? `Tier ${scaleTier}` : "none"}
          hint={
            scaleTier
              ? geometry?.mm_per_px
                ? `${geometry.mm_per_px.toFixed(4)} mm/px ±${(geometry.mm_per_px_tolerance ?? 0).toFixed(4)}`
                : undefined
              : "no marker found — millimetre rules cannot be evaluated"
          }
        />
        <Fact
          label="Mode"
          value={scan.degradation_tier}
          hint={TIER_MEANING[scan.degradation_tier] ?? undefined}
        />
        <Fact label="Rulepack" value={scan.rulepack_version || "—"} />
      </dl>

      {scan.message ? <p className="text-base text-fg-muted">{scan.message}</p> : null}
    </section>
  );
}

function Fact({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="min-w-24">
      <dt className="text-xs uppercase tracking-wide text-fg-muted">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums" title={hint}>
        {value}
      </dd>
      {hint ? <p className="text-xs text-fg-muted">{hint}</p> : null}
    </div>
  );
}
