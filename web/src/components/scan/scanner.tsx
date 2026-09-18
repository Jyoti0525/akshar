"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { capture, type CaptureOutcome } from "@/lib/scan/engine";
import { useCamera } from "@/lib/scan/use-camera";
import { runtimeProfile, type RuntimeProfile } from "@/lib/ocr/runtime";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/alert";
import { Card } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/field";
import { VerdictHeader } from "./verdict-header";
import { CaptureQualityNotice, FramesNotice, FramingNotice } from "./capture-quality";
import { RuleRows } from "./rule-rows";
import { Overlay } from "./overlay";
import type { GeoPoint } from "@/lib/api/types";

/**
 * The screen an officer uses fifty times a day.
 *
 * Two ways in, because both are real: the live camera for a pack in hand, and a
 * file for a photograph already taken. The camera is not required — a laptop in
 * a district office has none, and the same officer reviews the same photographs
 * there in the evening. Everything about opening it, and every way that fails,
 * lives in `useCamera`; this file is the screen.
 *
 * Location is requested but never insisted on. Section 18: the coordinate is
 * reduced server-side before storage, and a scan without one is still a scan.
 * Blocking capture on a GPS fix indoors would be the fastest way to make the
 * tool useless in a warehouse.
 */
const CATEGORIES = [
  "",
  "food",
  "cosmetics",
  "cement",
  "electronics",
  "footwear",
  "medical devices",
  "household",
  "other",
];

