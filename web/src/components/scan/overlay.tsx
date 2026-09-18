"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { DeclarationSet, Verdict } from "@/lib/api/types";
import { fieldLabel, millimetres } from "@/lib/format";

/**
 * Section 11: *"The annotated image shows the MRP box in red with its measured
 * height and the PDP outlined dashed."*
 *
 * Drawn in the browser over the photograph the officer just took, rather than
 * fetched as a rendered PNG, for one reason: it has to be on screen with the
 * verdict, and the annotated copy is produced by a worker
 * (`evidence/annotate.py`) some hundreds of milliseconds later. The server-side
 * drawing is the one that goes into the report and the evidence bucket; this one
 * is the one the officer looks at while still holding the packet.
 *
 * The two agree because they take the same coordinates from the same
 * `DeclarationSet`. Boxes are in original-photograph pixels — section 8b keeps
 * the transform so every box maps back onto the photograph — so the only work
 * here is the scale factor between the natural size and the rendered size.
 *
 * ---------------------------------------------------------------------------
 * WHY EVERY BOX USED TO LOOK THE SAME, AND WHY THAT WAS WRONG
 * ---------------------------------------------------------------------------
 * Until 2026-09-19 this drew every declaration in one weight of red with a
 * solid caption plate, captioned by `field.replace(/_/g, " ")`. On a real pack
 * that is forty-odd identical boxes, most of them `other` — the unclassified
 * text lines the OCR found and no rule ever looked at — sitting on top of the
 * three or four the verdict was actually built from, with their captions
 * overlapping each other. It is a picture of everything the pipeline saw. It is
 * not evidence, because evidence is a claim about *which* marks on the pack
 * support the finding.
 *
 * So the drawing now has three weights, and they mean something:
 *
 *   CITED      a field a FAIL or REVIEW verdict names. Heavy stroke in the
 *              status colour, captioned. This is what the notice rests on.
 *   READ       a field that was classified and either passed or was not cited.
 *              Thin, slate, captioned quietly. The pack declares it; nothing is
 *              alleged about it.
 *   UNREAD     `other`. Hairline, and HIDDEN by default behind a checkbox,
 *              because a line of text nobody classified is a fact about the
 *              recogniser, not about the package.
 *
 * Nothing is deleted. Every box is one click away, and the exported record and
 * the declaration table below still list all of them — an exhibit that quietly
 * dropped what it had seen would be a worse document than a cluttered one.
 */
const STROKE = {
  fail: "#b91c1c",
  review: "#b45309",
  read: "#475569",
  unread: "#94a3b8",
} as const;
const DASH = "#2563eb";

type Weight = "fail" | "review" | "read" | "unread";

/** Which fields a verdict actually pointed at, and how hard. */
function citations(verdicts: readonly Verdict[] | null | undefined): Map<string, Weight> {
  const cited = new Map<string, Weight>();
  for (const verdict of verdicts ?? []) {
    if (!verdict.field) continue;
    // A suppressed verdict is one the engine decided a more specific rule
    // already answers. Drawing it heavy would put two red boxes on the pack for
    // one finding.
    if (verdict.suppressed_by) continue;
    if (verdict.status === "FAIL") cited.set(verdict.field, "fail");
    else if (verdict.status === "REVIEW" && cited.get(verdict.field) !== "fail")
      cited.set(verdict.field, "review");
  }
  return cited;
}

/**
 * Keep captions off each other.
 *
 * Declarations on a label are stacked a few millimetres apart, so their
 * captions — drawn above each box — collide constantly, and two overlapping
 * labels are less readable than one. Each caption is placed above its box if
 * that space is free, otherwise just inside the top of the box, otherwise
 * nudged down until it is clear of everything already placed.
 */
function place(
  taken: { x: number; y: number; w: number; h: number }[],
  x: number,
  boxTop: number,
  w: number,
  h: number,
) {
  const collides = (y: number) =>
    taken.some(
      (other) =>
        x < other.x + other.w && x + w > other.x && y < other.y + other.h && y + h > other.y,
    );
  for (const y of [boxTop - h, boxTop + 1, boxTop + h + 1, boxTop + 2 * h + 2]) {
    if (y >= 0 && !collides(y)) {
      taken.push({ x, y, w, h });
      return y;
    }
  }
  const fallback = Math.max(0, boxTop - h);
  taken.push({ x, y: fallback, w, h });
  return fallback;
}

