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
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, signal, form } = options;
  const url = withQuery(`/api/v1${path}`, query);

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      signal,
      // Same-origin, so the session cookie is sent and nothing cross-site is.
      credentials: "same-origin",
      headers: form || body === undefined ? {} : { "Content-Type": "application/json" },
      body: form ?? (body === undefined ? undefined : JSON.stringify(body)),
    });
  } catch (cause) {
    // `fetch` rejects on a dead network. Status 0 is our marker for tier L1 —
    // the caller queues rather than showing a failure.
    throw new ApiError(0, "No network. The scan is queued and will sync.", cause);
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const parsed: unknown = text ? safeJson(text) : null;

  if (!response.ok) {
    throw new ApiError(response.status, messageFrom(response.status, parsed), parsed);
  }
  return parsed as T;
}

/** A report is a file, not JSON, and it must not be parsed on the way through. */
export async function apiBlob(path: string, query?: Query): Promise<Blob> {
  const response = await fetch(withQuery(`/api/v1${path}`, query), {
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new ApiError(response.status, messageFrom(response.status, null));
  }
  return response.blob();
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
