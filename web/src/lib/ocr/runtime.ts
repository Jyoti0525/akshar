"use client";

/**
 * Which execution path this browser actually gives us, decided once and
 * recorded.
 *
 * Section 15b: *"`onnxruntime-web` — WebGPU EP first, WASM SIMD+threads
 * fallback, **path recorded in `scans.model_versions`** so every latency figure
 * is attributable."* A 1,900 ms scan means one thing on a WebGPU laptop and
 * another on a single-threaded WASM phone, and without the path in the record
 * the two are indistinguishable six months later.
 *
 * The thread count is the part people get wrong. `numThreads` above 1 requires
 * `SharedArrayBuffer`, which requires cross-origin isolation, which requires the
 * COOP/COEP headers set in `next.config.ts`. If a reverse proxy drops them,
 * `crossOriginIsolated` goes false, ONNX Runtime silently pins to one thread and
 * section 4's WASM budget roughly doubles. So it is probed, not assumed, and
 * reported on screen.
 */
export type ExecutionPath = "webgpu" | "wasm-simd-threads" | "wasm-simd" | "wasm" | "unavailable";

export interface RuntimeProfile {
  path: ExecutionPath;
  crossOriginIsolated: boolean;
  numThreads: number;
  simd: boolean;
  webgpu: boolean;
  /** What to show the officer when the fast path is not available, in one
   *  sentence. Empty when everything is as it should be. */
  warning: string;
}

/** WebAssembly SIMD, detected by compiling the smallest module that uses it.
 *  Feature detection rather than a user-agent test, because the answer differs
 *  between two builds of the same browser version. */
function hasSimd(): boolean {
  try {
    // (module (func (result v128) (i8x16.splat (i32.const 0))))
    const bytes = Uint8Array.from([
      0, 97, 115, 109, 1, 0, 0, 0, 1, 5, 1, 96, 0, 1, 123, 3, 2, 1, 0, 10, 10, 1, 8, 0, 65, 0,
      253, 15, 253, 98, 11,
    ]);
    return WebAssembly.validate(bytes);
  } catch {
    return false;
  }
}

async function hasWebGpu(): Promise<boolean> {
  const gpu = (navigator as Navigator & { gpu?: { requestAdapter(): Promise<unknown> } }).gpu;
  if (!gpu) return false;
  try {
    return (await gpu.requestAdapter()) !== null;
  } catch {
    return false;
  }
}

let cached: Promise<RuntimeProfile> | null = null;

export function runtimeProfile(): Promise<RuntimeProfile> {
  if (!cached) cached = probe();
  return cached;
}

async function probe(): Promise<RuntimeProfile> {
  const isolated = typeof crossOriginIsolated === "boolean" ? crossOriginIsolated : false;
  const simd = hasSimd();
  const webgpu = await hasWebGpu();

  // ONNX Runtime caps at 4 in practice; more threads on a phone costs more in
  // scheduling than it returns.
  const cores = navigator.hardwareConcurrency ?? 1;
  const numThreads = isolated ? Math.max(1, Math.min(4, cores)) : 1;

  const path: ExecutionPath = webgpu
    ? "webgpu"
    : simd && numThreads > 1
      ? "wasm-simd-threads"
      : simd
        ? "wasm-simd"
        : typeof WebAssembly === "object"
          ? "wasm"
          : "unavailable";

  let warning = "";
  if (!webgpu && !isolated) {
    warning =
      "This page is not cross-origin isolated, so on-device recognition is limited to one " +
      "thread and will take roughly twice as long. The COOP and COEP headers are missing — " +
      "usually a proxy in front of the app.";
  } else if (path === "wasm") {
    warning = "This browser has no WebAssembly SIMD. On-device recognition will be slow.";
  } else if (path === "unavailable") {
    warning = "This browser cannot run on-device recognition. Scans will be sent to the server.";
  }

  return { path, crossOriginIsolated: isolated, numThreads, simd, webgpu, warning };
}

/** The string that goes into `scans.model_versions` alongside the model
 *  digests. Section 6: a measurement disputed six months later must be
 *  re-runnable exactly, and "which backend produced it" is part of that. */
export function runtimeTag(profile: RuntimeProfile): string {
  return `${profile.path}/t${profile.numThreads}${profile.crossOriginIsolated ? "" : "/no-coi"}`;
}
