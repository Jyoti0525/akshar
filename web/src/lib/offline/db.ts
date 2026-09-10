"use client";

/**
 * The browser's own store. Section 5: *"Scans queue in IndexedDB and replay when
 * the network returns."*
 *
 * Four stores, and the reason each exists:
 *
 *   `outbox`   scans made offline, awaiting sync. Keyed by the client-generated
 *              UUIDv7 so replay is idempotent (section 5: *"Sync is idempotent,
 *              so replaying the outbox never duplicates a record"*).
 *   `photos`   the image bytes, kept apart from the record on purpose. Section 5:
 *              *"Verdicts sync before photos — a verdict is 2 KB and a photo is
 *              3 MB, and the officer needs the record more urgently than the
 *              image."* Two stores is what makes that ordering expressible.
 *   `skus`     the warmed cache, section 5's top 5,000 per district.
 *   `meta`     rulepack, model versions, last warm time. Small and singular.
 *
 * Nothing here holds a credential. See `src/lib/api/session.ts`.
 */
import { openDB, type DBSchema, type IDBPDatabase } from "idb";
import type { DeclarationSet, GeoPoint, SkuSummary, Verdict } from "@/lib/api/types";

export type OutboxState = "pending" | "sending" | "synced" | "failed";

export interface OutboxScan {
  /** UUIDv7 — time-ordered, so it doubles as the replay sort key (section 5). */
  id: string;
  state: OutboxState;
  captured_at: string;
  source: "photo" | "bulk" | "listing_text";
  degradation_tier: string;
  declaration_set: DeclarationSet | Record<string, unknown>;
  verdicts: Verdict[];
  coverage: number | null;
  latency_ms: number | null;
  cache_hit: boolean;
  district: string | null;
  geo: GeoPoint | null;
  model_versions: Record<string, string>;
  rulepack_version: string;
  /** Set once the server has accepted the record; the photo may still be owed. */
  chain_seq?: number;
  record_sha256?: string;
  /** `held` is a real terminal state, not a stage. See `outbox.ts`: the API
   *  has no route that attaches a photograph to a sealed scan record, and
   *  section 6 hashes that record with its image fields inside. */
  photo_state: "none" | "held";
  attempts: number;
  last_error?: string;
}

export interface OutboxPhoto {
  id: string;
  blob: Blob;
  sha256: string;
  bytes: number;
}

interface AksharDB extends DBSchema {
  outbox: {
    key: string;
    value: OutboxScan;
    indexes: { by_state: OutboxState; by_captured: string };
  };
  photos: { key: string; value: OutboxPhoto };
  skus: {
    key: string;
    value: SkuSummary & { district: string | null; cached_at: string };
    indexes: { by_barcode: string; by_phash: string };
  };
  meta: { key: string; value: unknown };
}

const NAME = "akshar";
const VERSION = 1;

let handle: Promise<IDBPDatabase<AksharDB>> | null = null;

export function db(): Promise<IDBPDatabase<AksharDB>> {
  if (!handle) {
    handle = openDB<AksharDB>(NAME, VERSION, {
      upgrade(database) {
        const outbox = database.createObjectStore("outbox", { keyPath: "id" });
        outbox.createIndex("by_state", "state");
        outbox.createIndex("by_captured", "captured_at");

        database.createObjectStore("photos", { keyPath: "id" });

        const skus = database.createObjectStore("skus", { keyPath: "id" });
        // Section 12: *"if the pack has a readable EAN-13 then identifying the
        // SKU is a single indexed lookup — faster and more reliable than image
        // matching."* This is that index, offline.
        skus.createIndex("by_barcode", "barcode");
        skus.createIndex("by_phash", "phash");

        database.createObjectStore("meta");
      },
    });
  }
  return handle;
}

export async function meta<T>(key: string): Promise<T | undefined> {
  return (await (await db()).get("meta", key)) as T | undefined;
}

export async function setMeta(key: string, value: unknown): Promise<void> {
  await (await db()).put("meta", value, key);
}

/**
 * UUIDv7 — 48-bit millisecond timestamp, then randomness.
 *
 * Section 5: *"Every scan gets a client-generated UUIDv7, which is time-ordered
 * so it doubles as a sort key."* `crypto.randomUUID()` is v4 and would not
 * order, so this is written out rather than borrowed.
 */
export function uuidv7(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);

  const ms = BigInt(Date.now());
  for (let i = 0; i < 6; i += 1) {
    bytes[i] = Number((ms >> BigInt(8 * (5 - i))) & 0xffn);
  }
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x70; // version 7
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80; // RFC 4122 variant

  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export async function sha256(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}