export function Overlay({
  src,
  declarations,
  verdicts,
  className,
}: {
  src: string;
  declarations: DeclarationSet | null | undefined;
  verdicts?: readonly Verdict[] | null;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [ready, setReady] = useState(false);
  const [showUnread, setShowUnread] = useState(false);

  const cited = useMemo(() => citations(verdicts), [verdicts]);

  const counts = useMemo(() => {
    let heavy = 0;
    let read = 0;
    let unread = 0;
    for (const declaration of declarations?.declarations ?? []) {
      if (!declaration.box) continue;
      if (declaration.field === "other") unread += 1;
      else if (cited.has(declaration.field)) heavy += 1;
      else read += 1;
    }
    return { heavy, read, unread };
  }, [declarations, cited]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const image = new Image();
    image.decoding = "async";
    image.src = src;

    let cancelled = false;
    void image
      .decode()
      .then(() => {
        if (cancelled) return;
        const context = canvas.getContext("2d");
        if (!context) return;

        canvas.width = image.naturalWidth;
        canvas.height = image.naturalHeight;
        context.drawImage(image, 0, 0);

        // Line width scales with the photograph, or a 2 px stroke vanishes on a
        // 3000 px frame shown 400 px wide.
        const unit = Math.max(2, Math.round(image.naturalWidth / 400));
        context.lineJoin = "round";
        context.textBaseline = "top";

        const polygon = declarations?.geometry?.pdp_polygon ?? null;
        if (polygon && polygon.length >= 3) {
          context.save();
          context.strokeStyle = DASH;
          context.lineWidth = unit;
          context.setLineDash([unit * 4, unit * 3]);
          context.beginPath();
          polygon.forEach((point, index) => {
            const [x, y] = point as unknown as [number, number];
            if (index === 0) context.moveTo(x, y);
            else context.lineTo(x, y);
          });
          context.closePath();
          context.stroke();
          context.restore();
        }

        const drawn = (declarations?.declarations ?? []).filter((declaration) => {
          if (!declaration.box) return false;
          return declaration.field !== "other" || showUnread;
        });

        // Heaviest last, so a cited box is never drawn under a quiet one.
        const weightOf = (field: string): Weight =>
          field === "other" ? "unread" : (cited.get(field) ?? "read");
        const order: Record<Weight, number> = { unread: 0, read: 1, review: 2, fail: 3 };
        drawn.sort((a, b) => order[weightOf(a.field)] - order[weightOf(b.field)]);

        const taken: { x: number; y: number; w: number; h: number }[] = [];
        for (const declaration of drawn) {
          const box = declaration.box!;
          const weight = weightOf(declaration.field);
          const heavy = weight === "fail" || weight === "review";

          context.save();
          context.strokeStyle = STROKE[weight];
          context.lineWidth = heavy ? unit * 1.5 : weight === "read" ? unit * 0.75 : unit * 0.4;
          context.setLineDash(weight === "unread" ? [unit * 2, unit * 2] : []);
          context.globalAlpha = weight === "unread" ? 0.45 : 1;
          context.strokeRect(box.x, box.y, box.w, box.h);
          context.restore();

          // An unclassified line gets no caption. "Unclassified text" forty
          // times is the clutter itself, and the box already says where it is.
          if (weight === "unread") continue;

          const caption = [
            fieldLabel(declaration.field),
            declaration.height_mm !== null && declaration.height_mm !== undefined
              ? millimetres(declaration.height_mm)
              : null,
          ]
            .filter(Boolean)
            .join(" · ");

          const size = heavy ? unit * 7 : unit * 5.5;
          context.font = `${heavy ? "600 " : ""}${size}px ui-sans-serif, system-ui, sans-serif`;
          const plateW = context.measureText(caption).width + unit * 2;
          const plateH = size + unit * 1.5;
          const y = place(taken, box.x, box.y, plateW, plateH);

          context.save();
          context.globalAlpha = heavy ? 1 : 0.85;
          context.fillStyle = STROKE[weight];
          context.fillRect(box.x, y, plateW, plateH);
          context.fillStyle = "#ffffff";
          context.fillText(caption, box.x + unit, y + unit * 0.6);
          context.restore();
        }

        setReady(true);
      })
      .catch(() => setReady(false));

    return () => {
      cancelled = true;
    };
  }, [src, declarations, cited, showUnread]);

  return (
    <figure className={className}>
      <canvas
        ref={canvasRef}
        className="w-full rounded-lg border border-border bg-surface-2"
        role="img"
        aria-label={
          declarations
            ? `The photograph. ${counts.heavy} declaration${counts.heavy === 1 ? "" : "s"} ` +
              `the findings rest on are outlined heavily, ${counts.read} further declaration` +
              `${counts.read === 1 ? " is" : "s are"} outlined thinly, and the principal ` +
              `display panel is outlined with a dashed line.`
            : "The photograph."
        }
      />
      <figcaption className="mt-1 space-y-1 text-sm text-fg-muted">
        {ready ? (
          <>
            <p>
              <span style={{ color: STROKE.fail }}>▬</span> what a finding rests on ·{" "}
              <span style={{ color: STROKE.read }}>▭</span> read and not disputed ·{" "}
              <span style={{ color: DASH }}>▭</span> principal display panel
            </p>
            {counts.unread > 0 ? (
              <label className="inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={showUnread}
                  onChange={(event) => setShowUnread(event.target.checked)}
                  className="h-4 w-4 accent-brand"
                />
                Also outline the {counts.unread} line{counts.unread === 1 ? "" : "s"} of text the
                system could not classify. They are part of the record either way.
              </label>
            ) : null}
          </>
        ) : (
          "Rendering the photograph…"
        )}
      </figcaption>
    </figure>
  );
}
