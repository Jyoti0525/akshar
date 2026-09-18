import { NextResponse, type NextRequest } from "next/server";
import {
  ACCESS_COOKIE,
  API_ORIGIN,
  REFRESH_COOKIE,
  REFRESH_MAX_AGE,
  ROLE_COOKIE,
  cookieOptions,
} from "@/lib/api/session";

/**
 * The session gate: renew, redirect, or step aside.
 *
 * A visitor with no session goes to `/login` with the page they wanted kept in
 * `next`, so signing in lands them where they were going — which is what happens
 * when a controller opens a shared filtered link (section 11) and has to sign in
 * first. Without it they would arrive at the dashboard's default view and have
 * to be sent the link again.
 *
 * **Why it also renews.** The browser's own calls go through the proxy at
 * `src/app/api/v1/[...path]/route.ts`, which spends the refresh token and
 * retries on a 401. Server Components do not: `serverFetch` reads the access
 * cookie and calls the API itself, and there is no retry behind it — a Server
 * Component cannot write a cookie, so it could not store a renewed token even if
 * it asked for one. That left the two halves of the dashboard on different
 * clocks. An access token lives 30 minutes (`api/security.py`); a refresh token
 * lives 14 days. Anyone who left a tab open over lunch came back to a page
 * saying their session had ended while the credential that would have renewed it
 * sat unspent in the same cookie jar. Middleware is the one place in the request
 * that runs *before* the render and *can* set cookies, so the renewal belongs
 * here.
 *
 * The renewed token is written to the request as well as the response. `cookies()`
 * inside a Server Component reads the request's `cookie` header, so without that
 * line the officer's first page after renewal would still be rendered with the
 * dead token and the new one would only take effect on the *next* navigation.
 *
 * **The `exp` claim is read without verifying the signature, and that is not an
 * authorisation decision.** It answers one question — is it worth spending a
 * round trip to renew — and nothing else. A forged token with a distant `exp`
 * buys its holder the right to have the API reject it, which is what would have
 * happened anyway. Every real decision is still made by `require_role` on the
 * API against the signed token.
 */
const PUBLIC = ["/login", "/manifest.webmanifest", "/sw.js", "/offline"];

/** Renew this many seconds before the token actually dies. The clocks of the
 *  browser, the Next server and the API are not the same clock, and a token that
 *  passes here with four seconds left is a token the API sees as expired. */
const RENEW_BEFORE_SECONDS = 60;

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (PUBLIC.some((path) => pathname === path || pathname.startsWith(`${path}/`))) {
    return NextResponse.next();
  }

  const access = request.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;

  if (access && !expiringWithin(access, RENEW_BEFORE_SECONDS)) return NextResponse.next();

  // No refresh token, or one too old to be worth presenting: this session is
  // over however sympathetically we phrase it.
  if (!refresh || expiringWithin(refresh, 0)) return toLogin(request);

  const renewed = await renew(refresh);

  if (renewed === "unreachable") {
    // The API is down, not the session. Clearing the cookies here would turn a
    // thirty-second outage into every officer in the field being signed out,
    // and section 5's degradation ladder has no rung for that. Let the page
    // render and say the server could not be reached — which is true, and
    // recoverable by waiting.
    return NextResponse.next();
  }
  if (renewed === "rejected") return toLogin(request);

  // Write the new pair to the request, so the render happening immediately
  // after this line sees it, and to the response, so the browser keeps it.
  request.cookies.set(ACCESS_COOKIE, renewed.access_token);
  request.cookies.set(REFRESH_COOKIE, renewed.refresh_token);
  request.cookies.set(ROLE_COOKIE, renewed.role);

  const response = NextResponse.next({ request: { headers: request.headers } });
  response.cookies.set(ACCESS_COOKIE, renewed.access_token, cookieOptions(renewed.expires_in));
  response.cookies.set(REFRESH_COOKIE, renewed.refresh_token, cookieOptions(REFRESH_MAX_AGE));
  // Readable, like the proxy and the sign-in route write it: navigation needs
  // the role and a role is not a credential. Re-set on every renewal because
  // `/auth/refresh` re-reads it from the store — a supervisor demoted this
  // morning loses the supervisor links here, not at the next sign-in.
  response.cookies.set(ROLE_COOKIE, renewed.role, cookieOptions(REFRESH_MAX_AGE, true));
  return response;
}

/** Is this JWT dead, or dead within `seconds`? Unreadable counts as dead: a
 *  token we cannot parse is one we cannot vouch for, and the recovery — try to
 *  renew, then ask for a sign-in — is the right response to both. */
function expiringWithin(token: string, seconds: number): boolean {
  const [, payload, signature] = token.split(".");
  if (payload === undefined || signature === undefined) return true;
  try {
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    const claims = JSON.parse(atob(padded)) as { exp?: unknown };
    if (typeof claims.exp !== "number") return true;
    return claims.exp - seconds <= Date.now() / 1000;
  } catch {
    return true;
  }
}

interface RenewedPair {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  role: string;
}

/** How long a renewal may hold up a page. A refused connection fails in
 *  microseconds; an API that accepts the socket and then stops answering does
 *  not fail at all, and this code sits in front of *every* navigation. Waiting
 *  is the worse failure of the two — an officer would rather be told the server
 *  is unreachable than watch a blank tab. */
const RENEW_TIMEOUT_MS = 5000;

/** Three outcomes, not two. "The API said no" and "the API said nothing" lead
 *  to opposite actions — sign out, or carry on — and collapsing them into a
 *  single `null` is how an outage becomes a mass sign-out. */
async function renew(refreshToken: string): Promise<RenewedPair | "rejected" | "unreachable"> {
  let response: Response;
  try {
    response = await fetch(`${API_ORIGIN}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
      signal: AbortSignal.timeout(RENEW_TIMEOUT_MS),
    });
  } catch {
    // Refused, DNS-dead, or timed out. All three mean the same thing here, and
    // none of them means the officer's credentials are bad.
    return "unreachable";
  }
  if (response.status >= 500) return "unreachable";
  if (!response.ok) return "rejected";
  try {
    return (await response.json()) as RenewedPair;
  } catch {
    return "rejected";
  }
}

/** To the sign-in page, carrying the destination — and taking the dead cookies
 *  with us, so the next request does not repeat this whole dance. */
function toLogin(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;
  const url = request.nextUrl.clone();
  url.pathname = "/login";
  url.search = "";
  if (pathname !== "/") url.searchParams.set("next", `${pathname}${request.nextUrl.search}`);

  const response = NextResponse.redirect(url);
  for (const name of [ACCESS_COOKIE, REFRESH_COOKIE, ROLE_COOKIE]) {
    response.cookies.set(name, "", { ...cookieOptions(0), maxAge: 0 });
  }
  return response;
}

export const config = {
  matcher: [
    // Everything except Next's own assets, the models bundle and the API proxy.
    // The proxy is excluded because it has to be able to answer 401 itself —
    // redirecting an XHR to an HTML sign-in page is how a fetch ends up parsing
    // a login form as JSON. It does its own renewal for the same reason.
    "/((?!_next/static|_next/image|api/|models/|icons/|favicon.ico|manifest.webmanifest|sw.js|workbox-).*)",
  ],
};
