/**
 * The same-origin API proxy.
 *
 * Its whole job is to take a request the browser made without credentials and
 * give it credentials, so that no access token is ever reachable from page
 * JavaScript. See `src/lib/api/session.ts` for the reasoning.
 *
 * It also does the one thing a token holder has to do: when the access token has
 * expired, spend the refresh token, retry once, and write the new pair back. The
 * caller sees a slower request, never a 401 it has to understand. Section 5's
 * degradation ladder has no rung for "you were logged out while walking between
 * two shops", and this is why it does not need one.
 */
import { NextResponse, type NextRequest } from "next/server";
import {
  ACCESS_COOKIE,
  API_ORIGIN,
  REFRESH_COOKIE,
  REFRESH_MAX_AGE,
  ROLE_COOKIE,
  cookieOptions,
} from "@/lib/api/session";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/** Headers we refuse to forward upstream. `host` would break virtual hosting;
 *  `cookie` would hand our session cookie to a service that has no use for it
 *  and should never see it. */
const STRIPPED = new Set(["host", "cookie", "connection", "content-length", "authorization"]);

/** And headers we refuse to pass back. The upstream must not be able to set a
 *  cookie on our origin — that is the one thing this proxy exists to control. */
const STRIPPED_RESPONSE = new Set(["set-cookie", "transfer-encoding", "connection"]);

interface Context {
  params: Promise<{ path: string[] }>;
}

async function forward(request: NextRequest, context: Context): Promise<NextResponse> {
  const { path } = await context.params;
  const upstream = `${API_ORIGIN}/api/v1/${path.join("/")}${request.nextUrl.search}`;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!STRIPPED.has(key.toLowerCase())) headers.set(key, value);
  });

  // Read the body once: a retry after refresh needs to send it again, and a
  // `ReadableStream` body cannot be replayed.
  const body =
    request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.arrayBuffer();

  const access = request.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;

  let response = await call(upstream, request.method, headers, body, access);
  let refreshed: RefreshedPair | null = null;

  if (response.status === 401 && refresh) {
    refreshed = await renew(refresh);
    if (refreshed) {
      response = await call(upstream, request.method, headers, body, refreshed.access_token);
    }
  }

  const out = new NextResponse(response.body, {
    status: response.status,
    statusText: response.statusText,
  });
  response.headers.forEach((value, key) => {
    if (!STRIPPED_RESPONSE.has(key.toLowerCase())) out.headers.set(key, value);
  });
  // `require-corp` (next.config.ts) rejects any subresource that does not opt
  // in, and a proxied API response is a subresource like any other.
  out.headers.set("Cross-Origin-Resource-Policy", "same-origin");

  if (refreshed) {
    out.cookies.set(ACCESS_COOKIE, refreshed.access_token, cookieOptions(refreshed.expires_in));
    out.cookies.set(REFRESH_COOKIE, refreshed.refresh_token, cookieOptions(REFRESH_MAX_AGE));
    out.cookies.set(ROLE_COOKIE, refreshed.role, cookieOptions(REFRESH_MAX_AGE, true));
  } else if (response.status === 401) {
    // The refresh token is spent or invalid. Clear the session rather than
    // leaving a cookie that will 401 on every request for the next week.
    out.cookies.delete(ACCESS_COOKIE);
    out.cookies.delete(REFRESH_COOKIE);
    out.cookies.delete(ROLE_COOKIE);
  }
  return out;
}

/** Long enough for a report render, which also travels this route. */
const PROXY_TIMEOUT_MS = 60_000;
/** Token exchange only: one signature check. */
const AUTH_TIMEOUT_MS = 15_000;

function call(
  url: string,
  method: string,
  headers: Headers,
  body: ArrayBuffer | undefined,
  token: string | undefined,
): Promise<Response> {
  const sent = new Headers(headers);
  if (token) sent.set("Authorization", `Bearer ${token}`);
  return fetch(url, {
    method,
    headers: sent,
    body,
    cache: "no-store",
    redirect: "manual",
    // The browser already gives up on its own schedule (`lib/api/client.ts`),
    // but that abort does not reach this hop — without a deadline here a hung
    // API leaves one pending upstream request per scan inside the Next process,
    // accumulating for as long as the officer keeps trying.
    //
    // 60 s rather than the client's 30 s, because report rendering also travels
    // this route and is allowed to be slow. The bound exists to stop a leak, not
    // to be the thing that times a scan out.
    signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
  });
}

interface RefreshedPair {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  role: string;
}

async function renew(refreshToken: string): Promise<RefreshedPair | null> {
  let response: Response;
  try {
    response = await fetch(`${API_ORIGIN}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
      signal: AbortSignal.timeout(AUTH_TIMEOUT_MS),
    });
  } catch {
    // Returning null means "could not renew", which the caller already handles
    // by clearing the session. A silent API must not hold a request open while
    // it decides.
    return null;
  }
  if (!response.ok) return null;
  return (await response.json()) as RefreshedPair;
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
