"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Plus, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  createCampaign,
  getCampaign,
  updateCampaign,
  type Campaign,
  type CreateCampaignPayload,
  type UpdateCampaignPayload,
} from "@/lib/api/campaigns";
import { apiErrorMessages } from "@/lib/api/client";
import { campaignQueryKey, campaignsQueryKey } from "@/lib/queries/query-keys";

const campaignFormSchema = z
  .object({
    name: z.string().trim().min(1, "Enter a campaign name.").max(255),
    description: z.string(),
    target_count: z
      .number({ error: "Enter a target company count." })
      .int("Enter a whole number.")
      .min(1, "Target company count must be at least 1."),
    max_companies_to_research: z.number().int().min(1),
    target_market: z.string().max(255),
    industry: z.string().max(255),
    keywords: z.array(z.string().trim().min(1)),
    min_employees: z
      .number()
      .int("Enter a whole number.")
      .min(0, "Employee count cannot be negative.")
      .optional(),
    max_employees: z
      .number()
      .int("Enter a whole number.")
      .min(0, "Employee count cannot be negative.")
      .optional(),
  })
  .superRefine((values, context) => {
    if (
      values.min_employees !== undefined &&
      values.max_employees !== undefined &&
      values.min_employees > values.max_employees
    ) {
      context.addIssue({
        code: "custom",
        path: ["max_employees"],
        message: "Maximum employees must be at least the minimum.",
      });
    }

    if (values.max_companies_to_research < values.target_count) {
      context.addIssue({
        code: "custom",
        path: ["max_companies_to_research"],
        message: "Research limit must be at least the target company count.",
      });
    }
  });

type CampaignFormValues = z.infer<typeof campaignFormSchema>;
type KeywordField = "keywords";

const defaultValues: CampaignFormValues = {
  name: "",
  description: "",
  target_count: 5,
  max_companies_to_research: 15,
  target_market: "",
  industry: "",
  keywords: [],
  min_employees: undefined,
  max_employees: undefined,
};

