import { expect, test } from "@playwright/test";
import { signInWithPlaceholder } from "./session-fixture";

/**
 * The failure the degradation ladder did not cover: a server that is reachable
 * and does not answer.
 *
 * Section 5's ladder is written around the radio being off. `fetch` rejects when
 * a host is unreachable, `ApiError` calls that status 0, and tier L1 queues the
 * scan. That path has a test of its own in `offline.spec.ts`.
 *
 * A **hung** server produces none of that. With a dead Postgres behind it the
 * API completes the TCP handshake and then blocks; `fetch` neither resolves nor
 * rejects, `capture()` awaits it forever, and the capture screen sits with
 * `busy` true. The officer sees a photograph that never became a verdict and
 * never became a queued scan either — no error, no record, nothing to retry.
 * That is the one outcome the whole ladder exists to make impossible, and it is
 * exactly what an officer reported as "the upload isn't working".
 *
 * `apiFetch` now gives every request a deadline and classifies its expiry as an
 * unusable network, which is what a silent server is. This test holds the
 * request open and asserts the scan is queued rather than lost.
 *
 * It is slow *by construction*: the deadline is 30 seconds, chosen against a
 * performance budget whose worst sanctioned server figure is 2000 ms, and the
 * point of the test is that the real deadline fires. Shortening it would mean
 * shortening the thing under test.
 */
test.describe("when the server answers the handshake and nothing else", () => {
  test.beforeEach(async ({ context }) => {
    await signInWithPlaceholder(context);
  });

  test("a scan against a silent server is queued, not lost", async ({ page }) => {
    // 30 s deadline, plus the page load, plus the queue assertion.
    test.setTimeout(90_000);

    // Held open, never fulfilled and never aborted — a socket that accepted the
    // request and went quiet. `route.fetch()` is deliberately not called: this
    // must not reach a real API, and it must not fail fast either.
    const hung: (() => void)[] = [];
    await page.route("**/api/v1/scans", async () => {
      await new Promise<void>((resolve) => hung.push(resolve));
    });

    await page.goto("/scan");
    await expect(page.getByRole("heading", { name: "Scan a package" })).toBeVisible();

    await page.getByLabel("Height of the side facing the camera").fill("15");

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

    // While it is in flight the control says so. This is the other half of the
    // same report: the camera path flipped its button to "Reading…" and the
    // upload path changed nothing, so a running scan and a dead button looked
    // identical.
    await expect(page.getByText("Reading…")).toBeVisible();

    // And when the deadline expires the scan is a record, not a loss.
    await expect(page.getByText("Queued", { exact: true })).toBeVisible({ timeout: 60_000 });

    // Release the held request so the route handler does not outlive the test.
    hung.forEach((resolve) => resolve());
  });
});
