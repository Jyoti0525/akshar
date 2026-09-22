"use client";

import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { apiFetch } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Input, Label, Select } from "@/components/ui/field";
import { count } from "@/lib/format";
import type { BulkAccepted, BulkJobStatus } from "@/lib/api/types";

const MAX_FILES = 500;
const CATEGORIES = ["", "food", "cosmetics", "cement", "electronics", "footwear", "household"];

export function BulkUploader() {
  const [files, setFiles] = useState<File[]>([]);
  const [district, setDistrict] = useState("");
  const [category, setCategory] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);

  const start = useMutation<BulkAccepted>({
    mutationFn: async () => {
      const form = new FormData();
      for (const file of files) form.append("images", file, file.name);
      if (district) form.set("district", district);
      if (category) form.set("category", category);
      return apiFetch<BulkAccepted>("/scans/bulk", { method: "POST", form });
    },
    onSuccess: (accepted) => setJobId(String(accepted.job_id)),
  });

  /**
   * The one place in the application that polls.
   *
   * Section 11's "nothing auto-refreshes" is a rule about *reading figures* on
   * the dashboard, and it is kept everywhere else. A job counter is the opposite
   * case: it is a progress indicator with nothing to read aloud, and it stops
   * polling the moment the job finishes.
   */
  const job = useQuery<BulkJobStatus>({
    queryKey: ["bulk", jobId],
    enabled: jobId !== null,
    queryFn: () => apiFetch<BulkJobStatus>(`/scans/bulk/${jobId}`),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2000 : false),
  });

  const tooMany = files.length > MAX_FILES;

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (files.length > 0 && !tooMany) start.mutate();
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="files">Photographs</Label>
            <input
              // Extensions stamp `fdprocessedid` here before hydration; see ui/button.tsx.
              suppressHydrationWarning
              id="files"
              type="file"
              accept="image/*"
              multiple
              className="text-base"
              onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
            />
            <p className="text-sm text-fg-muted">
              {files.length === 0
                ? "Nothing chosen yet."
                : `${count(files.length)} file${files.length === 1 ? "" : "s"} chosen.`}
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="bulk-district">District</Label>
              <Input
                id="bulk-district"
                value={district}
                onChange={(event) => setDistrict(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="bulk-category">Category</Label>
              <Select
                id="bulk-category"
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
          </div>

          {tooMany ? (
            <Alert tone="review">
              {count(files.length)} files in one request; the limit is {MAX_FILES}. Send them in
              batches — every batch gets its own job.
            </Alert>
          ) : null}

          <div>
            <Button type="submit" disabled={files.length === 0 || tooMany || start.isPending}>
              {start.isPending ? "Uploading…" : "Queue for processing"}
            </Button>
          </div>
        </form>
      </Card>

      {start.isError ? <Alert tone="fail">{(start.error as Error).message}</Alert> : null}

      {start.data && (start.data.rejected ?? []).length > 0 ? (
        <Alert tone="review" title="Some files were not accepted">
          <ul className="mt-1 list-disc pl-5">
            {(start.data.rejected ?? []).map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </Alert>
      ) : null}

      {job.data ? (
        <Card>
          <CardTitle>Job {job.data.status}</CardTitle>
          <p className="mt-1 text-base text-fg-muted">
            {count(job.data.completed)} of {count(job.data.total)} processed ·{" "}
            {count(job.data.pending)} pending · {count(job.data.failed)} failed
          </p>
          <progress
            className="mt-3 w-full"
            max={job.data.total}
            value={job.data.completed + job.data.failed}
          />
          {(job.data.errors ?? []).length > 0 ? (
            <Alert tone="review" className="mt-3">
              <ul className="list-disc pl-5">
                {(job.data.errors ?? []).map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            </Alert>
          ) : null}
          {(job.data.scan_ids ?? []).length > 0 ? (
            <ul className="mt-3 flex flex-wrap gap-2">
              {(job.data.scan_ids ?? []).slice(0, 40).map((id) => (
                <li key={String(id)}>
                  <Link
                    href={`/scan/${String(id)}`}
                    className="inline-flex h-touch items-center rounded-md border border-border px-3 text-sm hover:bg-surface-2"
                  >
                    {String(id).slice(0, 8)}
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}
