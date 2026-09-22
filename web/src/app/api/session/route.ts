/**
 * Sign in and sign out. The only two places a token is written.
 *
 * `POST` exchanges an email and password for a pair and stores it in httpOnly
 * cookies. `DELETE` clears them. Nothing else in the application can do either,
 * which is what makes "no token in page JavaScript" a property rather than a
 * convention.
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

/** One bcrypt verify and one audit-log insert. See the note at the call. */
const AUTH_TIMEOUT_MS = 15_000;

export async function POST(request: NextRequest): Promise<NextResponse> {
  const body = (await request.json()) as { email?: string; password?: string };

  // Bounded, like every other call that leaves this process. An unbounded
  // `fetch` against an API that is reachable and silent does not fail — it
  // hangs, and here that means a "Signing in…" button that never comes back
  // and never says why. `lib/api/client.ts` carries the full argument.
  //
  // 15 s: authentication is one bcrypt verify and one insert into `access_log`.
  // Anything past that is not a slow login, it is a broken one.
  let upstream: Response;
  try {
    upstream = await fetch(`${API_ORIGIN}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: body.email ?? "", password: body.password ?? "" }),
      cache: "no-store",
      signal: AbortSignal.timeout(AUTH_TIMEOUT_MS),
    });
  } catch {
    // 503, not 401. The credentials were never judged, and telling an officer
    // their password is wrong when the API simply did not answer sends them to
    // reset a password that works.
    return NextResponse.json(
      { detail: "The API is not answering. Sign-in cannot be completed; this is not a problem with your credentials." },
      { status: 503 },
    );
  }

  if (!upstream.ok) {
    // The upstream deliberately does not say which of the two was wrong, and
    // neither do we. `api/routers/auth.py` records the failed attempt in
    // `access_log`; that is where a lockout decision would be made, not here.
    const detail = (await upstream.json().catch(() => null)) as { detail?: string } | null;
    return NextResponse.json(
      { detail: detail?.detail ?? "Sign-in failed." },
      { status: upstream.status },
    );
  }

  const pair = (await upstream.json()) as {
    access_token: string;
    refresh_token: string;
    expires_in: number;
    role: string;
  };

  const response = NextResponse.json({ role: pair.role });
  response.cookies.set(ACCESS_COOKIE, pair.access_token, cookieOptions(pair.expires_in));
  response.cookies.set(REFRESH_COOKIE, pair.refresh_token, cookieOptions(REFRESH_MAX_AGE));
  // The role is readable on purpose: navigation has to know whether to show the
  // dashboard link, and a role is not a credential. Every actual authorisation
  // decision is made by `require_role` on the server, which reads the signed
  // token and not this.
  response.cookies.set(ROLE_COOKIE, pair.role, cookieOptions(REFRESH_MAX_AGE, true));
  return response;
}

export async function DELETE(): Promise<NextResponse> {
  const response = NextResponse.json({ ok: true });
  for (const name of [ACCESS_COOKIE, REFRESH_COOKIE, ROLE_COOKIE]) {
    response.cookies.set(name, "", { ...cookieOptions(0), maxAge: 0 });
  }
  return response;
}
