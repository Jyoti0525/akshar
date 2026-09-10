import "server-only";

/**
 * The Server Component's way to the API.
 *
 * Section 11: *"Server Components for all of it except the review queue, which
 * needs interactivity."* Those components run on the Node side, so they read the
 * httpOnly cookie directly through `next/headers` and call the API without the
 * proxy hop the browser needs.
 */
import { cookies } from "next/headers";
import { ApiError, messageFrom } from "./errors";
import { ACCESS_COOKIE, API_ORIGIN } from "./session";
import { withQuery, type Query } from "./query";

export async function accessToken(): Promise<string | null> {
  const jar = await cookies();
  return jar.get(ACCESS_COOKIE)?.value ?? null;
}

export async function serverFetch<T>(path: string, query?: Query): Promise<T> {
  const token = await accessToken();
  if (!token) throw new ApiError(401, "Not signed in.");

  const response = await fetch(`${API_ORIGIN}${withQuery(`/api/v1${path}`, query)}`, {
    headers: { Authorization: `Bearer ${token}` },
    // Section 11: *"Nothing auto-refreshes — a moving dashboard is unusable when
    // someone is reading a figure aloud."* That rule starts here: no page of the
    // dashboard is served from a cache the reader did not ask to refresh, and
    // none of it is revalidated behind their back either.
    cache: "no-store",
  });

  const text = await response.text();
  const parsed: unknown = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new ApiError(response.status, messageFrom(response.status, parsed), parsed);
  }
  return parsed as T;
}

/** Returns `null` instead of throwing on 401/403, for the several views that
 *  would rather render an empty state than a stack trace.
 *
 *  **It logs first.** An empty catch here turns every possible cause — an
 *  expired token, a 422 from a filter the API rejects, a DNS failure, the API
 *  simply not running — into one identical grey panel that says "or". That is
 *  fine for the officer reading the screen and useless for whoever has to fix
 *  it, and the log line is the only place the distinction survives. It goes to
 *  the server's stdout, never to the page. */
export async function tryServerFetch<T>(path: string, query?: Query): Promise<T | null> {
  try {
    return await serverFetch<T>(path, query);
  } catch (error) {
    // Next probes every route at build time and aborts the render the moment it
    // touches `cookies()`, which is how it discovers the route is dynamic. That
    // abort arrives here as a `DynamicServerError`. It is the build working
    // correctly, so logging it would print three alarming lines during a
    // successful build and teach whoever reads them to ignore this log.
    const digest = (error as { digest?: unknown } | null)?.digest;
    if (digest === "DYNAMIC_SERVER_USAGE") return null;

    const reason =
      error instanceof ApiError
        ? `${error.status} ${error.message}`
        : error instanceof Error
          ? `${error.name}: ${error.message}`
          : String(error);
    console.warn(`[akshar] GET /api/v1${path} failed — ${reason}`);
    return null;
  }
}

/** `/healthz` sits outside `/api/v1` and needs no token — it is the ops probe,
 *  and a health endpoint that requires a working auth stack cannot report that
 *  the auth stack is broken. */
export async function opsHealth<T>(): Promise<T | null> {
  try {
    const response = await fetch(`${API_ORIGIN}/healthz`, { cache: "no-store" });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}
