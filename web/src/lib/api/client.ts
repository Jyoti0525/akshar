"use client";

/**
 * The browser's way to the API: same-origin, no token in JavaScript.
 *
 * Every request goes to `/api/v1/...` on our own origin, where the route handler
 * attaches the bearer token from the httpOnly cookie. See `session.ts` for why.
 */
import { ApiError, messageFrom } from "./errors";
// Both sides of the boundary use these, so they live in a module that is
// neither "use client" nor "server-only" — see `query.ts` for what breaks
// otherwise. Re-exported here so existing client imports keep working.
import { withQuery, type Query } from "./query";

export { withQuery, type Query };

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Query;
  signal?: AbortSignal;
  /** Multipart bodies are passed through untouched; the browser must set its
   *  own boundary, so we must not set Content-Type. */
  form?: FormData;
  /** Override the deadline below. Only for a call known to be slower than a
   *  scan; there is no way to switch the deadline off. */
  timeoutMs?: number;
}

/**
 * Every request gets a deadline, and this is the whole reason why.
 *
 * `fetch` rejects when the network is *unreachable*, and the catch below turns
 * that into `ApiError(0)`, which is tier L1: the caller queues the scan and the
 * officer carries on. That covers the case section 5 describes — no signal.
 *
 * It does not cover a server that is **reachable and does not answer**. With a
 * dead Postgres behind it, the API completes the TCP handshake and then blocks
 * forever; `fetch` neither resolves nor rejects. `capture()` in
 * `lib/scan/engine.ts` awaits it, `busy` stays true, and the officer is left
 * with a photograph that never became a verdict and never became a queued
 * scan either. No error, no record, nothing to retry — the one outcome the
 * degradation ladder exists to make impossible.
 *
 * A hung server is an unusable network, so it is classified as one. The
 * deadline expiring produces the same `ApiError(0)` as an unreachable host,
 * which means the existing L1 path queues the scan with no further changes.
 *
 * 30 seconds, against a performance budget (section 4) whose worst sanctioned
 * server figure is 2000 ms. Anything past fifteen times that is not slow, it is
 * broken — and the cost of being wrong is small, because being wrong queues the
 * scan rather than losing it.
 */
const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * The caller's cancellation and our deadline, as one signal.
 *
 * `AbortSignal.any` is the one-liner, and it is guarded because a PWA installed
 * on an older Android WebView is a real target here. The fallback forwards the
 * caller's abort into our own controller, which is the same behaviour with more
 * lines.
 */
function withDeadline(
  caller: AbortSignal | undefined,
  timeoutMs: number,
): { signal: AbortSignal; expired: () => boolean; done: () => void } {
  const deadline = new AbortController();
  let fired = false;
  const timer = setTimeout(() => {
    fired = true;
    deadline.abort();
  }, timeoutMs);

  let signal = deadline.signal;
  if (caller) {
    if (typeof AbortSignal.any === "function") {
      signal = AbortSignal.any([caller, deadline.signal]);
    } else if (caller.aborted) {
      deadline.abort();
    } else {
      caller.addEventListener("abort", () => deadline.abort(), { once: true });
    }
  }

  return { signal, expired: () => fired, done: () => clearTimeout(timer) };
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, signal, form, timeoutMs = DEFAULT_TIMEOUT_MS } = options;
  const url = withQuery(`/api/v1${path}`, query);
  const deadline = withDeadline(signal, timeoutMs);

  try {
    let response: Response;
    try {
      response = await fetch(url, {
        method,
        signal: deadline.signal,
        // Same-origin, so the session cookie is sent and nothing cross-site is.
        credentials: "same-origin",
        headers: form || body === undefined ? {} : { "Content-Type": "application/json" },
        body: form ?? (body === undefined ? undefined : JSON.stringify(body)),
      });
    } catch (cause) {
      // The caller's own cancellation is not a network condition — a screen
      // that unmounted does not want its scan queued. Rethrown untouched so it
      // stays an AbortError and no caller mistakes it for tier L1.
      if (signal?.aborted && !deadline.expired()) throw cause;
      // Everything else is an unusable network: unreachable, or reachable and
      // silent past the deadline. Status 0 is our marker for tier L1 — the
      // caller queues rather than showing a failure.
      throw new ApiError(0, offlineMessage(deadline.expired()), cause);
    }

    if (response.status === 204) return undefined as T;

    // The deadline covers the body too. Headers can arrive promptly from a
    // server that then stalls mid-response, and a read that never finishes is
    // the same dead end as a request that never answers.
    let text: string;
    try {
      text = await response.text();
    } catch (cause) {
      if (signal?.aborted && !deadline.expired()) throw cause;
      throw new ApiError(0, offlineMessage(deadline.expired()), cause);
    }
    const parsed: unknown = text ? safeJson(text) : null;

    if (!response.ok) {
      throw new ApiError(response.status, messageFrom(response.status, parsed), parsed);
    }
    return parsed as T;
  } finally {
    deadline.done();
  }
}

/** Tier L1 either way; the officer is told which kind of unusable it was, because
 *  "the server stopped answering" and "there is no signal" lead to different
 *  next actions — the first is worth reporting, the second is worth walking. */
function offlineMessage(timedOut: boolean): string {
  return timedOut
    ? "The server accepted the request and stopped answering. The scan is queued and will sync."
    : "No network. The scan is queued and will sync.";
}

/** A report is a file, not JSON, and it must not be parsed on the way through. */
export async function apiBlob(path: string, query?: Query): Promise<Blob> {
  // A report is rendered server-side and is the slowest thing the API does, so
  // it gets a longer deadline than a scan — but it gets one. Without it, a
  // stalled render leaves the officer holding a download that never arrives and
  // never fails, which is how the PDF route behaved when WeasyPrint could not
  // load its native libraries.
  const deadline = withDeadline(undefined, 60_000);
  try {
    const response = await fetch(withQuery(`/api/v1${path}`, query), {
      credentials: "same-origin",
      signal: deadline.signal,
    });
    if (!response.ok) {
      throw new ApiError(response.status, messageFrom(response.status, null));
    }
    return await response.blob();
  } catch (cause) {
    if (cause instanceof ApiError) throw cause;
    throw new ApiError(0, offlineMessage(deadline.expired()), cause);
  } finally {
    deadline.done();
  }
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

/** Section 11: *"Every table paginates server-side and exports to CSV."* The
 *  export is the same route with `format=csv`, so the file always contains
 *  exactly the rows the screen was showing the filters for. */
export function downloadCsv(path: string, query: Query, filename: string): void {
  const url = withQuery(`/api/v1${path}`, { ...query, format: "csv" });
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
}
