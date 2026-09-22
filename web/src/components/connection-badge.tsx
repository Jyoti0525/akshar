"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { counts } from "@/lib/offline/outbox";
import { cn } from "@/lib/cn";

/**
 * Section 5's tier, visible at all times — and the way into the outbox.
 *
 * An officer needs to know *before* pressing the shutter whether this scan will
 * come back with a verdict or go into the outbox. Discovering it afterwards is
 * how someone walks out of a shop believing a pack passed.
 *
 * ---------------------------------------------------------------------------
 * TWO CHANGES FROM THE VERSION THAT SAT BESIDE A "QUEUE" TAB
 * ---------------------------------------------------------------------------
 * **It is the link now.** This badge already carries the tier and the queue
 * depth, so a separate top-level Queue tab beside it published the same fact
 * twice. Pressing the badge goes to `/queue`, which is the screen that answers
 * the question the badge raises.
 *
 * **Online is no longer green.** It used to render with `tone="pass"`, which is
 * the PASS verdict colour — the same green that means "this package complies",
 * sitting in the masthead above a verdict. Green there is a claim about the
 * label, and connectivity is not a claim about the label. Being online is the
 * unremarkable case and now looks it: neutral chrome, with a small live dot.
 * Amber is kept for offline and for a non-empty queue, which are the two states
 * that are actually owed attention — and in both the *word* carries the state,
 * so the colour is never the only cue.
 */
export function ConnectionBadge() {
  const [online, setOnline] = useState(true);
  const [queued, setQueued] = useState(0);

  useEffect(() => {
    const refresh = () => {
      setOnline(navigator.onLine);
      void counts().then((c) => setQueued(c.pending + c.sending + c.failed));
    };
    refresh();
    window.addEventListener("online", refresh);
    window.addEventListener("offline", refresh);
    window.addEventListener("akshar:synced", refresh);
    return () => {
      window.removeEventListener("online", refresh);
      window.removeEventListener("offline", refresh);
      window.removeEventListener("akshar:synced", refresh);
    };
  }, []);

  const attention = !online || queued > 0;
  const tier = online ? "L0" : "L1";
  const word = online ? "online" : "offline";

  return (
    <Link
      href="/queue"
      title={
        online
          ? `Tier L0 — online. ${queued > 0 ? `${queued} scan(s) still queued.` : "Nothing queued."}`
          : `Tier L1 — offline. Scans are being queued${queued > 0 ? `; ${queued} waiting` : ""}.`
      }
      className={cn(
        "flex h-touch items-center gap-2 rounded-md border px-2.5 text-sm font-medium transition-colors sm:px-3",
        attention
          ? "border-review bg-review-bg text-review-fg hover:bg-review-bg/70"
          : "border-border bg-surface-2 text-fg-muted hover:text-fg",
      )}
    >
      <span
        aria-hidden="true"
        className={cn("h-2 w-2 shrink-0 rounded-full", online ? "bg-pass" : "bg-review")}
      />
      {/* The tier code is monospaced because L0/L1 put a letter beside a digit,
          and a proportional zero next to a capital O is the one place this app
          can afford a slashed zero. */}
      {/*
        One element holding "L1 offline", not two siblings separated by a flex
        gap. The gap is a visual space and not a textual one, so two spans read
        as `L1offline` to anything that consumes text rather than pixels — a
        screen reader, a text search, `getByText`. The tier keeps its own inner
        span so it can stay monospaced.

        The word is shown at every width, including a phone. It was behind
        `hidden sm:inline` to save masthead room, and that was a false economy:
        the phone IS the device section 5 is written for, and an officer who
        sees only `L1` has been told the tier in a code they have no reason to
        know. "offline" is the part that means anything. The room came back when
        the navigation moved to its own row below the brand.
      */}
      <span>
        <span className="numeric">{tier}</span> {word}
      </span>
      {queued > 0 ? (
        <span className="numeric font-semibold">
          <span aria-hidden="true"> · </span>
          {queued}
          <span className="sr-only"> scans queued</span>
        </span>
      ) : null}
    </Link>
  );
}
