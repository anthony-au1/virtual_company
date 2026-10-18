"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  createExploration,
  getExploration,
  updateExploration,
  type CreateExplorationPayload,
} from "@/lib/api/explorations";
import { ApiError, apiErrorMessages } from "@/lib/api/client";
import {
  explorationObligationsQueryKey,
  explorationQueryKey,
  explorationsQueryKey,
} from "@/lib/queries/query-keys";

const schema = z.object({
  business_context: z
    .string()
    .trim()
    .min(1, "Describe the business context you want to investigate."),
  max_obligations: z
    .number({ error: "Enter a whole number from 1 to 20." })
    .int("Maximum obligations must be a whole number.")
    .min(1, "Maximum obligations must be at least 1.")
    .max(20, "Maximum obligations cannot exceed 20."),
});

type FormValues = z.infer<typeof schema>;

const defaults: FormValues = { business_context: "", max_obligations: 10 };
const inputClass =
  "border-input bg-background focus-visible:ring-ring w-full rounded-md border px-3 py-2 text-sm outline-none focus-visible:ring-2";

export function ExplorationFormPage({
  explorationId,
}: {
  explorationId?: string;
} = {}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const editMode = Boolean(explorationId);
  const explorationQuery = useQuery({
    queryKey: explorationQueryKey(explorationId ?? "new"),
    queryFn: () => getExploration(explorationId!),
    enabled: editMode,
  });
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: defaults,
  });

  useEffect(() => {
    if (!explorationQuery.data) return;
    form.reset({
      business_context: explorationQuery.data.business_context,
      max_obligations: explorationQuery.data.max_obligations,
    });
  }, [explorationQuery.data, form]);

  const mutation = useMutation({
    mutationFn: (payload: CreateExplorationPayload) =>
      explorationId
        ? updateExploration(explorationId, payload)
        : createExploration(payload),
    onSuccess: async (exploration) => {
      queryClient.setQueryData(
        explorationQueryKey(exploration.id),
        exploration,
      );
      await queryClient.invalidateQueries({ queryKey: explorationsQueryKey });
      if (explorationId) {
        await queryClient.invalidateQueries({
          queryKey: explorationObligationsQueryKey(explorationId),
        });
      }
      router.push(`/explorations/${exploration.id}`);
    },
  });

  const onSubmit = form.handleSubmit((values) => mutation.mutate(values));
  const disabled = form.formState.isSubmitting || mutation.isPending;

  if (editMode && explorationQuery.isPending) {
    return (
      <p role="status" className="mx-auto max-w-3xl p-8 text-center text-sm">
        Loading Exploration…
      </p>
    );
  }
  if (editMode && explorationQuery.isError) {
    return (
      <section className="mx-auto max-w-3xl rounded-lg border p-6">
        <h1 className="text-lg font-semibold">
          Exploration could not be loaded
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">
          {explorationQuery.error.message}
        </p>
        <Link
          className="text-primary mt-4 inline-block text-sm underline"
          href={`/explorations/${explorationId}`}
        >
          Back to Exploration
        </Link>
      </section>
    );
  }

  return (
    <section aria-labelledby="page-title" className="mx-auto max-w-3xl">
      <Link
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-sm"
        href={
          explorationId ? `/explorations/${explorationId}` : "/explorations"
        }
      >
        <ArrowLeft aria-hidden="true" className="size-4" />
        {explorationId ? "Exploration" : "Explorations"}
      </Link>
      <div className="mt-4 mb-6">
        <p className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
          Explorations
        </p>
        <h1 id="page-title" className="text-2xl font-semibold tracking-tight">
          {editMode ? "Edit Exploration" : "New Exploration"}
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Describe a business goal or question and how investigating companies
          you will select from Research could help answer it. The system will
          generate shared, evidence-focused investigation obligations.
        </p>
      </div>

      <form className="space-y-4" noValidate onSubmit={onSubmit}>
        <Card>
          <CardHeader>
            <CardTitle>Business context</CardTitle>
            <p className="text-muted-foreground text-sm">
              Describe the business goal, decision, or question you want to
              investigate, with the context and constraints that should guide
              research into companies you will select from Research.
            </p>
          </CardHeader>
          <CardContent>
            <label
              className="mb-1.5 block text-sm font-medium"
              htmlFor="business-context"
            >
              Business context
            </label>
            <textarea
              aria-describedby="business-context-help"
              aria-invalid={Boolean(form.formState.errors.business_context)}
              className={`${inputClass} min-h-56 resize-y`}
              id="business-context"
              {...form.register("business_context")}
            />
            <p
              className="text-muted-foreground mt-1 text-xs"
              id="business-context-help"
            >
              The context may concern the companies directly or a broader
              question their investigation can help answer. Use a full
              description rather than a search query.
            </p>
            {form.formState.errors.business_context ? (
              <p className="text-destructive mt-1 text-xs" role="alert">
                {form.formState.errors.business_context.message}
              </p>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Generation limit</CardTitle>
            <p className="text-muted-foreground text-sm">
              Maximum number of shared questions or conditions to investigate
              for each selected company. Fewer may be generated when the context
              does not require the full limit.
            </p>
          </CardHeader>
          <CardContent>
            <label
              className="mb-1.5 block text-sm font-medium"
              htmlFor="max-obligations"
            >
              Maximum obligations
            </label>
            <input
              aria-describedby="max-obligations-help"
              aria-invalid={Boolean(form.formState.errors.max_obligations)}
              className={inputClass}
              id="max-obligations"
              max="20"
              min="1"
              step="1"
              type="number"
              {...form.register("max_obligations", { valueAsNumber: true })}
            />
            <p
              className="text-muted-foreground mt-1 text-xs"
              id="max-obligations-help"
            >
              This is a ceiling, not an exact count. The valid range is 1 to 20.
            </p>
            {form.formState.errors.max_obligations ? (
              <p className="text-destructive mt-1 text-xs" role="alert">
                {form.formState.errors.max_obligations.message}
              </p>
            ) : null}
          </CardContent>
        </Card>

        {editMode ? (
          <p className="text-muted-foreground rounded-lg border p-3 text-sm">
            Changing the Business Context or Maximum obligations will regenerate
            the complete research obligation set. Once an Exploration has been
            run, the backend will prevent changes to these inputs.
          </p>
        ) : null}

        {mutation.isError ? (
          <div
            role="alert"
            className="border-destructive/30 rounded-lg border p-4"
          >
            <h2 className="text-sm font-semibold">
              Exploration could not be {editMode ? "updated" : "created"}
            </h2>
            <ul className="text-destructive mt-2 list-inside list-disc space-y-1 text-sm">
              {mutationMessages(mutation.error).map((message, index) => (
                <li key={`${index}-${message}`}>{message}</li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="flex flex-wrap justify-end gap-2 pb-4">
          <Button
            disabled={disabled}
            onClick={() =>
              router.push(
                explorationId
                  ? `/explorations/${explorationId}`
                  : "/explorations",
              )
            }
            type="button"
            variant="outline"
          >
            Cancel
          </Button>
          <Button disabled={disabled} type="submit">
            {mutation.isPending
              ? editMode
                ? "Saving and regenerating obligations…"
                : "Creating Exploration and generating obligations…"
              : editMode
                ? "Save changes"
                : "Create Exploration"}
          </Button>
        </div>
      </form>
    </section>
  );
}

function mutationMessages(error: unknown): string[] {
  if (error instanceof ApiError && error.status === 409) {
    return [
      "This Exploration can no longer be changed because it has already been run.",
    ];
  }
  if (error instanceof ApiError && error.status === 503) {
    return [
      "We couldn't generate research obligations for this Exploration. Please try again.",
    ];
  }
  return apiErrorMessages(error);
}
