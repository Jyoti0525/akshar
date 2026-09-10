import { NextResponse, type NextRequest } from "next/server";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/api/session";

/**
 * One redirect, and nothing else.
 *
 * A visitor with no session goes to `/login` with the page they wanted kept in
 * `next`, so signing in lands them where they were going — which is what happens
 * when a controller opens a shared filtered link (section 11) and has to sign in
 * first. Without it they would arrive at the dashboard's default view and have
 * to be sent the link again.
 *
 * This is navigation, not authorisation. The cookie's presence is all that is
 * checked here; whether it is valid, and what it permits, is decided by
 * `require_role` on the API against the signed token.
 */
const PUBLIC = ["/login", "/manifest.webmanifest", "/sw.js", "/offline"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (PUBLIC.some((path) => pathname === path || pathname.startsWith(`${path}/`))) {
    return NextResponse.next();
  }

  const signedIn =
    request.cookies.has(ACCESS_COOKIE) || request.cookies.has(REFRESH_COOKIE);
  if (signedIn) return NextResponse.next();

  const url = request.nextUrl.clone();
  url.pathname = "/login";
  url.search = "";
  if (pathname !== "/") url.searchParams.set("next", `${pathname}${request.nextUrl.search}`);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: [
    // Everything except Next's own assets, the models bundle and the API proxy.
    // The proxy is excluded because it has to be able to answer 401 itself —
    // redirecting an XHR to an HTML sign-in page is how a fetch ends up parsing
    // a login form as JSON.
    "/((?!_next/static|_next/image|api/|models/|icons/|favicon.ico|manifest.webmanifest|sw.js|workbox-).*)",
  ],
};
