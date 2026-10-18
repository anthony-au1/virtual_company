"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, apiErrorMessages } from "@/lib/api/client";
import { deleteExploration } from "@/lib/api/explorations";
import {
  explorationObligationsQueryKey,
  explorationQueryKey,
  explorationsQueryKey,
} from "@/lib/queries/query-keys";

const LIFECYCLE_MESSAGE =
  "This Exploration cannot be deleted because it has already been run.";

export function DeleteExplorationAction({
  explorationId,
  navigateOnSuccess = true,
}: {
  explorationId: string;
  navigateOnSuccess?: boolean;
}) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const mutation = useMutation({
    mutationFn: () => deleteExploration(explorationId),
    onSuccess: async () => {
      setConfirming(false);
      queryClient.removeQueries({
        queryKey: explorationQueryKey(explorationId),
      });
      queryClient.removeQueries({
        queryKey: explorationObligationsQueryKey(explorationId),
      });
      await queryClient.invalidateQueries({ queryKey: explorationsQueryKey });
      if (navigateOnSuccess) {
        router.push("/explorations");
      }
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 404) {
        await queryClient.invalidateQueries({ queryKey: explorationsQueryKey });
      }
    },
  });
  const messages =
    mutation.error instanceof ApiError && mutation.error.status === 409
      ? [LIFECYCLE_MESSAGE]
      : mutation.error instanceof ApiError && mutation.error.status === 404
        ? ["Exploration not found"]
        : mutation.error instanceof ApiError && mutation.error.status >= 500
          ? ["Exploration could not be deleted. Please try again."]
          : mutation.isError
            ? apiErrorMessages(mutation.error)
            : [];

  return (
    <>
      <Button
        disabled={mutation.isPending}
        onClick={() => {
          mutation.reset();
          setConfirming(true);
        }}
        size="sm"
        variant="destructive"
      >
        <Trash2 aria-hidden="true" data-icon="inline-start" />
        Delete Exploration
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
            aria-labelledby={`delete-exploration-title-${explorationId}`}
            aria-modal="true"
            className="bg-background w-full max-w-md rounded-lg border p-5 shadow-lg"
            role="alertdialog"
          >
            <h2
              id={`delete-exploration-title-${explorationId}`}
              className="font-semibold"
            >
              Delete Exploration?
            </h2>
            <p className="text-muted-foreground mt-2 text-sm">
              This will permanently delete this Exploration and its generated
              research obligations. This action cannot be undone.
            </p>
            {messages.length ? (
              <ul
                role="alert"
                className="text-destructive mt-3 space-y-1 text-sm"
              >
                {messages.map((message, index) => (
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
                {mutation.isPending ? "Deleting…" : "Delete Exploration"}
              </Button>
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}
