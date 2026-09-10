"use client";

/**
 * The outbox, and the order it drains in.
 *
 * Section 5: *"There is no conflict resolution, by design. Scans are immutable
 * facts. Corrections are append-only rows, never edits."* So this module never
 * merges anything. It queues, it replays, and it marks what the server accepted.
 *
 * The one piece of policy here is ordering: **every verdict goes before any
 * photo.** A verdict is 2 KB and a photo is 3 MB, and on the connection an
 * officer actually has, sending them interleaved means the twentieth shop's
 * verdict waits behind the first shop's image.
 *
 * **The photo half is held, not sent, and this is deliberate.** The API has no
 * route that attaches a photograph to a scan that already exists, and it cannot
 * simply grow one: section 6 hashes the scan record, `image_key` and
 * `image_sha256` included, into the chain in `evidence/chain.py`. Filling those
 * two fields after the record is sealed would change the payload the hash was
 * taken over and break the chain at that row — the precise failure the chain is
 * there to detect. Re-posting to `POST /scans` does not help either: a scan id
 * we already hold takes the replay path and returns the stored verdict without
 * storing anything.
 *
 * So an offline photograph stays in IndexedDB, `photo_state` stays `held`, and
 * `/queue` says so in words. Section 5's L4 rule is honoured — the officer has
 * a timestamped record either way — and section 6's chain is not quietly
 * broken to make a progress bar reach 100%. Closing this properly needs a
 * server-side decision about where a deferred evidence digest lives, and that
 * is a decision, not an oversight.
 */
import { apiFetch } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { db, type OutboxScan, type OutboxPhoto } from "./db";
import type { SkuCacheResponse, SyncResponse } from "@/lib/api/types";

/** `SyncRequest.scans` is capped at 500 by the API schema; 50 is a batch that
 *  fits comfortably in one request on a weak uplink and loses little if it
 *  fails. */
const BATCH = 50;

export async function enqueue(
  scan: OutboxScan,
  photo?: OutboxPhoto,
  extraPhotos: OutboxPhoto[] = [],
): Promise<void> {
  const database = await db();
  const tx = database.transaction(["outbox", "photos"], "readwrite");
  await tx.objectStore("outbox").put(scan);
  // `extraPhotos` carries the second and later frames of a multi-frame scan,
  // keyed `<scanId>:frameN`. They are held on the same terms as the first —
  // one transaction, so a scan is never queued with only some of its evidence.
  if (photo) await tx.objectStore("photos").put(photo);
  for (const extra of extraPhotos) await tx.objectStore("photos").put(extra);
  await tx.done;
}

export async function pending(): Promise<OutboxScan[]> {
  const database = await db();
  const all = await database.getAllFromIndex("outbox", "by_state", "pending");
  // UUIDv7 is time-ordered, so sorting by id is sorting by capture time, and it
  // does not depend on the client clock agreeing with the server's.
  return all.sort((a, b) => a.id.localeCompare(b.id));
}

export async function counts(): Promise<Record<OutboxScan["state"], number>> {
  const database = await db();
  const all = await database.getAll("outbox");
  const out: Record<OutboxScan["state"], number> = {
    pending: 0,
    sending: 0,
    synced: 0,
    failed: 0,
  };
  for (const scan of all) out[scan.state] += 1;
  return out;
}

export async function all(): Promise<OutboxScan[]> {
  const database = await db();
  const rows = await database.getAll("outbox");
  return rows.sort((a, b) => b.id.localeCompare(a.id));
}

export interface DrainResult {
  attempted: number;
  created: number;
  duplicates: number;
  photosHeld: number;
  offline: boolean;
  error?: string;
}

/**
 * Send everything that is waiting. Safe to call repeatedly and safe to call
 * while offline — an offline call marks nothing and reports `offline: true`.
 */
