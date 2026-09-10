"use client";

/**
 * The model bundle the browser is supposed to hold, and how to find out whether
 * it actually does.
 *
 * Section 5 budgets ~50 MB across four assets and section 15b caches them
 * `CacheFirst` *"with explicit versioning"*. Versioning is why every entry below
 * carries a filename that changes when the weights change: a cache entry keyed
 * on `/models/detector.onnx` can never be invalidated safely, and an officer
 * would keep scanning with last month's detector while the dashboard attributed
 * the results to this month's.
 *
 * The names match `scripts/fetch_models.py`, which is what puts them on disk.
 * Nothing here downloads anything: the service worker precaches the shell and
 * fetches models on first use, and `/queue` shows what is present.
 */
export interface ModelAsset {
  key: string;
  file: string;
  /** Section 5's table, in bytes, for the cache-size figure on `/queue`. */
  approxBytes: number;
  purpose: string;
}

export const MODEL_BUNDLE: ModelAsset[] = [
  {
    key: "detector",
    file: "detector_rtmdet_ins_tiny_int8.onnx",
    approxBytes: 12 * 1024 * 1024,
    purpose: "Package, PDP and panel instance segmentation (block B2).",
  },
  {
    key: "ocr_det",
    file: "ppocrv6_small_det.onnx",
    approxBytes: 5 * 1024 * 1024,
    purpose: "Text region detection (block B6).",
  },
  {
    key: "ocr_rec",
    file: "ppocrv5_rec_devanagari.onnx",
    approxBytes: 23 * 1024 * 1024,
    purpose: "Recognition, Latin and Devanagari on one head (block B6).",
  },
  {
    key: "ocr_dict",
    file: "devanagari_dict.txt",
    approxBytes: 8 * 1024,
    purpose: "The 568-entry character table the recognition head decodes against.",
  },
  {
    key: "classifier",
    file: "field_classifier_int8.onnx",
    approxBytes: 4 * 1024 * 1024,
    purpose: "Field classification tier 2 (block B8).",
  },
];

export const MODELS_PREFIX = "/models";

export interface BundleStatus {
  present: string[];
  missing: string[];
  bytes: number;
  complete: boolean;
}

/**
 * A HEAD per asset. Cheap when the service worker already holds them — the
 * request is answered from the cache — and it is the only way to distinguish
 * "the officer has never been online since install" from "the bundle is here".
 */
export async function bundleStatus(): Promise<BundleStatus> {
  const present: string[] = [];
  const missing: string[] = [];
  let bytes = 0;

  await Promise.all(
    MODEL_BUNDLE.map(async (asset) => {
      try {
        const response = await fetch(`${MODELS_PREFIX}/${asset.file}`, { method: "HEAD" });
        if (response.ok) {
          present.push(asset.key);
          bytes += Number(response.headers.get("content-length") ?? asset.approxBytes);
        } else {
          missing.push(asset.key);
        }
      } catch {
        missing.push(asset.key);
      }
    }),
  );

  return { present, missing, bytes, complete: missing.length === 0 };
}

export function bundleBudgetBytes(): number {
  return MODEL_BUNDLE.reduce((total, asset) => total + asset.approxBytes, 0);
}
