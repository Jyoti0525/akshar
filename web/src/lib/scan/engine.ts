"use client";

/**
 * What happens when an officer presses the shutter.
 *
 * Section 5's degradation ladder is the specification, and this function is
 * where the rung is chosen. It never fails, and it never returns nothing:
 *
 *   L0  online          the server pipeline runs and returns a full verdict
 *   L1  no network      the scan is queued; the officer keeps working
 *   L4  nothing read    a timestamped, located evidence record, queued for review
 *
 * **On-device inference is not wired yet, and this file says so rather than
 * pretending.** The vision blocks B1–B8 exist in Python under `vision/`, and the
 * browser port is a separate piece of work: the models are listed in
 * `src/lib/ocr/models.ts`, the execution path is probed in
 * `src/lib/ocr/runtime.ts`, and the moment a local pipeline exists it becomes a
 * third branch here with no change to any caller. What is *not* acceptable is a
 * local branch that returns a guess; section 8b's rule is `NO_DATA`, never a
 * fabricated value, and that rule does not relax because the code is running in
 * a browser.
 *
 * So today an offline scan produces an L4 record. Section 5 is explicit that
 * this is a real outcome and not a failure: *"Even in the worst case the officer
 * walks away with a timestamped evidence record. A tool that returns nothing
 * when it can't read is worse than a notebook."*
 */
import { apiFetch } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { sha256, uuidv7 } from "@/lib/offline/db";
import { enqueue } from "@/lib/offline/outbox";
import { runtimeProfile, runtimeTag } from "@/lib/ocr/runtime";
import type { GeoPoint, ScanResponse } from "@/lib/api/types";

export interface CaptureInput {
  image: Blob;
  /**
   * The second and later photographs of the SAME package — front, back, side.
   *
   * They become one scan: read separately, evidence unioned, rules evaluated
   * once on the union. That is the answer to the framing problem the corpus
   * exposed — 41 of 122 field photographs were sharp, well-lit pictures of the
   * brand face — because it replaces "aim at the right panel" with "walk round
   * the pack", and only one of those is a thing an officer will actually do.
   *
   * Several *packages* is the bulk endpoint, not this.
   */
  extraFrames?: Blob[];
  district?: string | null;
  category?: string | null;
  geo?: GeoPoint | null;
  /** Client-generated UUIDv7. Passed to the server so a retry after a dropped
   *  connection replays instead of creating a second inspection record. */
  scanId?: string;
  requestReport?: boolean;
}

export interface CaptureOutcome {
  scan: ScanResponse;
  /** True when the record is in the outbox rather than on the server. */
  queued: boolean;
  /** Wall-clock milliseconds this device spent, which is not the same number as
   *  `scan.latency_ms` (the server's own pipeline time) and is shown beside it
   *  rather than instead of it. Section 11: the latency figure is displayed on
   *  every scan because we make a speed claim and showing it makes the claim
   *  verifiable. */
  wallMs: number;
}

export async function capture(input: CaptureInput): Promise<CaptureOutcome> {
  const scanId = input.scanId ?? uuidv7();
  const started = performance.now();

  const frames = [input.image, ...(input.extraFrames ?? [])];

  const form = new FormData();
  // `append`, not `set`: the field is repeated once per photograph and the API
  // reads it as a list. One photograph produces exactly the request this sent
  // before multi-frame capture existed.
  frames.forEach((frame, index) => {
    form.append("image", frame, `${scanId}-${index}.jpg`);
  });
  form.set("scan_id", scanId);
  if (input.district) form.set("district", input.district);
  if (input.category) form.set("category", input.category);
  if (input.geo) {
    form.set("lat", String(input.geo.lat));
    form.set("lon", String(input.geo.lon));
  }
  form.set("captured_at", new Date().toISOString());
  if (input.requestReport) form.set("report", "true");

  try {
    const scan = await apiFetch<ScanResponse>("/scans", { method: "POST", form });
    return { scan, queued: false, wallMs: Math.round(performance.now() - started) };
  } catch (error) {
    if (!(error instanceof ApiError) || !error.isOffline) throw error;
    const scan = await queueOffline(scanId, input);
    return { scan, queued: true, wallMs: Math.round(performance.now() - started) };
  }
}

/** Tier L4: the photograph is held, the record is real, the verdict is owed.
 *
 *  **Every frame is held, not just the first.** Discarding the photographs an
 *  officer took because the signal dropped would lose evidence that cannot be
 *  retaken — the shop is behind them by the time they notice. */
async function queueOffline(scanId: string, input: CaptureInput): Promise<ScanResponse> {
  const profile = await runtimeProfile();
  const digest = await sha256(input.image);
  const capturedAt = new Date().toISOString();
  const extras = input.extraFrames ?? [];
  const held = await Promise.all(
    extras.map(async (frame, index) => ({
      id: `${scanId}:frame${index + 1}`,
      blob: frame,
      sha256: await sha256(frame),
      bytes: frame.size,
    })),
  );

  await enqueue(
    {
      id: scanId,
      state: "pending",
      captured_at: capturedAt,
      source: "photo",
      degradation_tier: "L4",
      // An empty set, not an invented one. The rules engine will run against
      // this on the server when it arrives, and every rule will return NO_DATA,
      // which is the truthful answer for a photograph nothing has read yet.
      declaration_set: { declarations: [], coverage: 0 },
      verdicts: [],
      coverage: 0,
      latency_ms: null,
      cache_hit: false,
      district: input.district ?? null,
      geo: input.geo ?? null,
      model_versions: { runtime: runtimeTag(profile) },
      rulepack_version: "",
      photo_state: "held",
      attempts: 0,
    },
    { id: scanId, blob: input.image, sha256: digest, bytes: input.image.size },
    held,
  );

  return {
    id: scanId,
    exit_path: "full",
    source: "photo",
    degradation_tier: "L4",
    coverage: 0,
    latency_ms: 0,
    cache_hit: false,
    declarations: null,
    verdicts: [],
    message:
      extras.length > 0
        ? `No network. All ${extras.length + 1} photographs are stored on this device with ` +
          "their time and location, and the scan is queued for a verdict when signal returns."
        : "No network. The photograph is stored on this device with its time and location, " +
          "and the scan is queued for a verdict when signal returns.",
    model_versions: { runtime: runtimeTag(profile) },
    rulepack_version: "",
    record_sha256: null,
    chain_seq: null,
    report_status: "not_requested",
    evidence: {
      stored: true,
      reason: "held on this device until the scan syncs",
      key: null,
      sha256: digest,
      tier: null,
      deferred: true,
      faces_blurred: 0,
      faces_on_package: 0,
    },
  } as ScanResponse;
}

/** The listing channel — section 2's seventh point, and the one most teams miss:
 *  *"Photo, bulk images, and listing text with no image at all."* */
export async function scanListing(
  text: string,
  options: { category?: string; district?: string } = {},
): Promise<ScanResponse> {
  return apiFetch<ScanResponse>("/scans/listing", {
    method: "POST",
    body: { text, category: options.category ?? null, district: options.district ?? null },
  });
}
