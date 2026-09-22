"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { all, counts, discardPhoto, drain, heldPhotos, warmSkuCache } from "@/lib/offline/outbox";
import { bundleBudgetBytes, bundleStatus, MODEL_BUNDLE, type BundleStatus } from "@/lib/ocr/models";
import { runtimeProfile, type RuntimeProfile } from "@/lib/ocr/runtime";
import { Button } from "@/components/ui/button";
import { Card, CardTitle, CardHint } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Table, THead, TR, TH, TD, Empty } from "@/components/ui/table";
import { bytes, count, dateTime } from "@/lib/format";
import type { OutboxScan } from "@/lib/offline/db";

const CACHE_BUDGET = 60 * 1024 * 1024; // Section 5: "Cached bundle < 60 MB".

export function OutboxPanel() {
  const [scans, setScans] = useState<OutboxScan[]>([]);
  const [tally, setTally] = useState<Record<string, number>>({});
  const [photos, setPhotos] = useState({ count: 0, bytes: 0 });
  const [bundle, setBundle] = useState<BundleStatus | null>(null);
  const [profile, setProfile] = useState<RuntimeProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [updateReady, setUpdateReady] = useState(false);

  const refresh = useCallback(async () => {
    // One round trip's worth of awaits rather than three. These are three
    // independent reads of the same IndexedDB; sequencing them only made the
    // panel repaint three times.
    const [rows, tally, held] = await Promise.all([all(), counts(), heldPhotos()]);
    setScans(rows);
    setTally(tally);
    setPhotos(held);
  }, []);

  useEffect(() => {
    // `live` guards every write below. Without it a drain that resolves after
    // the officer has navigated away sets state on an unmounted component —
    // harmless today, and exactly the kind of thing that becomes a leak once
    // the panel is mounted somewhere that unmounts often.
    let live = true;

    void (async () => {
      const [rows, tally, held, bundleStatusResult, runtimeProfileResult] = await Promise.all([
        all(),
        counts(),
        heldPhotos(),
        bundleStatus(),
        runtimeProfile(),
      ]);
      if (!live) return;
      setScans(rows);
      setTally(tally);
      setPhotos(held);
      setBundle(bundleStatusResult);
      setProfile(runtimeProfileResult);
    })();

    const onUpdate = () => setUpdateReady(true);
    window.addEventListener("akshar:update-ready", onUpdate);
    return () => {
      live = false;
      window.removeEventListener("akshar:update-ready", onUpdate);
    };
  }, []);

  const syncNow = async () => {
    setBusy(true);
    setNote(null);
    try {
      const result = await drain();
      setNote(
        result.offline
          ? "Still offline. Nothing was sent, and nothing was lost."
          : `${count(result.created)} recorded, ${count(result.duplicates)} already on the server.` +
            (result.error ? ` ${result.error}` : ""),
      );
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const warm = async () => {
    setBusy(true);
    setNote(null);
    try {
      const n = await warmSkuCache();
      setNote(`${count(n)} SKUs cached for offline lookup.`);
    } catch (error) {
      setNote(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const pending = (tally.pending ?? 0) + (tally.sending ?? 0);

  return (
    <div className="flex flex-col gap-5">
      {updateReady ? (
        <Alert tone="review" title="A new version is ready">
          It will be applied the next time every AKSHAR tab is closed and reopened. Nothing is
          swapped underneath a scan in progress.
        </Alert>
      ) : null}

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>Outbox</CardTitle>
            <CardHint>
              {pending === 0
                ? "Nothing waiting. Every scan on this device is on the server."
                : `${count(pending)} scan${pending === 1 ? "" : "s"} waiting to sync.`}
            </CardHint>
          </div>
          <div className="flex gap-2">
            <Button onClick={syncNow} disabled={busy}>
              {busy ? "Working…" : "Sync now"}
            </Button>
            <Button variant="outline" onClick={warm} disabled={busy}>
              Warm SKU cache
            </Button>
          </div>
        </div>

        {note ? <Alert className="mt-3">{note}</Alert> : null}

        <div className="mt-3">
          <Table>
            <THead>
              <TR>
                <TH>State</TH>
                <TH>Captured</TH>
                <TH>Tier</TH>
                <TH>District</TH>
                <TH>Photograph</TH>
                <TH>Chain</TH>
              </TR>
            </THead>
            <tbody>
              {scans.length === 0 ? (
                <Empty colSpan={6}>Nothing has been scanned on this device.</Empty>
              ) : (
                scans.map((scan) => (
                  <TR key={scan.id}>
                    <TD>
                      <Badge
                        tone={
                          scan.state === "synced"
                            ? "pass"
                            : scan.state === "failed"
                              ? "fail"
                              : "review"
                        }
                      >
                        {scan.state}
                      </Badge>
                      {scan.last_error ? (
                        <p className="mt-1 text-sm text-fg-muted">{scan.last_error}</p>
                      ) : null}
                    </TD>
                    <TD>
                      {scan.state === "synced" ? (
                        <Link href={`/scan/${scan.id}`} className="underline">
                          {dateTime(scan.captured_at)}
                        </Link>
                      ) : (
                        dateTime(scan.captured_at)
                      )}
                    </TD>
                    <TD>{scan.degradation_tier}</TD>
                    <TD>{scan.district ?? "—"}</TD>
                    <TD>
                      {scan.photo_state === "held" ? (
                        // Extensions stamp `fdprocessedid` here before hydration; see ui/button.tsx.
                        <button
                          suppressHydrationWarning
                          type="button"
                          className="underline"
                          onClick={async () => {
                            await discardPhoto(scan.id);
                            await refresh();
                          }}
                        >
                          held — discard
                        </button>
                      ) : (
                        <span className="text-fg-muted">none</span>
                      )}
                    </TD>
                    <TD className="font-mono text-sm">
                      {scan.chain_seq === undefined ? "—" : `#${scan.chain_seq}`}
                    </TD>
                  </TR>
                ))
              )}
            </tbody>
          </Table>
        </div>

        {photos.count > 0 ? (
          <Alert tone="review" className="mt-3" title="Photographs held on this device">
            {count(photos.count)} photograph{photos.count === 1 ? "" : "s"}, {bytes(photos.bytes)}.
            The API has no route that attaches a photograph to a scan record after the record is
            sealed, and section 6 hashes that record with its image fields inside — so filling them
            in later would break the evidence chain at that row. The verdicts have synced; the
            images stay here until that endpoint exists.
          </Alert>
        ) : null}
      </Card>

      <Card>
        <CardTitle>On-device models</CardTitle>
        <CardHint>
          Section 5 budgets about 50 MB across the bundle and caps the cached bundle at 60 MB.
        </CardHint>
        {bundle ? (
          <>
            <p className="mt-2 text-base">
              {bundle.complete
                ? `All ${MODEL_BUNDLE.length} assets present — ${bytes(bundle.bytes)}.`
                : `${bundle.present.length} of ${MODEL_BUNDLE.length} present. Missing: ${bundle.missing.join(", ")}.`}{" "}
              <span className="text-fg-muted">
                Budget {bytes(bundleBudgetBytes())}, cap {bytes(CACHE_BUDGET)}.
              </span>
            </p>
            <ul className="mt-2 flex flex-col gap-1 text-sm">
              {MODEL_BUNDLE.map((asset) => (
                <li key={asset.key} className="flex flex-wrap gap-2">
                  <Badge tone={bundle.present.includes(asset.key) ? "pass" : "nodata"}>
                    {bundle.present.includes(asset.key) ? "cached" : "absent"}
                  </Badge>
                  <span className="font-mono">{asset.file}</span>
                  <span className="text-fg-muted">{asset.purpose}</span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="mt-2 text-base text-fg-muted">Checking…</p>
        )}
        <Alert tone="neutral" className="mt-3">
          On-device inference is not wired yet: the vision blocks run on the server. Offline scans
          are recorded at tier L4 — the photograph, its time and its location — and get a verdict
          when they sync. Section 8b&apos;s rule is <code>NO_DATA</code>, never a guess, and that
          does not relax because the code would be running in a browser.
        </Alert>
      </Card>

      <Card>
        <CardTitle>This device</CardTitle>
        <CardHint>
          Section 15b: the execution path is recorded with every scan, so a latency figure is
          attributable to the backend that produced it.
        </CardHint>
        {profile ? (
          <dl className="mt-2 grid gap-2 sm:grid-cols-2">
            <Row label="Execution path" value={profile.path} />
            <Row label="WASM threads" value={String(profile.numThreads)} />
            <Row label="Cross-origin isolated" value={profile.crossOriginIsolated ? "yes" : "no"} />
            <Row label="WebGPU" value={profile.webgpu ? "available" : "no"} />
            <Row label="WASM SIMD" value={profile.simd ? "available" : "no"} />
          </dl>
        ) : (
          <p className="mt-2 text-base text-fg-muted">Probing…</p>
        )}
        {profile?.warning ? (
          <Alert tone="review" className="mt-3">
            {profile.warning}
          </Alert>
        ) : null}
      </Card>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b border-border pb-1 last:border-0">
      <dt className="text-fg-muted">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
