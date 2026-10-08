"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Check,
  ExternalLink,
  Search,
  X,
  CircleHelp,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  formatDate,
  RunStatus,
} from "@/components/research/research-runs-page";
import {
  getResearchRunResults,
  type CriterionResult,
  type ResearchCompany,
  type ResearchResults,
  type ReviewStatus,
  updateCompanyReview,
} from "@/lib/api/research";
import { cn } from "@/lib/utils";
import { researchRunResultsQueryKey } from "@/lib/queries/query-keys";

const filters = [
  "ALL",
  "QUALIFIED",
  "INSUFFICIENT_EVIDENCE",
  "NOT_QUALIFIED",
  "ACCEPTED",
  "REJECTED",
  "UNREVIEWED",
] as const;
type ResultFilter = (typeof filters)[number];

export function ResearchResultsPage({ runId }: { runId: string }) {
  const [filter, setFilter] = useState<ResultFilter>("ALL");
  const [search, setSearch] = useState("");
  const queryKey = researchRunResultsQueryKey(runId);
  const query = useQuery({
    queryKey,
    queryFn: () => getResearchRunResults(runId),
  });
  const visibleCompanies = useMemo(() => {
    const normalizedSearch = search.trim().toLocaleLowerCase();
    return (query.data?.companies ?? []).filter((company) => {
      const statusMatch =
        filter === "ALL" ||
        company.qualification_status === filter ||
        company.review_status === filter;
      const searchMatch =
        !normalizedSearch ||
        company.name.toLocaleLowerCase().includes(normalizedSearch);
      return statusMatch && searchMatch;
    });
  }, [filter, query.data?.companies, search]);

  if (query.isPending) {
    return (
      <p
        role="status"
        className="text-muted-foreground mx-auto max-w-6xl rounded-lg border p-8 text-center text-sm"
      >
        Loading run results…
      </p>
    );
  }
  if (query.isError) {
    const notFound = "status" in query.error && query.error.status === 404;
    return (
      <section aria-labelledby="page-title" className="mx-auto max-w-6xl">
        <BackToRuns />
        <div
          role="alert"
          className="border-destructive/30 mt-5 rounded-lg border p-6"
        >
          <h1 id="page-title" className="text-lg font-semibold">
            {notFound
              ? "Research Run not found"
              : "Run results could not be loaded"}
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            {query.error.message}
          </p>
          {!notFound ? (
            <Button
              className="mt-4"
              onClick={() => void query.refetch()}
              size="sm"
              variant="outline"
            >
              Try again
            </Button>
          ) : null}
        </div>
      </section>
    );
  }

  const results = query.data;
  const reviewCounts = results.companies.reduce(
    (counts, company) => ({
      ...counts,
      [company.review_status.toLowerCase()]:
        counts[
          company.review_status.toLowerCase() as
            "accepted" | "rejected" | "unreviewed"
        ] + 1,
    }),
    { accepted: 0, rejected: 0, unreviewed: 0 },
  );

  return (
    <section aria-labelledby="page-title" className="mx-auto max-w-6xl">
      <BackToRuns />
      <header className="mt-4 border-b pb-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
              Research Run
            </p>
            <h1
              id="page-title"
              className="text-2xl font-semibold tracking-tight"
            >
              {results.campaign.name}
            </h1>
            <p className="text-muted-foreground mt-1 font-mono text-xs">
              {results.research_run.id}
            </p>
          </div>
          <RunStatus status={results.research_run.status} />
        </div>
        {results.research_run.status === "RUNNING" ? (
          <p className="mt-3 rounded-md bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
            This run is still in progress. Showing the results currently
            available.
          </p>
        ) : null}
        {results.research_run.error ? (
          <p className="text-destructive mt-3 text-sm">
            {results.research_run.error}
          </p>
        ) : null}
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
          <Metric label="Target" value={results.campaign.target_count} />
          <Metric
            label="Research cap"
            value={results.campaign.max_companies_to_research}
          />
          <Metric label="Researched" value={results.summary.researched} />
          <Metric label="Qualified" value={results.summary.qualified} />
          <Metric label="Not qualified" value={results.summary.not_qualified} />
          <Metric
            label="Insufficient"
            value={results.summary.insufficient_evidence}
          />
          <Metric label="Accepted" value={reviewCounts.accepted} />
          <Metric label="Rejected" value={reviewCounts.rejected} />
        </div>
        <p className="text-muted-foreground mt-2 text-xs">
          Started {formatDate(results.research_run.started_at)} ·{" "}
          {reviewCounts.unreviewed} unreviewed
        </p>
      </header>

      <CampaignCriteria results={results} />

      <div className="mt-8">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Companies</h2>
            <p className="text-muted-foreground mt-0.5 text-sm">
              AI qualification and human review are shown separately.
            </p>
          </div>
          <label className="relative block w-full sm:w-64">
            <Search
              aria-hidden="true"
              className="text-muted-foreground absolute top-2 left-2.5 size-4"
            />
            <input
              aria-label="Search companies"
              className="border-input bg-background focus-visible:ring-ring h-9 w-full rounded-md border pr-3 pl-9 text-sm outline-none focus-visible:ring-2"
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search company name"
              value={search}
            />
          </label>
        </div>
        <div
          aria-label="Filter companies"
          className="mb-4 flex flex-wrap gap-1.5"
        >
          {filters.map((value) => (
            <Button
              aria-pressed={filter === value}
              key={value}
              onClick={() => setFilter(value)}
              size="sm"
              variant={filter === value ? "secondary" : "ghost"}
            >
              {filterLabel(value)}
            </Button>
          ))}
        </div>

        {results.companies.length === 0 ? (
          <div className="rounded-lg border border-dashed p-9 text-center">
            <h3 className="text-sm font-semibold">No companies in this run</h3>
            <p className="text-muted-foreground mt-1 text-sm">
              Company results will appear here when they are available.
            </p>
          </div>
        ) : visibleCompanies.length === 0 ? (
          <p className="text-muted-foreground rounded-lg border p-8 text-center text-sm">
            No companies match this filter.
          </p>
        ) : (
          <div className="space-y-3">
            {visibleCompanies.map((company) => (
              <CompanyCard
                company={company}
                key={company.company_id}
                runId={runId}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function BackToRuns() {
  return (
    <Link
      className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-sm"
      href="/research"
    >
      <ArrowLeft aria-hidden="true" className="size-4" />
      Research Runs
    </Link>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-muted/40 rounded-md px-3 py-2">
      <div className="text-muted-foreground text-xs">{label}</div>
      <div className="mt-0.5 text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function CampaignCriteria({ results }: { results: ResearchResults }) {
  const criteria = results.campaign.criteria;
  return (
    <section aria-labelledby="criteria-title" className="mt-6">
      <h2 id="criteria-title" className="text-sm font-semibold">
        Campaign criteria
      </h2>
      <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <CriterionGroup title="Market & industry">
          {criteria.target_market ? (
            <ConfiguredCriterion
              label="Target market"
              subject={criteria.target_market}
            />
          ) : null}
          {criteria.industry ? (
            <ConfiguredCriterion label="Industry" subject={criteria.industry} />
          ) : null}
        </CriterionGroup>
        <CriterionGroup title="Technologies">
          {criteria.technologies.map((technology) => (
            <ConfiguredCriterion
              key={technology}
              label="Technology"
              subject={technology}
            />
          ))}
          {criteria.technologies.length === 0 ? (
            <p className="text-muted-foreground text-xs">
              No technology criteria
            </p>
          ) : null}
        </CriterionGroup>
        {criteria.company_size ? (
          <CriterionGroup title="Company size">
            {criteria.company_size.min != null ? (
              <ConfiguredCriterion
                label="Employees"
                subject={`≥ ${criteria.company_size.min}`}
              />
            ) : null}
            {criteria.company_size.max != null ? (
              <ConfiguredCriterion
                label="Employees"
                subject={`≤ ${criteria.company_size.max}`}
              />
            ) : null}
          </CriterionGroup>
        ) : null}
      </div>
    </section>
  );
}

function CriterionGroup({
  title,
  children,
}: React.PropsWithChildren<{ title: string }>) {
  return (
    <div className="rounded-lg border p-3">
      <h3 className="text-muted-foreground mb-2 text-xs font-semibold tracking-wide uppercase">
        {title}
      </h3>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function ConfiguredCriterion({
  label,
  subject,
}: {
  label: string;
  subject: string;
}) {
  return (
    <div className="flex items-center justify-between gap-2 text-sm">
      <span>
        <span className="text-muted-foreground">{label}</span>{" "}
        <span className="font-medium">{subject}</span>
      </span>
    </div>
  );
}

function CompanyCard({
  company,
  runId,
}: {
  company: ResearchCompany;
  runId: string;
}) {
  const queryClient = useQueryClient();
  const queryKey = researchRunResultsQueryKey(runId);
  const mutation = useMutation({
    mutationKey: ["research-company-review", runId, company.company_id],
    mutationFn: (status: ReviewStatus) =>
      updateCompanyReview(runId, company.company_id, status),
    onSuccess: (result) => {
      queryClient.setQueryData<ResearchResults>(queryKey, (current) =>
        current
          ? {
              ...current,
              companies: current.companies.map((item) =>
                item.company_id === result.company_id
                  ? { ...item, review_status: result.review_status }
                  : item,
              ),
            }
          : current,
      );
      void queryClient.invalidateQueries({ queryKey: ["research-runs"] });
    },
  });
  const pending = mutation.isPending;
  const reviewError = mutation.isError ? mutation.error.message : null;

  return (
    <article className="rounded-lg border p-4 sm:p-5">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
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
            <ReviewBadge status={company.review_status} />
          </div>
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs">
            <SummaryCounts label="Criteria" counts={company.summary} />
          </div>
        </div>
        <div className="flex flex-wrap gap-2 md:justify-end">
          <Button
            disabled={pending || company.review_status === "ACCEPTED"}
            onClick={() => mutation.mutate("ACCEPTED")}
            size="sm"
            variant={
              company.review_status === "ACCEPTED" ? "secondary" : "outline"
            }
          >
            <Check aria-hidden="true" data-icon="inline-start" />
            Accept
          </Button>
          <Button
            disabled={pending || company.review_status === "REJECTED"}
            onClick={() => mutation.mutate("REJECTED")}
            size="sm"
            variant={
              company.review_status === "REJECTED" ? "secondary" : "outline"
            }
          >
            <X aria-hidden="true" data-icon="inline-start" />
            Reject
          </Button>
          {company.review_status !== "UNREVIEWED" ? (
            <Button
              disabled={pending}
              onClick={() => mutation.mutate("UNREVIEWED")}
              size="sm"
              variant="ghost"
            >
              Reset
            </Button>
          ) : null}
        </div>
      </div>
      {reviewError ? (
        <p role="alert" className="text-destructive mt-3 text-sm">
          Review update failed: {reviewError}
        </p>
      ) : null}
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
        : {counts.matched} matched · {counts.mismatched} mismatched ·{" "}
        {counts.unknown} unknown
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
              <div
                className="bg-muted/40 rounded-md p-3 text-sm"
                key={evidence.id}
              >
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

function ReviewBadge({ status }: { status: ReviewStatus }) {
  return (
    <Badge variant={status === "UNREVIEWED" ? "outline" : "secondary"}>
      Human review: {status}
    </Badge>
  );
}

function criterionLabel(criterion: CriterionResult) {
  if (criterion.subject) return criterion.subject;
  return criterion.criterion.replaceAll("_", " ");
}

function filterLabel(value: ResultFilter) {
  return value === "ALL"
    ? "All"
    : value
        .replaceAll("_", " ")
        .toLowerCase()
        .replace(/^./, (letter) => letter.toUpperCase());
}

function sourceHost(url: string) {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}
