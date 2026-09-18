import type { BrowserContext } from "@playwright/test";

/**
 * A session for tests that are not about sessions.
 *
 * The camera and the outbox both live behind the sign-in gate, so their specs
 * have to arrive holding something. They used to hold the string
 * `"camera-test-session"`, which worked only because `middleware.ts` checked
 * that the cookie was *present* and never that it was a token — the same defect
 * that showed an officer "not found on the server" when their session had
 * simply expired. Fixing that broke five tests, which is the fix working: an
 * unreadable token is a dead token.
 *
 * So these are real JWTs in shape and fiction in substance. The `exp` is far
 * enough out that the gate carries on without renewing; the signature is
 * nonsense, which the API rejects exactly as it rejected the old placeholder —
 * these pages render their shell without it, which is what the specs measure.
 */
const ORIGIN_HOST = "127.0.0.1";

function token(kind: "access" | "refresh", secondsFromNow: number): string {
  const encode = (value: object) => Buffer.from(JSON.stringify(value)).toString("base64url");
  return [
    encode({ alg: "HS256", typ: "JWT" }),
    encode({
      sub: "00000000-0000-0000-0000-000000000000",
      role: "officer",
      typ: kind,
      exp: Math.floor(Date.now() / 1000) + secondsFromNow,
    }),
    Buffer.from("not-a-signature").toString("base64url"),
  ].join(".");
}

/** Valid for an hour — longer than any run, shorter than anything that could
 *  outlive the test and confuse a later one. */
export function placeholderAccessToken(): string {
  return token("access", 3600);
}

/** Five minutes dead. The gate should reach for the refresh token on seeing
 *  this, and sign the officer out only if that one is dead too. */
export function expiredAccessToken(): string {
  return token("access", -300);
}

export async function signInWithPlaceholder(context: BrowserContext): Promise<void> {
  await context.addCookies([
    { name: "akshar_at", value: placeholderAccessToken(), domain: ORIGIN_HOST, path: "/" },
    { name: "akshar_role", value: "officer", domain: ORIGIN_HOST, path: "/" },
  ]);
}