export function CampaignFormPage({ campaignId }: { campaignId?: string } = {}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [serverError, setServerError] = useState<string[] | null>(null);
  const campaignQuery = useQuery({
    queryKey: campaignQueryKey(campaignId ?? "new"),
    queryFn: () => getCampaign(campaignId!),
    enabled: Boolean(campaignId),
  });
  const form = useForm<CampaignFormValues>({
    resolver: zodResolver(campaignFormSchema),
    defaultValues,
  });
  const keywords = useWatch({
    control: form.control,
    name: "keywords",
  });
  useEffect(() => {
    const campaign = campaignQuery.data;
    if (!campaign) return;
    if (campaign.sealed_at) return;
    form.reset(campaignToFormValues(campaign));
  }, [campaignQuery.data, form]);
  const mutation = useMutation({
    mutationFn: (payload: CreateCampaignPayload | UpdateCampaignPayload) =>
      campaignId
        ? updateCampaign(campaignId, payload as UpdateCampaignPayload)
        : createCampaign(payload as CreateCampaignPayload),
    onSuccess: (campaign) => {
      queryClient.setQueryData(campaignQueryKey(campaign.id), campaign);
      void queryClient.invalidateQueries({ queryKey: campaignsQueryKey });
      router.push(`/campaigns/${campaign.id}`);
    },
    onError: (error) => setServerError(apiErrorMessages(error)),
  });

  const onSubmit = form.handleSubmit((values) => {
    setServerError(null);
    const companySize = {
      ...(values.min_employees !== undefined
        ? { min: values.min_employees }
        : {}),
      ...(values.max_employees !== undefined
        ? { max: values.max_employees }
        : {}),
    };
    const commonPayload = {
      name: values.name,
      description: values.description,
      target_count: values.target_count,
      max_companies_to_research: values.max_companies_to_research,
      keywords: values.keywords,
      company_size:
        companySize.min !== undefined || companySize.max !== undefined
          ? companySize
          : null,
    };
    const payload: CreateCampaignPayload | UpdateCampaignPayload = campaignId
      ? {
          ...commonPayload,
          target_market: values.target_market.trim() || null,
          industry: values.industry.trim() || null,
        }
      : {
          ...commonPayload,
          status: "DRAFT",
          ...(values.target_market.trim()
            ? { target_market: values.target_market.trim() }
            : {}),
          ...(values.industry.trim()
            ? { industry: values.industry.trim() }
            : {}),
        };
    mutation.mutate(payload);
  });

  const disabled = form.formState.isSubmitting || mutation.isPending;

  if (campaignId && campaignQuery.isPending) {
    return (
      <p role="status" className="mx-auto max-w-3xl p-8 text-center text-sm">
        Loading Campaign…
      </p>
    );
  }
  if (campaignId && (campaignQuery.isError || campaignQuery.data?.sealed_at)) {
    const sealed = campaignQuery.data?.sealed_at != null;
    return (
      <section className="mx-auto max-w-3xl rounded-lg border p-6">
        <h1 className="text-lg font-semibold">
          {sealed ? "Campaign is sealed" : "Campaign could not be loaded"}
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">
          {sealed
            ? "Campaign criteria cannot be changed after research has started."
            : campaignQuery.error?.message}
        </p>
        <Link
          className="text-primary mt-4 inline-block text-sm underline"
          href={`/campaigns/${campaignId}`}
        >
          Back to Campaign
        </Link>
      </section>
    );
  }

  return (
    <section aria-labelledby="page-title" className="mx-auto max-w-3xl">
      <Link
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-sm"
        href="/campaigns"
      >
        <ArrowLeft aria-hidden="true" className="size-4" />
        Campaigns
      </Link>
      <div className="mt-4 mb-6">
        <p className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
          Campaigns
        </p>
        <h1 id="page-title" className="text-2xl font-semibold tracking-tight">
          {campaignId ? "Edit Campaign" : "Create Campaign"}
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Set criteria for a reusable company research campaign.
        </p>
      </div>

      <form className="space-y-4" noValidate onSubmit={onSubmit}>
        <Card>
          <CardHeader>
            <CardTitle>Basic information</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Field
              id="campaign-name"
              label="Campaign name"
              error={form.formState.errors.name?.message}
            >
              <input
                aria-invalid={Boolean(form.formState.errors.name)}
                autoComplete="off"
                className={inputClass}
                id="campaign-name"
                {...form.register("name")}
              />
            </Field>
            <Field
              id="target-count"
              label="Target company count"
              error={form.formState.errors.target_count?.message}
            >
              <input
                aria-invalid={Boolean(form.formState.errors.target_count)}
                className={inputClass}
                id="target-count"
                min="1"
                step="1"
                type="number"
                {...form.register("target_count", {
                  setValueAs: parseOptionalNumber,
                })}
              />
            </Field>
            <Field id="research-limit" label="Maximum companies to research">
              <input
                className={inputClass}
                id="research-limit"
                min="1"
                step="1"
                type="number"
                {...form.register("max_companies_to_research", {
                  setValueAs: parseOptionalNumber,
                })}
              />
            </Field>
            <Field
              className="sm:col-span-2"
              id="description"
              label="Description"
            >
              <textarea
                className={`${inputClass} min-h-20 resize-y`}
                id="description"
                {...form.register("description")}
              />
            </Field>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Market</CardTitle>
            <p className="text-muted-foreground text-xs">
              All configured campaign criteria are evaluated equally.
            </p>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Field
              id="target-market"
              label="Target market"
              error={form.formState.errors.target_market?.message}
            >
              <input
                className={inputClass}
                id="target-market"
                maxLength={255}
                {...form.register("target_market")}
              />
            </Field>
            <Field
              id="industry"
              label="Industry"
              error={form.formState.errors.industry?.message}
            >
              <input
                className={inputClass}
                id="industry"
                maxLength={255}
                {...form.register("industry")}
              />
            </Field>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Keywords</CardTitle>
            <p className="text-muted-foreground text-xs">
              Keywords relevant to the companies you want to find. Examples:
              Java, cloud migration, process automation, omnichannel.
            </p>
          </CardHeader>
          <CardContent className="space-y-5">
            <KeywordInput
              error={form.formState.errors.keywords?.message}
              label="Keywords"
              onAdd={(value) => addKeyword(form, "keywords", value)}
              onRemove={(index) =>
                removeKeyword(form, "keywords", index)
              }
              values={keywords}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Company size</CardTitle>
            <p className="text-muted-foreground text-xs">
              Either bound can be left empty.
            </p>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <SizeBoundFields
              error={form.formState.errors.min_employees?.message}
              label="Minimum employees"
              numberName="min_employees"
              register={form.register}
            />
            <SizeBoundFields
              error={form.formState.errors.max_employees?.message}
              label="Maximum employees"
              numberName="max_employees"
              register={form.register}
            />
          </CardContent>
        </Card>

        {serverError ? (
          <div
            role="alert"
            className="border-destructive/30 rounded-lg border p-4"
          >
            <h2 className="text-sm font-semibold">
              Campaign could not be {campaignId ? "updated" : "created"}
            </h2>
            <ul className="text-destructive mt-2 list-inside list-disc space-y-1 text-sm">
              {serverError.map((message, index) => (
                <li key={`${index}-${message}`}>{message}</li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="flex justify-end gap-2 pb-4">
          <Button
            disabled={disabled}
            onClick={() => router.push("/campaigns")}
            type="button"
            variant="outline"
          >
            Cancel
          </Button>
          <Button disabled={disabled} type="submit">
            {mutation.isPending
              ? campaignId
                ? "Saving changes…"
                : "Creating campaign…"
              : campaignId
                ? "Save Changes"
                : "Create Campaign"}
          </Button>
        </div>
      </form>
    </section>
  );
}

const inputClass =
  "border-input bg-background focus-visible:ring-ring h-9 w-full rounded-md border px-3 text-sm outline-none focus-visible:ring-2";

function Field({
  id,
  label,
  error,
  className,
  children,
}: React.PropsWithChildren<{
  id: string;
  label: string;
  error?: string;
  className?: string;
}>) {
  return (
    <div className={className}>
      <label className="mb-1.5 block text-sm font-medium" htmlFor={id}>
        {label}
        {error ? <span className="text-destructive ml-1">*</span> : null}
      </label>
      {children}
      {error ? <p className="text-destructive mt-1 text-xs">{error}</p> : null}
    </div>
  );
}

function KeywordInput({
  label,
  values,
  onAdd,
  onRemove,
  error,
}: {
  label: string;
  values: string[];
  onAdd: (value: string) => void;
  onRemove: (index: number) => void;
  error?: string;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const value = draft.trim();
    if (!value) return;
    onAdd(value);
    setDraft("");
  };
  return (
    <div>
      <span className="mb-1.5 block text-sm font-medium">{label}</span>
      <div className="flex flex-wrap gap-1.5" aria-label={label}>
        {values.map((value, index) => (
          <Badge
            className="h-7 gap-1 rounded-md"
            key={`${value}-${index}`}
            variant="secondary"
          >
            {value}
            <button
              aria-label={`Remove ${value}`}
              className="hover:text-destructive rounded-full"
              onClick={() => onRemove(index)}
              type="button"
            >
              <X aria-hidden="true" className="size-3" />
            </button>
          </Badge>
        ))}
        {values.length === 0 ? (
          <span className="text-muted-foreground py-1 text-xs">None added</span>
        ) : null}
      </div>
      <div className="mt-2 flex gap-2">
        <input
          aria-label={`Add ${label.toLowerCase()}`}
          className={inputClass}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === ",") {
              event.preventDefault();
              add();
            }
          }}
          placeholder="Add a keyword or concept"
          value={draft}
        />
        <Button
          aria-label={`Add ${label.toLowerCase()}`}
          onClick={add}
          size="sm"
          type="button"
          variant="outline"
        >
          <Plus aria-hidden="true" />
        </Button>
      </div>
      {error ? <p className="text-destructive mt-1 text-xs">{error}</p> : null}
    </div>
  );
}

function SizeBoundFields({
  label,
  numberName,
  register,
  error,
}: {
  label: string;
  numberName: "min_employees" | "max_employees";
  register: ReturnType<typeof useForm<CampaignFormValues>>["register"];
  error?: string;
}) {
  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium" htmlFor={numberName}>
        {label}
      </label>
      <input
        className={inputClass}
        id={numberName}
        min="0"
        step="1"
        type="number"
        {...register(numberName, { setValueAs: parseOptionalNumber })}
      />
      {error ? <p className="text-destructive text-xs">{error}</p> : null}
    </div>
  );
}

function addKeyword(
  form: ReturnType<typeof useForm<CampaignFormValues>>,
  field: KeywordField,
  value: string,
) {
  form.setValue(field, [...form.getValues(field), value], {
    shouldDirty: true,
    shouldValidate: true,
  });
}

function removeKeyword(
  form: ReturnType<typeof useForm<CampaignFormValues>>,
  field: KeywordField,
  index: number,
) {
  form.setValue(
    field,
    form.getValues(field).filter((_, itemIndex) => itemIndex !== index),
    { shouldDirty: true, shouldValidate: true },
  );
}

function parseOptionalNumber(value: string) {
  return value === "" ? undefined : Number(value);
}

function campaignToFormValues(campaign: Campaign): CampaignFormValues {
  return {
    name: campaign.name,
    description: campaign.description ?? "",
    target_count: campaign.target_count,
    max_companies_to_research: campaign.max_companies_to_research,
    target_market: campaign.target_market ?? "",
    industry: campaign.industry ?? "",
    keywords: campaign.keywords,
    min_employees: campaign.company_size?.min ?? undefined,
    max_employees: campaign.company_size?.max ?? undefined,
  };
}
