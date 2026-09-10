/**
 * Where the officer's credentials live, and why they live there.
 *
 * The API authenticates with `Authorization: Bearer` (`api/deps/__init__.py`
 * uses `HTTPBearer`). That leaves one question with real consequences: who holds
 * the token?
 *
 * It is held in **httpOnly cookies**, and page JavaScript never sees it. Two
 * paths reach the API and both work without the token being readable:
 *
 *   - Server Components call `serverFetch`, which reads the cookie through
 *     `next/headers` and calls the API directly. Section 11 asks for Server
 *     Components across the whole dashboard, so this is the common path there.
 *   - The browser calls same-origin `/api/v1/...`, which the route handler at
 *     `src/app/api/v1/[...path]/route.ts` forwards upstream with the header
 *     attached.
 *
 * The alternative — a token in `localStorage` or a readable cookie — is what
 * most PWAs do, and it means any injected script can lift an enforcement
 * officer's credentials. The cost of doing it this way is one proxy hop inside
 * Next for browser calls, which is measured in a fraction of a millisecond and
 * is not on the scan path at all: section 5 says the scan runs locally.
 *
 * Offline (section 5, tier L1) is unaffected, and that is not an accident. The
 * outbox in IndexedDB stores scans, never credentials. When the network returns
 * the replay POSTs to the same-origin `/api/v1/scans/sync` and the cookie rides
 * along on its own, so a session that was established before the officer walked
 * into the market is still a session when they walk out.
 */
export const ACCESS_COOKIE = "akshar_at";
export const REFRESH_COOKIE = "akshar_rt";
export const ROLE_COOKIE = "akshar_role";

export const API_ORIGIN = process.env.AKSHAR_API_ORIGIN ?? "http://localhost:8000";

/** The refresh token outlives the access token; both are session-scoped to the
 *  browser profile rather than persisted for a year. `api/config.py` owns the
 *  real lifetimes — these are only how long the cookie is allowed to sit. */
export const REFRESH_MAX_AGE = 60 * 60 * 24 * 7;

export interface CookieOptions {
  httpOnly: boolean;
  sameSite: "lax" | "strict";
  secure: boolean;
  path: string;
  maxAge: number;
}

export function cookieOptions(maxAge: number, readable = false): CookieOptions {
  return {
    httpOnly: !readable,
    // `lax` rather than `strict`: an escalated finding arrives as a link in an
    // email — section 11's "that's how a finding gets escalated to a controller"
    // — and `strict` would drop the session on that first navigation.
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge,
  };
}
