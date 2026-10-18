"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, apiErrorMessages } from "@/lib/api/client";
import { deleteCampaign } from "@/lib/api/campaigns";
import { campaignQueryKey, campaignsQueryKey } from "@/lib/queries/query-keys";

const LIFECYCLE_MESSAGE =
  "This Campaign cannot be deleted because it has already been used for research.";

export function DeleteCampaignAction({
  campaignId,
  navigateOnSuccess = true,
}: {
  campaignId: string;
  navigateOnSuccess?: boolean;
}) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const mutation = useMutation({
    mutationFn: () => deleteCampaign(campaignId),
    onSuccess: async () => {
      setConfirming(false);
      queryClient.removeQueries({ queryKey: campaignQueryKey(campaignId) });
      await queryClient.invalidateQueries({ queryKey: campaignsQueryKey });
      if (navigateOnSuccess) router.push("/campaigns");
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 404) {
        await queryClient.invalidateQueries({ queryKey: campaignsQueryKey });
      }
    },
  });
  const messages =
    mutation.error instanceof ApiError && mutation.error.status === 409
      ? [LIFECYCLE_MESSAGE]
      : mutation.error instanceof ApiError && mutation.error.status === 404
        ? ["Campaign not found"]
        : mutation.error instanceof ApiError && mutation.error.status >= 500
          ? ["Campaign could not be deleted. Please try again."]
          : mutation.isError
            ? apiErrorMessages(mutation.error)
            : [];

  return (
    <>
      <Button
        aria-label={`Delete Campaign ${campaignId}`}
        disabled={mutation.isPending}
        onClick={(event) => {
          event.stopPropagation();
          mutation.reset();
          setConfirming(true);
        }}
        size="sm"
        variant="destructive"
      >
        <Trash2 aria-hidden="true" data-icon="inline-start" />
        Delete Campaign
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
            aria-labelledby={`delete-campaign-title-${campaignId}`}
            aria-modal="true"
            className="bg-background w-full max-w-md rounded-lg border p-5 shadow-lg"
            role="alertdialog"
          >
            <h2
              id={`delete-campaign-title-${campaignId}`}
              className="font-semibold"
            >
              Delete Campaign?
            </h2>
            <p className="text-muted-foreground mt-2 text-sm">
              This will permanently delete this Campaign and its setup data.
              Shared company records and Research history are preserved. This
              action cannot be undone. Campaigns already used for research
              cannot be deleted.
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
                {mutation.isPending ? "Deleting…" : "Delete Campaign"}
              </Button>
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}
