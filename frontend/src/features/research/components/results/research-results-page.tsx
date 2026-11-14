"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { DeleteRunAction } from "@/features/research/components/runs/delete-run-action";
import { RunStatus } from "@/features/research/components/runs/run-status-badge";
import { ResearchCompanyCard } from "@/features/research/components/results/research-company-card";
import { isTerminalRunStatus } from "@/features/research/status";
import {
  getResearchRunResults,
  type ResearchResults,
} from "@/features/research/api/research";
import { formatDate } from "@/lib/format-date";
import { researchRunResultsQueryKey } from "@/features/research/query-keys";

const filters = [
  "ALL",
  "QUALIFIED",
  "INSUFFICIENT_EVIDENCE",
  "NOT_QUALIFIED",
] as const;
type ResultFilter = (typeof filters)[number];

export function ResearchResultsPage({ runId }: { runId: string }) {
  const router = useRouter();
  const [filter, setFilter] = useState<ResultFilter>("ALL");
  const [search, setSearch] = useState("");
  const queryKey = researchRunResultsQueryKey(runId);
  const query = useQuery({
    queryKey,
    queryFn: () => getResearchRunResults(runId),
    refetchInterval: (current) =>
      current.state.data && isTerminalRunStatus(current.state.data.research_run.status)
        ? false
        : 2000,
  });
  const visibleCompanies = useMemo(() => {
    const normalizedSearch = search.trim().toLocaleLowerCase();
    return (query.data?.companies ?? []).filter((company) => {
      const statusMatch =
        filter === "ALL" || company.qualification_status === filter;
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
          <div className="flex flex-wrap items-center justify-end gap-2">
            <RunStatus status={results.research_run.status} />
            {isTerminalRunStatus(results.research_run.status) ? (
              <DeleteRunAction
                runId={runId}
                onDeleted={() => router.push("/research")}
              />
            ) : null}
          </div>
        </div>
        {results.research_run.status === "RUNNING" || results.research_run.status === "QUEUED" ? (
          <p className="mt-3 rounded-md bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
            {results.research_run.status === "QUEUED"
              ? "This run is queued. Results will appear here as research progresses."
              : "This run is still in progress. Showing the results currently available."}
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
        </div>
        <p className="text-muted-foreground mt-2 text-xs">
          Started {formatDate(results.research_run.started_at)}
        </p>
      </header>

      <CampaignCriteria results={results} />

      <div className="mt-8">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Companies</h2>
            <p className="text-muted-foreground mt-0.5 text-sm">
              Automatic qualification results and supporting evidence.
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
              <ResearchCompanyCard company={company} key={company.company_id} />
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
        <CriterionGroup title="Keywords">
          {criteria.keywords.map((keyword) => (
            <ConfiguredCriterion
              key={keyword}
              label="Keyword"
              subject={keyword}
            />
          ))}
          {criteria.keywords.length === 0 ? (
            <p className="text-muted-foreground text-xs">No keyword criteria</p>
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

function filterLabel(value: ResultFilter) {
  return value === "ALL"
    ? "All"
    : value
        .replaceAll("_", " ")
        .toLowerCase()
        .replace(/^./, (letter) => letter.toUpperCase());
}
