"use client";

import { useEffect, useRef, useState } from "react";
import type { DeclarationSet } from "@/lib/api/types";
import { millimetres } from "@/lib/format";

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
 */
const RED = "#dc2626";
const DASH = "#2563eb";

export function Overlay({
  src,
  declarations,
  className,
}: {
  src: string;
  declarations: DeclarationSet | null | undefined;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [ready, setReady] = useState(false);

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
        context.font = `${unit * 7}px ui-sans-serif, system-ui, sans-serif`;
        context.textBaseline = "bottom";

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

        for (const declaration of declarations?.declarations ?? []) {
          const box = declaration.box;
          if (!box) continue;
          context.strokeStyle = RED;
          context.lineWidth = unit;
          context.setLineDash([]);
          context.strokeRect(box.x, box.y, box.w, box.h);

          const caption = [
            declaration.field.replace(/_/g, " "),
            declaration.height_mm !== null && declaration.height_mm !== undefined
              ? millimetres(declaration.height_mm)
              : null,
          ]
            .filter(Boolean)
            .join(" · ");

          const width = context.measureText(caption).width + unit * 2;
          context.fillStyle = RED;
          context.fillRect(box.x, Math.max(0, box.y - unit * 9), width, unit * 9);
          context.fillStyle = "#ffffff";
          context.fillText(caption, box.x + unit, Math.max(unit * 8, box.y - unit));
        }

        setReady(true);
      })
      .catch(() => setReady(false));

    return () => {
      cancelled = true;
    };
  }, [src, declarations]);

  return (
    <figure className={className}>
      <canvas
        ref={canvasRef}
        className="w-full rounded-lg border border-border bg-surface-2"
        role="img"
        aria-label={
          declarations
            ? `The photograph with ${(declarations.declarations ?? []).length} declaration boxes marked in red and the principal display panel outlined.`
            : "The photograph."
        }
      />
      <figcaption className="mt-1 text-sm text-fg-muted">
        {ready ? (
          <>
            <span style={{ color: RED }}>▭</span> declaration, with its measured height ·{" "}
            <span style={{ color: DASH }}>▭</span> principal display panel
          </>
        ) : (
          "Rendering the photograph…"
        )}
      </figcaption>
    </figure>
  );
}
