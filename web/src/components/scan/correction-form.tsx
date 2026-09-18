"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { apiFetch } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/alert";
import { Label, Select } from "@/components/ui/field";
import { fieldLabel } from "@/lib/format";
import type { Declaration, DeclarationSet } from "@/lib/api/types";

type FieldName = Declaration["field"];

/**
 * An officer override. Section 14: *"each of these is a labelled training
 * example produced by somebody already doing the job."*
 *
 * The two field lists come from `contracts/declarations.FieldName`, and the
 * order matters: `other` is last and is never preselected. Section 14 is
 * explicit that `other` must never be guessed and that `marketing_text` must
 * never be labelled `mrp`, and a form that defaults to a plausible answer is how
 * a hurried officer produces exactly that kind of label.
 */
const FIELDS: FieldName[] = [
  "mrp",
  "net_quantity",
  "mfg_date",
  "expiry_date",
  "manufacturer",
  "packer",
  "importer",
  "consumer_care",
  "country_of_origin",
  "generic_name",
  "batch",
  "marketing_text",
  "other",
];

export function CorrectionForm({
  scanId,
  declarations,
}: {
  scanId: string;
  declarations: DeclarationSet | null;
}) {
  const rows = declarations?.declarations ?? [];
  const [boxIndex, setBoxIndex] = useState<string>("");
  const [toField, setToField] = useState<string>("");

  const submit = useMutation({
    mutationFn: async () =>
      apiFetch(`/scans/${scanId}/corrections`, {
        method: "POST",
        body: {
          box_index: boxIndex === "" ? null : Number(boxIndex),
          from_field: boxIndex === "" ? null : (rows[Number(boxIndex)]?.field ?? null),
          to_field: toField,
        },
      }),
  });

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (toField) submit.mutate();
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="box">Which reading</Label>
          <Select id="box" value={boxIndex} onChange={(event) => setBoxIndex(event.target.value)}>
            <option value="">A declaration we missed entirely</option>
            {rows.map((declaration, index) => (
              <option key={index} value={index}>
                {fieldLabel(declaration.field)} — {declaration.text.slice(0, 40)}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="to">Should be</Label>
          <Select id="to" value={toField} onChange={(event) => setToField(event.target.value)} required>
            <option value="">Choose the correct field…</option>
            {FIELDS.map((field) => (
              <option key={field} value={field}>
                {fieldLabel(field)}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <div>
        <Button type="submit" disabled={!toField || submit.isPending}>
          {submit.isPending ? "Recording…" : "Record correction"}
        </Button>
      </div>

      {submit.isSuccess ? (
        <Alert tone="pass">
          Recorded as a new row. The scan is unchanged, and this correction becomes a training
          example.
        </Alert>
      ) : null}
      {submit.isError ? <Alert tone="fail">{(submit.error as Error).message}</Alert> : null}
    </form>
  );
}
