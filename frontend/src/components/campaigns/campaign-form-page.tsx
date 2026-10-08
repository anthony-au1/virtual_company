"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Plus, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  createCampaign,
  type CreateCampaignPayload,
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
    technologies: z.array(z.string().trim().min(1)),
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
type TechnologyField = "technologies";

const defaultValues: CampaignFormValues = {
  name: "",
  description: "",
  target_count: 5,
  max_companies_to_research: 15,
  target_market: "",
  industry: "",
  technologies: [],
  min_employees: undefined,
  max_employees: undefined,
};

export function CampaignFormPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [serverError, setServerError] = useState<string[] | null>(null);
  const form = useForm<CampaignFormValues>({
    resolver: zodResolver(campaignFormSchema),
    defaultValues,
  });
  const technologies = useWatch({
    control: form.control,
    name: "technologies",
  });
  const mutation = useMutation({
    mutationFn: createCampaign,
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
    const payload: CreateCampaignPayload = {
      name: values.name,
      description: values.description,
      target_count: values.target_count,
      max_companies_to_research: values.max_companies_to_research,
      status: "DRAFT",
      ...(values.target_market.trim()
        ? { target_market: values.target_market.trim() }
        : {}),
      ...(values.industry.trim() ? { industry: values.industry.trim() } : {}),
      technologies: values.technologies,
      company_size:
        companySize.min !== undefined || companySize.max !== undefined
          ? companySize
          : null,
    };
    mutation.mutate(payload);
  });

  const disabled = form.formState.isSubmitting || mutation.isPending;

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
          Create Campaign
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
            <CardTitle>Technologies</CardTitle>
            <p className="text-muted-foreground text-xs">
              Enter any technology label. The backend validates and normalizes
              criteria.
            </p>
          </CardHeader>
          <CardContent className="space-y-5">
            <TechnologyInput
              error={form.formState.errors.technologies?.message}
              label="Technologies"
              onAdd={(value) => addTechnology(form, "technologies", value)}
              onRemove={(index) =>
                removeTechnology(form, "technologies", index)
              }
              values={technologies}
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
              Campaign could not be created
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
            {mutation.isPending ? "Creating campaign…" : "Create Campaign"}
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

function TechnologyInput({
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
          placeholder="Type a technology"
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

function addTechnology(
  form: ReturnType<typeof useForm<CampaignFormValues>>,
  field: TechnologyField,
  value: string,
) {
  form.setValue(field, [...form.getValues(field), value], {
    shouldDirty: true,
    shouldValidate: true,
  });
}

function removeTechnology(
  form: ReturnType<typeof useForm<CampaignFormValues>>,
  field: TechnologyField,
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
