import { expect, test } from "@playwright/test";

/**
 * The camera opens, and the picture actually arrives.
 *
 * This is a regression test for a reported bug with a silent failure mode:
 * `startCamera` assigned `videoRef.current.srcObject` from inside the click
 * handler, but the `<video>` was only rendered once `cameraOn` had already
 * flipped to true. The ref was therefore `null` at the moment of assignment, a
 * `if (videoRef.current)` guard swallowed it, and the element then mounted with
 * no source. The permission prompt appeared, the officer allowed it, and the
 * viewfinder stayed black. Nothing threw, nothing was logged, and no existing
 * test noticed — the button was present, enabled and clickable throughout.
 *
 * So the assertions here are deliberately not "the button exists". They are
 * that a real `MediaStream` reaches the element, that the element decodes a
 * frame from it, and that Capture is only enabled once it has — which is the
 * chain the bug broke in the middle of.
 *
 * `getUserMedia` is stubbed with a canvas `captureStream`, which is a genuine
 * `MediaStream` carrying a genuine video track. A plain mock object would be
 * rejected by `HTMLMediaElement.srcObject` and would test nothing.
 */
test.describe("the camera", () => {
  test.beforeEach(async ({ context, page }) => {
    await context.addCookies([
      { name: "akshar_at", value: "camera-test-session", domain: "127.0.0.1", path: "/" },
      { name: "akshar_role", value: "officer", domain: "127.0.0.1", path: "/" },
    ]);

    // `addInitScript` rather than `page.evaluate`, so the stub is installed
    // before any application code runs on every document in the page.
    await page.addInitScript(() => {
      const canvas = document.createElement("canvas");
      canvas.width = 640;
      canvas.height = 480;
      const context2d = canvas.getContext("2d");
      window.setInterval(() => {
        if (!context2d) return;
        context2d.fillStyle = `hsl(${Date.now() / 40} 60% 50%)`;
        context2d.fillRect(0, 0, canvas.width, canvas.height);
      }, 100);
      const stream = canvas.captureStream(10);
      // Parked on `window` so a test can ask the track itself whether it was
      // stopped, rather than inferring it from the element disappearing.
      (window as unknown as { __stream: MediaStream }).__stream = stream;
      Object.defineProperty(navigator, "mediaDevices", {
        configurable: true,
        value: {
          getUserMedia: async () => stream,
          enumerateDevices: async () => [],
        },
      });
    });
  });

  test("the stream reaches the viewfinder and a frame decodes", async ({ page }) => {
    await page.goto("/scan");
    await page.getByRole("button", { name: "Use camera" }).click();

    const video = page.locator("video");
    await expect(video).toBeVisible();

    // The assertion the bug would have failed. `videoWidth` is only non-zero
    // once a frame has been decoded from an attached source, so this covers
    // both the attachment and the playback in one check.
    await expect
      .poll(async () => video.evaluate((element: HTMLVideoElement) => element.videoWidth))
      .toBe(640);

    expect(await video.evaluate((element: HTMLVideoElement) => Boolean(element.srcObject))).toBe(
      true,
    );
    expect(await video.evaluate((element: HTMLVideoElement) => element.paused)).toBe(false);

    // Capture stays disabled until there is something to capture. Grabbing from
    // a video with `videoWidth === 0` produces a zero-sized canvas and a blob
    // the API rejects with an error about the upload rather than the camera.
    await expect(page.getByRole("button", { name: "Capture" })).toBeEnabled();
  });

  test("stopping releases the tracks rather than only hiding the element", async ({ page }) => {
    await page.goto("/scan");
    await page.getByRole("button", { name: "Use camera" }).click();
    await expect(page.locator("video")).toBeVisible();

    await page.getByRole("button", { name: "Stop camera" }).click();

    await expect(page.locator("video")).toHaveCount(0);

    // The element going away is the easy half. A viewfinder that disappears
    // while the track stays live leaves the phone's camera light on for the
    // rest of the shift, and the officer has no control left on screen to turn
    // it off — so the track is asked directly.
    await expect
      .poll(async () =>
        page.evaluate(() => {
          const [track] = (window as unknown as { __stream: MediaStream }).__stream.getVideoTracks();
          return track?.readyState ?? "gone";
        }),
      )
      .toBe("ended");
  });

  test("an insecure context is diagnosed as a URL problem, not a camera fault", async ({
    page,
  }) => {
    // The failure that will actually happen: an officer opens the app from a
    // phone at http://192.168.1.x:3100. Outside a secure context
    // `navigator.mediaDevices` is undefined, so the call throws before any
    // hardware is touched — and the fix is a URL, not a permission setting.
    await page.addInitScript(() => {
      Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: undefined });
      Object.defineProperty(window, "isSecureContext", { configurable: true, value: false });
    });

    await page.goto("/scan");
    await page.getByRole("button", { name: "Use camera" }).click();

    await expect(page.getByText("The camera did not open")).toBeVisible();
    await expect(page.getByText(/secure connection/)).toBeVisible();
    // The upload path is the way out, and it has to still be offered.
    await expect(page.getByText("Upload a photograph")).toBeVisible();
  });
});
