"use client";

import { Check, CircleHelp, ExternalLink, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type {
  CriterionResult,
  ResearchCompany,
} from "@/features/research/api/research";

export function ResearchCompanyCard({
  company,
  selected,
  onSelectedChange,
}: {
  company: ResearchCompany;
  selected?: boolean;
  onSelectedChange?: (selected: boolean) => void;
}) {
  return (
    <article className="rounded-lg border p-4 sm:p-5">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {onSelectedChange ? (
              <label className="text-muted-foreground inline-flex min-h-8 shrink-0 items-center gap-2 text-sm">
                <input
                  checked={selected ?? false}
                  className="border-input accent-primary size-4 rounded"
                  onChange={(event) => onSelectedChange(event.target.checked)}
                  type="checkbox"
                />
                <span className="sr-only">Select {company.name}</span>
              </label>
            ) : null}
            <h3 className="text-base font-semibold">{company.name}</h3>
            {company.website ? (
              <a
                className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 truncate text-xs"
                href={company.website}
                rel="noreferrer"
                target="_blank"
              >
                {company.website}
                <ExternalLink aria-hidden="true" className="size-3" />
              </a>
            ) : null}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <QualificationBadge status={company.qualification_status} />
          </div>
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs">
            <SummaryCounts label="Criteria" counts={company.summary} />
          </div>
        </div>
      </div>
      {company.criteria.length > 0 ? (
        <div className="mt-4 border-t pt-3">
          <h4 className="text-muted-foreground mb-2 text-xs font-semibold tracking-wide uppercase">
            Criteria details
          </h4>
          <div className="space-y-1.5">
            {company.criteria.map((criterion, index) => (
              <CriterionDisclosure
                criterion={criterion}
                key={`${criterion.criterion}-${criterion.subject}-${index}`}
              />
            ))}
          </div>
        </div>
      ) : null}
    </article>
  );
}

function SummaryCounts({
  label,
  counts,
}: {
  label: string;
  counts: { matched: number; mismatched: number; unknown: number };
}) {
  return (
    <span>
      <span className="font-medium">{label}</span>
      <span className="text-muted-foreground">
        : {counts.matched} matched · {counts.mismatched} mismatched · {counts.unknown} unknown
      </span>
    </span>
  );
}

function CriterionDisclosure({ criterion }: { criterion: CriterionResult }) {
  const Icon =
    criterion.status === "MATCH"
      ? Check
      : criterion.status === "MISMATCH"
        ? X
        : CircleHelp;
  return (
    <details className="group rounded-md border px-3 py-2">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 text-sm [&::-webkit-details-marker]:hidden">
        <Icon
          aria-hidden="true"
          className={cn(
            "size-4",
            criterion.status === "MATCH"
              ? "text-emerald-600"
              : criterion.status === "MISMATCH"
                ? "text-destructive"
                : "text-amber-600",
          )}
        />
        <span className="font-medium">{criterionLabel(criterion)}</span>
        <Badge variant="outline">{criterion.status}</Badge>
        <span className="text-muted-foreground ml-auto text-xs">Details</span>
      </summary>
      <div className="mt-3 border-t pt-3">
        <p className="text-sm">{criterion.reason}</p>
        {criterion.evidence.length ? (
          <div className="mt-3 space-y-2">
            <h5 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">
              Evidence for this criterion
            </h5>
            {criterion.evidence.map((evidence) => (
              <div className="bg-muted/40 rounded-md p-3 text-sm" key={evidence.id}>
                <p className="font-medium">{evidence.claim}</p>
                <p className="mt-1 whitespace-pre-wrap">
                  “{evidence.evidence_text}”
                </p>
                <a
                  className="text-primary mt-2 inline-flex items-center gap-1 text-xs underline underline-offset-2"
                  href={evidence.source_url}
                  rel="noreferrer"
                  target="_blank"
                >
                  {evidence.source_title || sourceHost(evidence.source_url)}
                  <ExternalLink aria-hidden="true" className="size-3" />
                </a>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-muted-foreground mt-2 text-xs">
            No evidence was linked to this criterion.
          </p>
        )}
      </div>
    </details>
  );
}

function QualificationBadge({
  status,
}: {
  status: ResearchCompany["qualification_status"];
}) {
  const styles =
    status === "QUALIFIED"
      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
      : status === "NOT_QUALIFIED"
        ? "bg-destructive/10 text-destructive"
        : "bg-amber-500/10 text-amber-700 dark:text-amber-300";
  return (
    <Badge className={styles} variant="secondary">
      AI: {status.replaceAll("_", " ")}
    </Badge>
  );
}

function criterionLabel(criterion: CriterionResult) {
  if (criterion.subject) return criterion.subject;
  return criterion.criterion.replaceAll("_", " ");
}

function sourceHost(url: string) {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}
