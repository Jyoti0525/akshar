import { expect, test } from "@playwright/test";
import { expiredAccessToken } from "./session-fixture";

/**
 * The session gate, checked at the only level where it is real.
 *
 * `src/middleware.ts` decides three things on every navigation — carry on,
 * renew, or sign out — and none of them can be unit tested here: there is no TS
 * test runner in this project, and the interesting part is not a function
 * anyway. It is what a browser ends up holding after a round trip.
 *
 * The first test needs no API, for the reason `shell.spec.ts` gives: a suite
 * that only passes with a live backend is a suite nobody runs. The second one
 * does, and skips with a reason rather than passing vacuously.
 */

const ACCESS = "akshar_at";
const REFRESH = "akshar_rt";
const ROLE = "akshar_role";

const EMAIL = process.env.AKSHAR_E2E_EMAIL ?? "officer@akshar.demo";
const PASSWORD = process.env.AKSHAR_E2E_PASSWORD ?? "akshar-demo";

test("a dead session is sent to sign in, not silently admitted", async ({ context, page }) => {
  // Both halves expired. Until 2026-09-18 the gate checked only that the
  // cookies were *present*, so this walked straight through and the officer met
  // a page that told them the record was not on the server.
  //
  // The signature on these is nonsense on purpose. The gate reads `exp`
  // **without verifying the signature** — deliberately, because that reading
  // decides only whether to spend a round trip renewing, never what anyone is
  // allowed to do — so a garbage signature is exactly what it should ignore,
  // and a test that signed these properly would need the API's secret and would
  // prove less.
  const dead = expiredAccessToken();
  await context.addCookies(
    [ACCESS, REFRESH].map((name) => ({
      name,
      value: dead,
      url: "http://127.0.0.1:3100",
    })),
  );

  await page.goto("/scan/01a0b1fb-0000-7000-8000-000000000000");
  await expect(page).toHaveURL(/\/login\?next=/);
  expect(decodeURIComponent(page.url())).toContain("/scan/01a0b1fb");

  // And the dead cookies are gone, so the next request does not repeat the
  // whole dance — and so a stale token cannot be presented again.
  const remaining = await context.cookies();
  for (const name of [ACCESS, REFRESH, ROLE]) {
    expect(remaining.find((cookie) => cookie.name === name)?.value ?? "").toBe("");
  }
});

test("an expired access token is renewed, not reported as a lost record", async ({
  context,
  page,
}) => {
  const signIn = await context.request
    .post("/api/session", { data: { email: EMAIL, password: PASSWORD }, failOnStatusCode: false })
    .catch(() => null);
  test.skip(
    signIn === null || !signIn.ok(),
    "needs a live API with the demo accounts seeded (api/demo.py)",
  );

  expect(
    (await context.cookies()).find((cookie) => cookie.name === ACCESS)?.value,
    "sign-in should have written an access cookie",
  ).toBeTruthy();

  // Age the access token by hand. Everything else about the session is real:
  // the refresh token is live, which is the whole situation — an officer who
  // left a tab open over lunch, holding a credential that would renew it.
  // Held in a variable, not re-derived: the helper stamps `exp` from the clock,
  // so calling it twice gives two different strings and comparing against the
  // second would assert nothing.
  const aged = expiredAccessToken();
  await context.addCookies([{ name: ACCESS, value: aged, url: "http://127.0.0.1:3100" }]);

  await page.goto("/queue");

  await expect(page).not.toHaveURL(/\/login/);
  const after = (await context.cookies()).find((cookie) => cookie.name === ACCESS)?.value ?? "";
  expect(after, "the gate should have written a fresh access token").toBeTruthy();
  expect(after, "the dead token should have been replaced").not.toBe(aged);

  // The live one from sign-in is *not* a useful thing to compare against:
  // `create_token` stamps `iat` and `exp` in whole seconds, so a renewal inside
  // the same second as the login mints a byte-identical token. What has to be
  // true is that whatever is in the jar now is alive.
  const claims = JSON.parse(Buffer.from(after.split(".")[1] ?? "", "base64url").toString()) as {
    exp: number;
  };
  expect(claims.exp).toBeGreaterThan(Date.now() / 1000);
});