export function Scanner() {
  // Destructured, not held as one object. React Compiler treats any object that
  // holds a ref as ref-tainted, so reading `state` off it in the JSX is reported
  // as "cannot access refs during render" even though `state` is ordinary state.
  // Pulling the fields apart at the call site gives the ref its own binding and
  // leaves the rest as the plain values they are.
  const {
    videoRef,
    state: cameraState,
    error: cameraError,
    start: startCamera,
    stop: stopCamera,
    grab,
    live,
  } = useCamera();

  const [category, setCategory] = useState("");
  const [district, setDistrict] = useState("");
  const [geo, setGeo] = useState<GeoPoint | null>(null);
  const [profile, setProfile] = useState<RuntimeProfile | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CaptureOutcome | null>(null);
  const [preview, setPreview] = useState<string | null>(null);

  /**
   * Photographs of THIS pack taken so far and not yet sent.
   *
   * The corpus said the limiting factor is what is in the frame, not how many
   * pixels it has: 40 of 122 field photographs were sharp, well-lit pictures of
   * the brand face, with no statutory declaration anywhere in them. Telling the
   * officer to aim better is a fix that depends on the officer, and an officer
   * in a shop with a queue behind them will not do it. Letting them walk round
   * the pack and sending three photographs as one scan does not.
   *
   * "Capture" still sends immediately, because that is the fifty-times-a-day
   * path and it must not get slower. Adding a side is a deliberate second act.
   */
  const [tray, setTray] = useState<Blob[]>([]);

  useEffect(() => {
    void runtimeProfile().then(setProfile);
    navigator.geolocation?.getCurrentPosition(
      (position) => setGeo({ lat: position.coords.latitude, lon: position.coords.longitude }),
      () => setGeo(null),
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 120_000 },
    );
  }, []);

  const submit = useCallback(
    async (blobs: Blob[]) => {
      const [first, ...rest] = blobs;
      if (!first) return;
      setBusy(true);
      setError(null);
      setResult(null);
      // The overlay draws declaration boxes in ONE photograph's coordinates, so
      // it previews the first frame. `Overlay` is given the union, and the
      // union knows which frame each box came from.
      setPreview((previous) => {
        if (previous) URL.revokeObjectURL(previous);
        return URL.createObjectURL(first);
      });
      try {
        const outcome = await capture({
          image: first,
          extraFrames: rest,
          category: category || null,
          district: district || null,
          geo,
        });
        setResult(outcome);
        setTray([]);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setBusy(false);
      }
    },
    [category, district, geo],
  );

  const shoot = useCallback(async () => {
    const blob = await grab();
    if (blob) await submit([...tray, blob]);
  }, [grab, submit, tray]);

  const addSide = useCallback(async () => {
    const blob = await grab();
    if (blob) setTray((held) => [...held, blob]);
  }, [grab]);

  const showViewfinder = cameraState === "starting" || cameraState === "on";

  return (
    <div className="flex flex-col gap-6">
      {profile?.warning ? <Alert tone="review">{profile.warning}</Alert> : null}

      <Card className="flex flex-col gap-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="category">Category</Label>
            <Select
              id="category"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
            >
              {CATEGORIES.map((value) => (
                <option key={value} value={value}>
                  {value === "" ? "Not stated" : value}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="district">District</Label>
            <Input
              id="district"
              value={district}
              placeholder="Defaults to your posting"
              onChange={(event) => setDistrict(event.target.value)}
            />
          </div>
        </div>

        {showViewfinder ? (
          <div className="flex flex-col gap-3">
            {/*
              The element is mounted for the whole of `starting` as well as
              `on`, because `useCamera` attaches the stream in an effect and an
              effect cannot attach to an element that has not rendered. That
              ordering is the bug this component used to have.
            */}
            <div className="relative overflow-hidden rounded-lg border border-border bg-black">
              <video
                ref={videoRef}
                playsInline
                autoPlay
                muted
                className="w-full"
                aria-label="Camera viewfinder"
              />

              {live ? (
                /*
                  The framing guide. Section 18b measured 4.9-11.7 px/mm on the
                  ruler corpus against a premise of about 24, and the whole of
                  that gap is officers photographing the marker card rather than
                  the declaration. Two lines on the glass are the cheapest place
                  to fix it — cheaper than any amount of documentation nobody
                  reads while holding a packet.
                */
                <div
                  aria-hidden="true"
                  className="pointer-events-none absolute inset-0 flex items-center justify-center p-6"
                >
                  <div className="h-full w-full rounded border-2 border-dashed border-white/70" />
                  <p className="absolute bottom-2 rounded bg-black/65 px-2 py-1 text-xs text-white">
                    {tray.length > 0
                      ? `${tray.length} side${tray.length > 1 ? "s" : ""} held. Turn the pack and add another, or capture to read them together.`
                      : "Fill this frame with the declaration panel — or add each side in turn and let them be read as one pack."}
                  </p>
                </div>
              ) : (
                <p className="absolute inset-0 flex items-center justify-center text-base text-white">
                  Waiting for the camera…
                </p>
              )}
            </div>

            <div className="flex flex-wrap gap-2">
              <Button onClick={shoot} disabled={busy || !live}>
                {busy
                  ? "Reading…"
                  : tray.length > 0
                    ? `Capture and read ${tray.length + 1} photographs`
                    : "Capture"}
              </Button>
              <Button variant="outline" onClick={addSide} disabled={busy || !live}>
                Add another side
              </Button>
              {tray.length > 0 ? (
                <Button variant="outline" onClick={() => setTray([])} disabled={busy}>
                  Discard {tray.length} held
                </Button>
              ) : null}
              <Button variant="outline" onClick={stopCamera}>
                Stop camera
              </Button>
            </div>

            {tray.length > 0 ? (
              <p className="text-sm text-fg-muted">
                {tray.length} photograph{tray.length > 1 ? "s" : ""} of this pack held. They
                are read separately and judged once, together — a declaration on any side
                counts as declared.
              </p>
            ) : null}
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => void startCamera()} disabled={busy}>
              Use camera
            </Button>
            <label className="inline-flex h-touch cursor-pointer items-center rounded-md border border-border px-4 text-base hover:bg-surface-2">
              Upload photographs
              <input
                type="file"
                accept="image/*"
                multiple
                className="sr-only"
                onChange={(event) => {
                  // Several files here means several photographs of ONE pack.
                  // A folder of different packs is the bulk upload, which is a
                  // separate screen with a separate endpoint behind it.
                  const files = Array.from(event.target.files ?? []);
                  if (files.length > 0) void submit(files);
                }}
              />
            </label>
            <span className="text-sm text-fg-muted">
              {geo ? "Location captured" : "No location — the scan still records"}
            </span>
          </div>
        )}

        {cameraError ? (
          <Alert tone="review" title="The camera did not open">
            {cameraError}
          </Alert>
        ) : null}
        {error ? <Alert tone="fail">{error}</Alert> : null}
      </Card>

      {result ? (
        <div className="flex flex-col gap-4">
          <CaptureQualityNotice quality={result.scan.capture_quality} />
          <FramesNotice frames={result.scan.frames} />
          {/*
            Suppressed once the pack was photographed from several sides: the
            framing hint tells an officer to turn the pack over, and they
            already did. What is left to say is which shot read, and
            `FramesNotice` above says it.
          */}
          {(result.scan.frames?.length ?? 0) > 1 ? null : (
            <FramingNotice framing={result.scan.framing} />
          )}
          <VerdictHeader scan={result.scan} wallMs={result.wallMs} />
          {result.queued ? (
            <Alert tone="review" title="Queued">
              This scan is in the outbox on this device and will sync when signal returns. The
              photograph, its time and its location are already recorded.
            </Alert>
          ) : null}
          {preview ? (
            <Overlay
              src={preview}
              declarations={result.scan.declarations}
              verdicts={result.scan.verdicts}
            />
          ) : null}
          <RuleRows verdicts={result.scan.verdicts} />
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline">
              <Link href={`/scan/${result.scan.id}`}>Open the full record</Link>
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
