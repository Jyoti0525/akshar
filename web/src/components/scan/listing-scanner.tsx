"use client";

import Link from "next/link";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { scanListing } from "@/lib/scan/engine";
import { VerdictHeader } from "./verdict-header";
import { RuleRows } from "./rule-rows";
import { DeclarationTable } from "./declaration-table";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Input, Label, Select, Textarea } from "@/components/ui/field";
import type { ScanResponse } from "@/lib/api/types";

const CATEGORIES = ["", "food", "cosmetics", "cement", "electronics", "footwear", "household"];

export function ListingScanner() {
  const [text, setText] = useState("");
  const [category, setCategory] = useState("");
  const [district, setDistrict] = useState("");

  const run = useMutation<ScanResponse>({
    mutationFn: () => scanListing(text, { category: category || undefined, district: district || undefined }),
  });

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (text.trim()) run.mutate();
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="listing">Listing text</Label>
            <Textarea
              id="listing"
              rows={10}
              required
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder={"MRP ₹449.00 (incl. of all taxes)\nNet Qty: 300 ml\nMfd: 07/2026\nMarketed by …"}
            />
            <p className="text-sm text-fg-muted">
              This channel needs a network — there is no model to run locally and the rules run on
              the server.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="listing-category">Category</Label>
              <Select
                id="listing-category"
                value={category}
                onChange={(event) => setCategory(event.target.value)}
              >
                {CATEGORIES.map((value) => (
                  <option key={value} value={value}>
                    {value === "" ? "Not stated" : value}
                  </option>
                ))}
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="listing-district">District</Label>
              <Input
                id="listing-district"
                value={district}
                onChange={(event) => setDistrict(event.target.value)}
                placeholder="Defaults to your posting"
              />
            </div>
          </div>

          <div>
            <Button type="submit" disabled={run.isPending || text.trim().length === 0}>
              {run.isPending ? "Checking…" : "Check the listing"}
            </Button>
          </div>
        </form>
      </Card>

      {run.isError ? <Alert tone="fail">{(run.error as Error).message}</Alert> : null}

      {run.data ? (
        <div className="flex flex-col gap-4">
          <VerdictHeader scan={run.data} />
          <RuleRows verdicts={run.data.verdicts} />
          <Card>
            <CardTitle>What was extracted</CardTitle>
            <div className="mt-3">
              <DeclarationTable declarations={run.data.declarations ?? null} />
            </div>
          </Card>
          <div>
            <Button asChild variant="outline">
              <Link href={`/scan/${run.data.id}`}>Open the full record</Link>
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
