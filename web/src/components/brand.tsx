/**
 * The AKSHAR mark, drawn rather than fetched.
 *
 * An `<img>` here would be a network request in the masthead of every page, a
 * second one in the offline shell, and a blank rectangle in the four seconds
 * before it lands. Inline SVG costs about 900 bytes in the HTML that was already
 * being sent, scales to any size without a second asset, and inherits the
 * palette — the daylight mode flattens the gradient to one high-contrast colour,
 * which a PNG could not do.
 *
 * The gradient lives in `<BrandDefs />`, rendered exactly once in the root
 * layout. Two `<linearGradient id="...">` on one page is a duplicate id and the
 * second one is ignored, so the definition is hoisted instead of repeated.
 *
 * `--brand-from` / `--brand-to` are identity colours and are used nowhere else.
 * See the long note in `globals.css`: the brand is wine-to-orange and FAIL is
 * scarlet, and the only thing keeping them legible as different signals is that
 * the gradient never reports a fact.
 */

import { cn } from "@/lib/cn";

const GRADIENT = "akshar-brand-gradient";

/** The gradient every mark on the page points at. Render once, in the layout. */
export function BrandDefs() {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      // Not `display: none`. A gradient inside a `display: none` SVG has a long
      // history of failing to resolve from another fragment; a zero-sized,
      // clipped container works everywhere and is just as invisible.
      style={{ position: "absolute", width: 0, height: 0, overflow: "hidden" }}
    >
      <defs>
        <linearGradient id={GRADIENT} x1="0" y1="1" x2="1" y2="0">
          <stop offset="0%" stopColor="var(--brand-from)" />
          <stop offset="100%" stopColor="var(--brand-to)" />
        </linearGradient>
      </defs>
    </svg>
  );
}

/**
 * The letterform: an A whose apex, legs and bar are the only strokes that
 * survive at 20 px. `detail` adds the leaf and the caliper lens from the full
 * logo, which are illegible below about 40 px and are therefore opt-in rather
 * than something the masthead pays for and nobody can see.
 */
export function AksharMark({
  size = 28,
  detail = false,
  className,
}: {
  size?: number;
  detail?: boolean;
  className?: string;
}) {
  const stroke = `url(#${GRADIENT})`;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      <circle cx="32" cy="32" r="30.5" stroke={stroke} strokeWidth="1.75" opacity="0.4" />

      {detail ? (
        /* The leaf. It reads as growth in the logo and as the left serif of the
           A at this size, which is why it is drawn under the letter rather than
           beside it. */
        <path
          d="M15 51 C13.5 37 19 25 31 18.5 C28 33.5 23.5 44.5 15 51 Z"
          fill={stroke}
          opacity="0.85"
        />
      ) : null}

      <path
        d="M14 50 L32 14 L50 50"
        stroke={stroke}
        strokeWidth="7.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M22.5 36 H41.5" stroke={stroke} strokeWidth="6.5" strokeLinecap="round" />

      {detail ? (
        <g>
          {/* The lens, and inside it the thing this whole system does: a cap
              height caught between two rules.

              Kept to r=11 and pushed down-right on purpose. At r=14.5 centred
              on the crossbar it covered the whole right half of the letter and
              the mark stopped reading as an A at all — which is the one thing
              it has to do. */}
          <circle cx="46" cy="36" r="11" fill="var(--surface)" opacity="0.94" />
          <circle cx="46" cy="36" r="11" stroke={stroke} strokeWidth="2.75" />
          <path d="M54 44 L60.5 51" stroke={stroke} strokeWidth="4" strokeLinecap="round" />
          <path
            d="M39 30.5 H53 M39 41.5 H53"
            stroke={stroke}
            strokeWidth="1.4"
            strokeDasharray="2.5 2"
          />
          <path d="M50.5 30.5 V41.5" stroke={stroke} strokeWidth="1.4" />
          <path
            d="M48.8 32.3 L50.5 30.5 L52.2 32.3 M48.8 39.7 L50.5 41.5 L52.2 39.7"
            stroke={stroke}
            strokeWidth="1.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>
      ) : null}
    </svg>
  );
}

/**
 * Mark plus wordmark. `tagline` is for the sign-in screen and nothing else — in
 * the masthead it would be four words nobody reads fifty times a day.
 */
export function BrandLockup({
  size = 28,
  detail = false,
  tagline = false,
  compact = false,
}: {
  size?: number;
  detail?: boolean;
  tagline?: boolean;
  /** Drop the word below `sm`, keeping only the mark.
   *
   *  Worth about 90 px, which is the difference between the masthead fitting on
   *  one row on a 360 px phone and spilling the connection badge onto a second.
   *  The mark alone is enough identity on a screen the officer has already
   *  signed into, and the link's `aria-label` carries the name regardless. */
  compact?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <AksharMark size={size} detail={detail} />
      <span className={cn("flex-col leading-none", compact ? "hidden sm:flex" : "flex")}>
        <span
          className="brand-wordmark font-semibold tracking-[0.14em]"
          style={{ fontSize: size * 0.62 }}
        >
          AKSHAR
        </span>
        {tagline ? (
          <span className="mt-1 text-xs tracking-[0.18em] text-fg-muted uppercase">
            Scan · Measure · Verify
          </span>
        ) : null}
      </span>
    </span>
  );
}
