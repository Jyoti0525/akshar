import { defineConfig, devices } from "@playwright/test";

/**
 * Section 18: *"Playwright E2E incl. aeroplane-mode offline run."*
 *
 * The offline run is the one that matters. Every other assertion here could be
 * made with a unit test; *"does the app still record an inspection with the
 * radio off"* cannot, and it is the claim the whole design rests on.
 *
 * The suite starts its own `next start`, so it runs against the production
 * build — which is the only build where the service worker exists.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  timeout: 60_000,
  use: {
    baseURL: process.env.AKSHAR_WEB_ORIGIN ?? "http://127.0.0.1:3100",
    trace: "retain-on-failure",
    // Section 11's 16 px floor and 44 px targets are sized for a phone held at
    // arm's length in a market, so that is what the suite runs on.
    ...devices["Pixel 7"],
  },
  webServer: {
    command: "npm run start -- --port 3100",
    url: "http://127.0.0.1:3100/login",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
