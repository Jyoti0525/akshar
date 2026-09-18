import { Table, THead, TR, TH, TD, Num, Empty } from "@/components/ui/table";
import { fieldLabel, millimetres, percent } from "@/lib/format";
import type { DeclarationSet } from "@/lib/api/types";

/**
 * What the pipeline actually read, before any rule was applied.
 *
 * Section 3: *"Extraction and decision stay separate."* Showing them separately
 * matters to the officer too: when a verdict looks wrong, the first question is
 * whether the rule is wrong or the reading is, and this table is the only place
 * that can answer it.
 *
 * `height_mm` is blank rather than zero when no scale was recovered. Section 8b:
 * `NO_DATA`, never a guess — and a zero in a millimetre column of an enforcement
 * record is a guess that reads as a measurement.
 */
export function DeclarationTable({ declarations }: { declarations: DeclarationSet | null }) {
  const rows = declarations?.declarations ?? [];

  return (
    <Table>
      <THead>
        <TR>
          <TH>Field</TH>
          <TH>Text</TH>
          <TH>Script</TH>
          <TH className="text-right">Height</TH>
          <TH className="text-right">Scale</TH>
          <TH className="text-right">OCR</TH>
          <TH className="text-right">Field</TH>
        </TR>
      </THead>
      <tbody>
        {rows.length === 0 ? (
          <Empty colSpan={7}>
            Nothing was read from this photograph. The record, its time and its location still
            stand as evidence.
          </Empty>
        ) : (
          rows.map((declaration, index) => (
            <TR key={`${declaration.field}-${index}`}>
              <TD className="font-medium">{fieldLabel(declaration.field)}</TD>
              <TD lang={declaration.script === "devanagari" ? "hi" : "en"}>{declaration.text}</TD>
              <TD className="text-fg-muted">{declaration.script}</TD>
              <Num
                title={
                  declaration.height_mm_tolerance
                    ? `±${declaration.height_mm_tolerance.toFixed(2)} mm`
                    : undefined
                }
              >
                {declaration.height_mm === null || declaration.height_mm === undefined ? (
                  <span className="text-fg-muted" title="No scale was recovered for this frame.">
                    no scale
                  </span>
                ) : (
                  millimetres(declaration.height_mm)
                )}
              </Num>
              <Num>{declaration.scale_tier ?? "—"}</Num>
              <Num>{percent(declaration.ocr_confidence, 0)}</Num>
              <Num>{percent(declaration.field_confidence, 0)}</Num>
            </TR>
          ))
        )}
      </tbody>
    </Table>
  );
}
