import { Alert } from "@/components/ui/alert";
import type { CaptureQuality as Quality, FrameInfo, Framing } from "@/lib/api/types";

/**
 * B1's answer, shown to the person still holding the camera.
 *
 * The whole value of a capture gate is the four seconds between "that photo is
 * no good" and the second attempt. A quality score filed into a record the
 * officer reads next week is a score that changed nothing, so this renders
 * immediately above the verdict and says what to do rather than what failed —
 * "tilt the pack away from the light", not "glare_ratio 0.43".
 *
 * **It is never shown for a usable frame.** A green "quality: fine" panel on
 * every scan is a panel people stop reading, and then they stop reading the
 * amber one too.
 */
export function CaptureQualityNotice({ quality }: { quality: Quality | null | undefined }) {
  if (!quality || quality.usable) return null;

  return (
    <Alert tone="review" title="This photograph cannot be measured">
      <ul className="flex list-disc flex-col gap-1 pl-5">
        {(quality.faults ?? []).map((fault) => (
          <li key={fault}>{ADVICE[fault] ?? fault}</li>
        ))}
      </ul>
      <p className="mt-2 text-sm">
        The photograph, its time and its location have been recorded anyway — nothing is lost by
        taking another. No measurement was taken from this frame, because a measurement from a
        frame like this one would be confident and wrong.
      </p>
    </Alert>
  );
}

/** Duplicated from `contracts/quality.py`, deliberately and with the same words.
 *
 *  The web app never imports Python and the API returns the advice on the
 *  response, so this is only the fallback for a fault a newer API knows about
 *  and this build does not — which is why the render above falls through to the
 *  raw fault name rather than showing nothing. */
const ADVICE: Record<string, string> = {
  blur: "Hold the camera still, or move slightly further back and tap to focus.",
  glare: "Tilt the pack away from the light, or shade it with your hand.",
  underexposed: "There is not enough light on the label. Move into better light.",
  overexposed: "The label is washed out. Move out of direct sun or reduce exposure.",
  resolution: "Move closer so the pack fills more of the frame.",
};

/**
 * The other half of B1, and the half that fires most often.
 *
 * `CaptureQualityNotice` above rejects a bad photograph. This one fires on a
 * *good* photograph of the wrong side of the pack — which, measured over the
 * 122-frame field corpus on 2026-09-10, is 40 of 122 frames pointed at the
 * brand face and another 28 pointed at the nutrition table. Every one of them
 * passes the gate above, because as photographs they are fine.
 *
 * Rendered as `review`, never as `fail`. Nothing here is a finding about the
 * package: it says we were looking the wrong way, and dressing that in the same
 * red as a missing MRP would put our own aim on an enforcement screen.
 */
export function FramingNotice({ framing }: { framing: Framing | null | undefined }) {
  if (!framing || framing.shows_declarations) return null;

  return (
    <Alert tone="review" title="No required declaration was found in this photograph">
      <p>{framing.reason ?? FRAMING_ADVICE[framing.fault ?? ""] ?? ""}</p>
      <p className="mt-2 text-sm">
        The photograph has been recorded with its time and its place. Nothing has been held
        against this package — a declaration we did not photograph is not a declaration the
        package is missing.
      </p>
    </Alert>
  );
}

/** Duplicated from `contracts/quality.py` for the same reason as `ADVICE`: the
 *  API returns the sentence on the response, and this is only the fallback for
 *  a fault a newer API knows about and this build does not. */
const FRAMING_ADVICE: Record<string, string> = {
  no_declaration_panel:
    "No declaration panel in this photograph. Turn the pack to the side printed with MRP and net weight, and photograph that side.",
  wrong_panel:
    "Text was read, but none of it is a required declaration — this is usually the nutrition table or the back-of-pack copy. Move to the block printed with MRP, net weight and the manufacturer's address.",
};

/**
 * What each photograph of the pack contributed, when the officer took several.
 *
 * The two notices above tell an officer to take a better photograph. This one
 * exists because the better answer is not to aim more carefully at all — it is
 * to walk round the pack and let the evidence be unioned. Section 8b: one pack,
 * several shots, verdicts computed once on the union.
 *
 * **The frames that contributed nothing are listed too, and that is the point.**
 * A strip that shows only what worked cannot say "your second shot was too
 * blurred", and that sentence is the one that gets a usable photograph taken
 * while the officer is still standing in front of the shelf.
 *
 * Never `fail`. Which of our photographs read is a fact about us, not a finding
 * about the package.
 */
export function FramesNotice({ frames }: { frames: FrameInfo[] | null | undefined }) {
  if (!frames || frames.length < 2) return null;

  const read = frames.filter((frame) => frame.read).length;
  const missed = frames.filter((frame) => !frame.read);

  return (
    <Alert
      tone={missed.length > 0 ? "review" : "neutral"}
      title={`${frames.length} photographs, read as one package`}
    >
      <p>
        {read} of {frames.length} showed something the rules could be applied to. The
        declarations from all of them were combined and judged once, so a declaration
        photographed from any side counts as declared.
      </p>
      {missed.length > 0 ? (
        <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 text-sm">
          {missed.map((frame) => (
            <li key={frame.frame}>
              Photograph {frame.frame + 1}: {frame.message || "nothing was read from it"}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="mt-2 text-sm">
        Every one of them is stored with its own digest in the record, including the ones
        that read nothing.
      </p>
    </Alert>
  );
}
