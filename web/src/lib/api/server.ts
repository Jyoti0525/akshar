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

/**
 * Deadlines for the two server-side callers below.
 *
 * `lib/api/client.ts` explains at length why an unbounded `fetch` is a bug and
 * not merely slow: a server that is reachable and does not answer — a dead
 * Postgres behind a live API is the case that actually happens — leaves the
 * request pending forever rather than rejecting. On the browser side that cost
 * an officer a scan. Here it costs a page: these run inside a Server Component,
 * so an unbounded call does not fail the render, it *suspends* it, and the
 * officer gets a browser that spins with nothing on it.
 *
 * `undici` has its own multi-minute defaults, which is far past the point where
 * a human has given up and reloaded.
 *
 * The health probe gets the short one on purpose. It decorates the sign-in page
 * with an optional panel, and the sign-in page is the screen someone opens
 * *because* the system is misbehaving. It is the last page allowed to be held
 * up by a sick API.
 */
const SERVER_TIMEOUT_MS = 15_000;
const HEALTH_TIMEOUT_MS = 2_500;

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
    // A bounded render. `tryServerFetch` below already turns a thrown error
    // into an empty panel, so with a deadline in place a sick API degrades a
    // page instead of suspending it.
    signal: AbortSignal.timeout(SERVER_TIMEOUT_MS),
  });

  const text = await response.text();
  const parsed: unknown = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new ApiError(response.status, messageFrom(response.status, parsed), parsed);
  }
  return parsed as T;
}

/** What `tryServerFetch` learned but could not return.
 *
 *  `status` is the HTTP status when the API answered, and `null` when it never
 *  did — a DNS failure, the API not running, a build-time probe. The
 *  distinction matters to any page that would otherwise report "this does not
 *  exist" when what actually happened was "your session ended": the middleware
 *  only checks that the session cookie is *present*, so an expired token walks
 *  past it and arrives here as a 401. */
export interface FetchResult<T> {
  data: T | null;
  status: number | null;
}

export async function tryServerFetchResult<T>(
  path: string,
  query?: Query,
): Promise<FetchResult<T>> {
  try {
    return { data: await serverFetch<T>(path, query), status: 200 };
  } catch (error) {
    const digest = (error as { digest?: unknown } | null)?.digest;
    if (digest === "DYNAMIC_SERVER_USAGE") return { data: null, status: null };

    const status = error instanceof ApiError ? error.status : null;
    const reason =
      error instanceof ApiError
        ? `${error.status} ${error.message}`
        : error instanceof Error
          ? `${error.name}: ${error.message}`
          : String(error);
    console.warn(`[akshar] GET /api/v1${path} failed — ${reason}`);
    return { data: null, status };
  }
}

/** Returns `null` instead of throwing on 401/403, for the several views that
 *  would rather render an empty state than a stack trace.
 *
 *  **It logs first.** An empty catch here turns every possible cause — an
 *  expired token, a 422 from a filter the API rejects, a DNS failure, the API
 *  simply not running — into one identical grey panel that says "or". That is
 *  fine for the officer reading the screen and useless for whoever has to fix
 *  it, and the log line is the only place the distinction survives. It goes to
 *  the server's stdout, never to the page.
 *
 *  Use `tryServerFetchResult` instead where the *reason* changes what the page
 *  should say — a 401 is not a 404. */

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
    const response = await fetch(`${API_ORIGIN}/healthz`, {
      cache: "no-store",
      signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}
