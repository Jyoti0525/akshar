"use client";

import { useEffect, useState } from "react";
import { counts } from "@/lib/offline/outbox";
import { Badge } from "./ui/badge";

/**
 * Section 5's tier, visible at all times.
 *
 * An officer needs to know *before* pressing the shutter whether this scan will
 * come back with a verdict or go into the outbox. Discovering it afterwards is
 * how someone walks out of a shop believing a pack passed.
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

  return (
    <Badge tone={online ? "pass" : "review"} glyph={false} title={online ? "L0 — online" : "L1 — offline; scans are queued"}>
      {online ? "L0 online" : "L1 offline"}
      {queued > 0 ? ` · ${queued} queued` : ""}
    </Badge>
  );
}
