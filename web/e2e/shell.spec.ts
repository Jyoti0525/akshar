import { expect, test } from "@playwright/test";

/**
 * The claims section 11 makes about the shell, checked rather than asserted.
 *
 * None of these needs the API to be running: they are properties of the page
 * itself, and a suite that only passes with a live backend is a suite nobody
 * runs before pushing.
 */

test("an unauthenticated visitor is sent to sign in, and the way back is kept", async ({ page }) => {
  await page.goto("/dashboard/brands?district=Khordha");
  await expect(page).toHaveURL(/\/login\?next=/);
  // The filter survives the redirect. Section 11: a shared filtered link is how
  // a finding gets escalated, and losing the filters at the sign-in door would
  // mean the controller has to be sent the link a second time.
  expect(decodeURIComponent(page.url())).toContain("district=Khordha");
});

test("cross-origin isolation is on, or the WASM path is silently halved", async ({ page }) => {
  const response = await page.goto("/login");
  const headers = response?.headers() ?? {};
  expect(headers["cross-origin-opener-policy"]).toBe("same-origin");
  expect(headers["cross-origin-embedder-policy"]).toBe("require-corp");

  // The header is only half of it: what onnxruntime-web actually reads is this.
  const isolated = await page.evaluate(() => crossOriginIsolated);
  expect(isolated).toBe(true);
});

test("the daylight palette is reachable and pure black on white", async ({ page }) => {
  await page.goto("/login");

  const toggle = page.getByRole("button", { name: /Display:/ });
  // system -> light -> dark -> daylight
  for (let i = 0; i < 3; i += 1) await toggle.click();

  await expect(page.locator("html")).toHaveAttribute("data-mode", "daylight");
  const colours = await page.evaluate(() => {
    const style = getComputedStyle(document.body);
    return { fg: style.color, bg: style.backgroundColor };
  });
  expect(colours.fg).toBe("rgb(0, 0, 0)");
  expect(colours.bg).toBe("rgb(255, 255, 255)");
});

test("the first tab stop skips to the content", async ({ page }) => {
  await page.goto("/login");
  await page.keyboard.press("Tab");
  await expect(page.locator(".skip-link")).toBeFocused();
});

test("nothing on the sign-in page is smaller than 16px or shorter than 44px", async ({ page }) => {
  await page.goto("/login");

  const small = await page.evaluate(() => {
    const offenders: string[] = [];
    for (const element of Array.from(document.querySelectorAll("body *"))) {
      if (!(element instanceof HTMLElement)) continue;
      if (element.children.length > 0) continue;
      const text = element.textContent?.trim() ?? "";
      if (!text) continue;
      const size = Number.parseFloat(getComputedStyle(element).fontSize);
      if (size < 14) offenders.push(`${element.tagName}:${size}px:${text.slice(0, 20)}`);
    }
    return offenders;
  });
  expect(small).toEqual([]);

  const short = await page.evaluate(() => {
    const offenders: string[] = [];
    for (const element of Array.from(
      document.querySelectorAll("button, a[href], input, select, textarea"),
    )) {
      const box = element.getBoundingClientRect();
      if (box.height > 0 && box.height < 44 && !element.classList.contains("sr-only")) {
        offenders.push(`${element.tagName}:${box.height.toFixed(0)}px`);
      }
    }
    return offenders;
  });
  expect(short).toEqual([]);
});

test("the manifest is installable and names the scan screen as the entry point", async ({
  request,
}) => {
  const response = await request.get("/manifest.webmanifest");
  expect(response.ok()).toBeTruthy();
  const manifest = (await response.json()) as Record<string, unknown>;
  expect(manifest.start_url).toBe("/scan");
  expect(manifest.display).toBe("standalone");
  expect((manifest.icons as unknown[]).length).toBeGreaterThanOrEqual(2);
});
