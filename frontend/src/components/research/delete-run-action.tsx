"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { apiErrorMessages } from "@/lib/api/client";
import { deleteResearchRun } from "@/lib/api/research";
import {
  researchRunResultsQueryKey,
  researchRunsQueryKey,
} from "@/lib/queries/query-keys";

export function DeleteRunAction({
  runId,
  onDeleted,
}: {
  runId: string;
  onDeleted?: () => void;
}) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const mutation = useMutation({
    mutationFn: () => deleteResearchRun(runId),
    onSuccess: async () => {
      queryClient.setQueryData(
        researchRunsQueryKey,
        (runs: Array<{ run_id: string }> | undefined) =>
          runs?.filter((run) => run.run_id !== runId),
      );
      queryClient.removeQueries({
        queryKey: researchRunResultsQueryKey(runId),
      });
      await queryClient.invalidateQueries({ queryKey: researchRunsQueryKey });
      onDeleted?.();
      setConfirming(false);
    },
  });

  return (
    <>
      <Button
        aria-label={`Delete run ${runId}`}
        disabled={mutation.isPending}
        onClick={() => setConfirming(true)}
        size="sm"
        variant="destructive"
      >
        <Trash2 aria-hidden="true" data-icon="inline-start" />
        Delete Run
      </Button>
      {confirming ? (
        <div
          className="bg-background/70 fixed inset-0 z-50 flex items-center justify-center p-4 backdrop-blur-sm"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !mutation.isPending) {
              setConfirming(false);
            }
          }}
        >
          <section
            aria-labelledby={`delete-run-title-${runId}`}
            aria-modal="true"
            className="bg-background w-full max-w-md rounded-lg border p-5 shadow-lg"
            role="alertdialog"
          >
            <h2 id={`delete-run-title-${runId}`} className="font-semibold">
              Delete Research Run?
            </h2>
            <p className="text-muted-foreground mt-2 text-sm">
              This will permanently delete this research run and its persisted
              evidence and qualification results. The Campaign and other runs
              will remain. This action cannot be undone.
            </p>
            {mutation.isError ? (
              <ul
                role="alert"
                className="text-destructive mt-3 space-y-1 text-sm"
              >
                {apiErrorMessages(mutation.error).map((message, index) => (
                  <li key={`${index}-${message}`}>{message}</li>
                ))}
              </ul>
            ) : null}
            <div className="mt-5 flex justify-end gap-2">
              <Button
                disabled={mutation.isPending}
                onClick={() => setConfirming(false)}
                variant="outline"
              >
                Cancel
              </Button>
              <Button
                disabled={mutation.isPending}
                onClick={() => mutation.mutate()}
                variant="destructive"
              >
                {mutation.isPending ? "Deleting…" : "Delete Run"}
              </Button>
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}