export async function drain(): Promise<DrainResult> {
  const result: DrainResult = {
    attempted: 0,
    created: 0,
    duplicates: 0,
    photosHeld: 0,
    offline: false,
  };

  const queue = await pending();
  result.attempted = queue.length;

  for (let start = 0; start < queue.length; start += BATCH) {
    const slice = queue.slice(start, start + BATCH);
    await mark(slice, "sending");
    try {
      const response = await apiFetch<SyncResponse>("/scans/sync", {
        method: "POST",
        body: { scans: slice.map(asSyncItem) },
      });
      result.created += response.created;
      result.duplicates += response.duplicates;
      await accept(response);
    } catch (error) {
      await mark(slice, "pending");
      if (error instanceof ApiError && error.isOffline) {
        result.offline = true;
        return result;
      }
      result.error = error instanceof Error ? error.message : String(error);
      await mark(slice, "failed", result.error);
      return result;
    }
  }

  // Every verdict is on the server. The photographs stay where they are, for
  // the reason given at the top of this file.
  result.photosHeld = (await heldPhotos()).count;
  return result;
}

function asSyncItem(scan: OutboxScan) {
  return {
    id: scan.id,
    source: scan.source,
    degradation_tier: scan.degradation_tier,
    declaration_set: scan.declaration_set,
    coverage: scan.coverage,
    latency_ms: scan.latency_ms,
    cache_hit: scan.cache_hit,
    geo: scan.geo,
    captured_at: scan.captured_at,
    model_versions: scan.model_versions,
    rulepack_version: scan.rulepack_version,
    district: scan.district,
  };
}

async function mark(scans: OutboxScan[], state: OutboxScan["state"], error?: string) {
  const database = await db();
  const tx = database.transaction("outbox", "readwrite");
  for (const scan of scans) {
    await tx.store.put({
      ...scan,
      state,
      attempts: state === "failed" ? scan.attempts + 1 : scan.attempts,
      ...(error ? { last_error: error } : {}),
    });
  }
  await tx.done;
}

async function accept(response: SyncResponse) {
  const database = await db();
  const tx = database.transaction("outbox", "readwrite");
  for (const item of response.results) {
    const existing = await tx.store.get(String(item.id));
    if (!existing) continue;
    await tx.store.put({
      ...existing,
      // A duplicate is a success: section 5's whole point is that replaying the
      // outbox is harmless, so `created: false` means "already there", not
      // "rejected".
      state: "synced",
      chain_seq: item.chain_seq,
      record_sha256: item.record_sha256,
    });
  }
  await tx.done;
}

/**
 * How many photographs are being held, and how much space they take.
 *
 * There is no upload here on purpose — see the note at the top of the file. The
 * numbers are surfaced on `/queue` so the held bytes are visible rather than
 * silently accumulating until the browser evicts the origin's storage.
 */
export async function heldPhotos(): Promise<{ count: number; bytes: number }> {
  const database = await db();
  const photos = await database.getAll("photos");
  return {
    count: photos.length,
    bytes: photos.reduce((total, photo) => total + photo.bytes, 0),
  };
}

/** Discard a held photograph the officer has decided they do not need. The scan
 *  record itself is untouched: section 5, scans are immutable facts. */
export async function discardPhoto(id: string): Promise<void> {
  const database = await db();
  const scan = await database.get("outbox", id);
  await database.delete("photos", id);
  if (scan) await database.put("outbox", { ...scan, photo_state: "none" });
}

/** Section 5: *"On wifi, pull the 5,000 most-scanned SKUs for the officer's
 *  district."* Called from `/queue` by hand and on a metered-free connection. */
export async function warmSkuCache(district?: string, n = 5000): Promise<number> {
  const response = await apiFetch<SkuCacheResponse>("/skus/cache", {
    query: { district: district ?? null, n },
  });
  const database = await db();
  const tx = database.transaction("skus", "readwrite");
  await tx.store.clear();
  const cachedAt = new Date().toISOString();
  for (const sku of response.skus) {
    await tx.store.put({ ...sku, district: district ?? null, cached_at: cachedAt });
  }
  await tx.done;
  return response.count;
}
