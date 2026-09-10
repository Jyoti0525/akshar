"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * The rear camera, and an honest account of every way it fails to open.
 *
 * ---------------------------------------------------------------------------
 * THE BUG THIS REPLACES
 * ---------------------------------------------------------------------------
 * The previous version assigned `videoRef.current.srcObject = stream` inside the
 * click handler, and the `<video>` was only rendered once `cameraOn` had flipped
 * to true. So at the moment of assignment the element did not exist, the ref was
 * `null`, the guard silently skipped the assignment — and then the element
 * mounted with no source. The permission prompt appeared, the officer allowed
 * it, and they got a black rectangle. Nothing threw and nothing was logged.
 *
 * The stream is therefore state, not a ref side-effect: it is attached by an
 * effect that runs after the element exists, which is the only ordering React
 * guarantees.
 *
 * ---------------------------------------------------------------------------
 * WHY THE DIAGNOSIS IS SPECIFIC
 * ---------------------------------------------------------------------------
 * "The camera is not available" is true of all six failures below and useful for
 * none of them. The one that will actually happen — an officer opening the app
 * on a phone at `http://192.168.1.x:3000` — is not a camera problem at all:
 * outside a secure context `navigator.mediaDevices` is `undefined`, so the call
 * throws a TypeError before any hardware is touched, and the fix is a URL, not a
 * setting. That message has to say so or the device gets blamed.
 */

export type CameraState = "idle" | "starting" | "on" | "error";

/** How long to wait on `getUserMedia` before saying something.
 *
 *  The specification puts no bound on it: while a permission prompt is open the
 *  promise is simply pending, and if the prompt never appears — a policy block,
 *  an embedded webview, a prompt opened behind another window — it stays pending
 *  for ever. A UI that shows nothing at all in that case is indistinguishable
 *  from a dead button, which is exactly what it was reported as. */
const PROMPT_TIMEOUT_MS = 20_000;

function diagnose(error: unknown): string {
  // Checked first because it is not really an error about the camera, and
  // because it is the one that will happen on a phone. `mediaDevices` is only
  // exposed in a secure context: https, or localhost on the same machine.
  if (typeof window !== "undefined" && !window.isSecureContext) {
    return `Browsers only allow camera access over a secure connection, and this page is on ${window.location.origin}. Open it over https, or on this machine at http://localhost:3000. Uploading a photograph works either way and runs the identical pipeline.`;
  }

  const name = error instanceof DOMException ? error.name : "";
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return "Camera access was refused for this site. Allow it from the padlock or the camera icon in the address bar, then press Use camera again.";
    case "NotFoundError":
    case "DevicesNotFoundError":
      return "No camera was found on this device. Upload a photograph instead — the pipeline is identical.";
    case "NotReadableError":
    case "TrackStartError":
      return "Another application is holding the camera. Close it — a video call is the usual culprit — and try again.";
    case "OverconstrainedError":
      return "This camera cannot supply the requested resolution, and the fallback also failed. Upload a photograph instead.";
    case "AbortError":
      return "The camera stopped before it started. Try again, or upload a photograph.";
    default:
      return "The camera could not be opened. Upload a photograph instead — the pipeline is identical.";
  }
}

export function useCamera() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [state, setState] = useState<CameraState>("idle");
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Attach after render, when the element is guaranteed to exist. `play()` is
  // awaited and its rejection swallowed on purpose: iOS rejects it if the tab
  // loses focus mid-start, the tracks are live regardless, and an unhandled
  // rejection in the console helps nobody standing in a shop.
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !stream) return;
    video.srcObject = stream;
    void video.play().catch(() => undefined);
    return () => {
      video.srcObject = null;
    };
  }, [stream]);

  // One unmount cleanup for the whole hook. Without it the camera light stays
  // on after the officer navigates away, which is both alarming and a battery
  // cost on a device that has to last a shift.
  useEffect(
    () => () => {
      stream?.getTracks().forEach((track) => track.stop());
    },
    [stream],
  );

  const start = useCallback(async () => {
    setError(null);
    setState("starting");

    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setError(diagnose(new TypeError("mediaDevices unavailable")));
      setState("error");
      return;
    }

    // The rear camera, and as much resolution as the device will give. Section
    // 18b measured 4.9-11.7 px/mm on the ruler corpus against a premise of ~24;
    // on a phone that gap is closed by filling the frame with the pack, not by
    // asking for a larger sensor.
    const ideal: MediaStreamConstraints = {
      video: { facingMode: { ideal: "environment" }, width: { ideal: 3000 } },
      audio: false,
    };

    let timer: ReturnType<typeof setTimeout> | undefined;
    const deadline = new Promise<never>((_, reject) => {
      timer = setTimeout(
        () => reject(new DOMException("permission prompt timed out", "AbortError")),
        PROMPT_TIMEOUT_MS,
      );
    });

    const open = async (): Promise<MediaStream> => {
      try {
        return await navigator.mediaDevices.getUserMedia(ideal);
      } catch (caught) {
        // A laptop with one fixed webcam and a hard resolution ceiling reports
        // OverconstrainedError even for `ideal` constraints on some drivers.
        // Any camera beats none, so ask again for the plainest possible one.
        if (caught instanceof DOMException && caught.name === "OverconstrainedError") {
          return await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        }
        throw caught;
      }
    };

    try {
      const opened = await Promise.race([open(), deadline]);
      setStream(opened);
      setState("on");
    } catch (caught) {
      setError(
        caught instanceof DOMException && caught.name === "AbortError"
          ? "The browser is still waiting for permission to use the camera. Look for a prompt in the address bar — it can open behind this window — or upload a photograph instead."
          : diagnose(caught),
      );
      setState("error");
    } finally {
      clearTimeout(timer);
    }
  }, []);

  const stop = useCallback(() => {
    setStream((current) => {
      current?.getTracks().forEach((track) => track.stop());
      return null;
    });
    setState("idle");
    setError(null);
  }, []);

  /** A JPEG of the current frame, at the quality `evidence/redact.encode_jpeg`
   *  uses, so the bytes the officer sees and the bytes stored as evidence are
   *  the same. */
  const grab = useCallback(async (): Promise<Blob | null> => {
    const video = videoRef.current;
    // `videoWidth` is 0 until the first frame has decoded. Capturing then gives
    // a zero-sized canvas and a blob the API rejects with a confusing error, so
    // the button that calls this is disabled until `ready` below is true.
    if (!video || !video.videoWidth || !video.videoHeight) return null;

    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);
    return new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
  }, []);

  return { videoRef, state, error, start, stop, grab, live: stream !== null };
}
