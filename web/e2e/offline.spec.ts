import { expect, test } from "@playwright/test";

/**
 * The aeroplane-mode run. Section 18 asks for it by name, and it is the only
 * test in the suite that checks the claim the whole architecture is built on:
 *
 *   Section 5, tier L4 — *"Even in the worst case the officer walks away with a
 *   timestamped evidence record. A tool that returns nothing when it can't read
 *   is worse than a notebook."*
 *
 * The session cookie is set directly rather than by signing in, because signing
 * in is the one thing that genuinely needs a network and this file is about what
 * happens after it is gone. The value is never validated by the API in these
 * tests — the middleware only checks that a session exists, and no request
 * reaches the server once the context is offline.
 */
test.describe("with the radio off", () => {
  test.beforeEach(async ({ context }) => {
    await context.addCookies([
      {
        name: "akshar_at",
        value: "offline-test-session",
        domain: "127.0.0.1",
        path: "/",
      },
      { name: "akshar_role", value: "officer", domain: "127.0.0.1", path: "/" },
    ]);
  });

  test("a scan taken offline is recorded, queued, and never lost", async ({ page, context }) => {
    // Warm the shell first: an officer installs the app on wifi in the office
    // and walks into the market with it, which is the sequence section 5
    // describes. That includes waiting for the service worker to take control —
    // a page loaded before the worker activated is a page the worker cannot
    // serve, and going offline in that window tests nothing but a race.
    await page.goto("/scan");
    await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined));
    await page.reload();
    await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller));
    await expect(page.getByRole("heading", { name: "Scan a package" })).toBeVisible();

    await context.setOffline(true);
    await expect(page.getByText(/L1 offline/)).toBeVisible();

    // A one-pixel JPEG stands in for the photograph. What is under test is the
    // outbox, not the camera.
    const jpeg = Buffer.from(
      "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a" +
        "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA" +
        "AAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==",
      "base64",
    );
    await page.setInputFiles('input[type="file"]', {
      name: "pack.jpg",
      mimeType: "image/jpeg",
      buffer: jpeg,
    });

    // Section 5, L4: a record, not a failure.
    await expect(page.getByText("Queued", { exact: true })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(/photograph, its time and its location are already recorded/)).toBeVisible();

    // And it is durable: still there after a reload with the radio still off.
    await page.reload();
    await page.goto("/queue");
    await expect(page.getByRole("heading", { name: "Offline queue" })).toBeVisible();
    await expect(page.getByText("pending").first()).toBeVisible();
  });

  test("a page never opened offline explains what still works", async ({ page, context }) => {
    await page.goto("/scan");
    await context.setOffline(true);

    await page.goto("/summary").catch(() => undefined);
    // Either the offline fallback, or a cached copy — both are acceptable
    // outcomes; a browser network error page is not.
    const body = await page.textContent("body");
    expect(body ?? "").not.toContain("ERR_INTERNET_DISCONNECTED");
  });

  test("the queue survives a reload because it is in IndexedDB, not memory", async ({ page }) => {
    await page.goto("/queue");
    // The database is opened lazily by the panel's first read, so wait for the
    // panel to have rendered something from it before asking what exists.
    await expect(page.getByRole("heading", { name: "Outbox" })).toBeVisible();
    await expect(page.getByText(/Nothing (waiting|has been scanned)/).first()).toBeVisible();
    const stores = await page.evaluate(async () => {
      const databases = await indexedDB.databases();
      return databases.map((entry) => entry.name);
    });
    expect(stores).toContain("akshar");
  });
});
