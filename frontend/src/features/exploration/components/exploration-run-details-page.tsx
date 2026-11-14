"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, RefreshCw } from "lucide-react";
import Link from "next/link";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  executeExplorationRun,
  getExplorationRun,
  listExplorationCompanyEvidence,
  listExplorationCompanyFacts,
  listExplorationCompanyHypotheses,
  listExplorationObligations,
  listExplorationRunCompanies,
  listExplorationRuns,
  type ExplorationEvidence,
  type ExplorationFact,
  type ExplorationHypothesis,
  type ExplorationRunStatus,
} from "@/features/exploration/api/explorations";
import { ApiError } from "@/lib/api/client";
import { formatDate } from "@/lib/format-date";
import {
  explorationCompanyEvidenceQueryKey,
  explorationCompanyFactsQueryKey,
  explorationCompanyHypothesesQueryKey,
  explorationObligationsQueryKey,
  explorationRunCompaniesQueryKey,
  explorationRunStatusQueryKey,
  explorationRunsQueryKey,
} from "@/features/exploration/query-keys";

const POLL_INTERVAL_MS = 2_500;
const resultSections = ["evidence", "facts", "hypotheses"] as const;
type ResultSection = (typeof resultSections)[number];

export function ExplorationRunDetailsPage({
  explorationId,
  runId,
}: {
  explorationId: string;
  runId: string;
}) {
  const queryClient = useQueryClient();
  const [companyLinkId, setCompanyLinkId] = useState("");
  const [expandedHypothesisIds, setExpandedHypothesisIds] = useState<
    Set<string>
  >(new Set());
  const [expandedFactIds, setExpandedFactIds] = useState<Set<string>>(
    new Set(),
  );
  const [activeSection, setActiveSection] = useState<ResultSection>("evidence");
  const [executionNeedsRefresh, setExecutionNeedsRefresh] = useState(false);
  const previousStatus = useRef<ExplorationRunStatus | undefined>(undefined);
  const statusKey = explorationRunStatusQueryKey(explorationId, runId);

  const statusQuery = useQuery({
    queryKey: statusKey,
    queryFn: () => getExplorationRun(explorationId, runId),
    retry: false,
    refetchInterval: (query) =>
      explorationRunStatusPollingInterval(
        query.state.data?.status,
        Boolean(query.state.error),
      ),
    refetchOnWindowFocus: true,
  });
  const runsQuery = useQuery({
    queryKey: explorationRunsQueryKey(explorationId),
    queryFn: () => listExplorationRuns(explorationId),
  });
  const companiesQuery = useQuery({
    queryKey: explorationRunCompaniesQueryKey(explorationId, runId),
    queryFn: () => listExplorationRunCompanies(explorationId, runId),
    enabled: Boolean(statusQuery.data),
  });

  const selectedCompany = useMemo(() => {
    const companies = companiesQuery.data ?? [];
    return (
      companies.find((company) => company.id === companyLinkId) ?? companies[0]
    );
  }, [companiesQuery.data, companyLinkId]);
  const selectedCompanyLinkId = selectedCompany?.id ?? "";

  const evidenceQuery = useQuery({
    queryKey: explorationCompanyEvidenceQueryKey(
      explorationId,
      runId,
      selectedCompanyLinkId,
    ),
    queryFn: () =>
      listExplorationCompanyEvidence(explorationId, selectedCompanyLinkId),
    enabled: Boolean(selectedCompanyLinkId) && activeSection === "evidence",
    retry: false,
  });
  const factsQuery = useQuery({
    queryKey: explorationCompanyFactsQueryKey(
      explorationId,
      runId,
      selectedCompanyLinkId,
    ),
    queryFn: () =>
      listExplorationCompanyFacts(explorationId, selectedCompanyLinkId),
    enabled:
      Boolean(selectedCompanyLinkId) &&
      (activeSection === "facts" ||
        (activeSection === "hypotheses" && expandedHypothesisIds.size > 0)),
    retry: false,
  });
  const hypothesesQuery = useQuery({
    queryKey: explorationCompanyHypothesesQueryKey(
      explorationId,
      runId,
      selectedCompanyLinkId,
    ),
    queryFn: () =>
      listExplorationCompanyHypotheses(explorationId, selectedCompanyLinkId),
    enabled: Boolean(selectedCompanyLinkId) && activeSection === "hypotheses",
    retry: false,
  });
  const obligationsQuery = useQuery({
    queryKey: explorationObligationsQueryKey(explorationId),
    queryFn: () => listExplorationObligations(explorationId),
    enabled:
      Boolean(selectedCompanyLinkId) &&
      (activeSection === "evidence" ||
        ((activeSection === "facts" || activeSection === "hypotheses") &&
          expandedFactIds.size > 0)),
  });
  const runSummary = runsQuery.data?.find((run) => run.id === runId);
  const status = statusQuery.data?.status;
  const executionMutation = useMutation({
    mutationFn: () => executeExplorationRun(explorationId, runId),
    retry: false,
    onSuccess: async (result) => {
      setExecutionNeedsRefresh(false);
      queryClient.setQueryData(statusKey, (current: typeof statusQuery.data) =>
        current ? { ...current, status: result.status } : current,
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: statusKey }),
        queryClient.invalidateQueries({
          queryKey: explorationRunsQueryKey(explorationId),
        }),
      ]);
    },
    onError: async (error) => {
      setExecutionNeedsRefresh(true);
      if (error instanceof ApiError && error.status === 409) {
        const refreshed = await statusQuery.refetch();
        if (refreshed.isSuccess && refreshed.data) {
          setExecutionNeedsRefresh(false);
        }
      }
    },
  });

  useEffect(() => {
    if (!status) return;
    const previous = previousStatus.current;
    previousStatus.current = status;
    if (previous === status) return;
    if (previous !== undefined) {
      void queryClient.invalidateQueries({
        queryKey: explorationRunsQueryKey(explorationId),
      });
    }
    if (!isTerminalStatus(status)) return;

    void queryClient.invalidateQueries({
      queryKey: explorationRunCompaniesQueryKey(explorationId, runId),
    });
    void queryClient.invalidateQueries({
      queryKey: explorationCompanyEvidenceQueryKey(explorationId, runId),
    });
    void queryClient.invalidateQueries({
      queryKey: explorationCompanyFactsQueryKey(explorationId, runId),
    });
    void queryClient.invalidateQueries({
      queryKey: explorationCompanyHypothesesQueryKey(explorationId, runId),
    });
  }, [explorationId, queryClient, runId, status]);

  async function refreshStatus(): Promise<void> {
    const refreshed = await statusQuery.refetch();
    if (refreshed.isSuccess && refreshed.data) setExecutionNeedsRefresh(false);
  }

  function setExpanded(
    setter: Dispatch<SetStateAction<Set<string>>>,
    id: string,
    expanded: boolean,
  ): void {
    setter((current) => {
      const next = new Set(current);
      if (expanded) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  if (statusQuery.isPending) {
    return (
      <p role="status" className="mx-auto max-w-6xl p-8 text-center text-sm">
        Loading Exploration Run…
      </p>
    );
  }

  if (statusQuery.isError && !statusQuery.data) {
    const notFound =
      statusQuery.error instanceof ApiError && statusQuery.error.status === 404;
    return (
      <section className="mx-auto max-w-6xl">
        <BackToExploration explorationId={explorationId} />
        <div
          className="border-destructive/30 mt-5 rounded-lg border p-6"
          role="alert"
        >
          <h1 className="text-lg font-semibold">
            {notFound
              ? "Exploration Run not found"
              : "Exploration Run status could not be loaded"}
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            {notFound
              ? "This run may not belong to the requested Exploration."
              : "Check the connection and refresh the run status."}
          </p>
          {!notFound ? (
            <Button
              className="mt-4"
              onClick={() => void refreshStatus()}
              size="sm"
              variant="outline"
            >
              <RefreshCw aria-hidden="true" data-icon="inline-start" />
              Refresh status
            </Button>
          ) : null}
        </div>
      </section>
    );
  }

  const run = statusQuery.data;
  if (!run) return null;

  return (
    <section aria-labelledby="page-title" className="mx-auto max-w-6xl">
      <BackToExploration explorationId={explorationId} />
      <header className="mt-4 border-b pb-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
              Exploration Run
            </p>
            <h1
              id="page-title"
              className="text-2xl font-semibold tracking-tight"
            >
              {runSummary?.campaign_name ?? "Run details"}
            </h1>
            <p className="text-muted-foreground mt-1 font-mono text-xs">
              {run.id}
            </p>
          </div>
          <ExplorationStatusBadge status={run.status} />
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
          {runSummary ? (
            <Link
              className="text-primary inline-flex items-center gap-1 underline underline-offset-2"
              href={`/research/${runSummary.research_run_id}`}
            >
              Source Research Run
              <ExternalLink aria-hidden="true" className="size-3" />
            </Link>
          ) : runsQuery.isError ? (
            <span className="text-muted-foreground">
              Source Research Run details are unavailable.
            </span>
          ) : (
            <span className="text-muted-foreground" role="status">
              Loading source Research Run…
            </span>
          )}
          {runSummary ? (
            <span className="text-muted-foreground">
              {runSummary.selected_company_count} selected{" "}
              {runSummary.selected_company_count === 1
                ? "company"
                : "companies"}
            </span>
          ) : null}
          <span className="text-muted-foreground">
            {run.status === "READY" || run.status === "QUEUED"
              ? "Created"
              : "Started"}{" "}
            {formatDate(run.started_at)}
          </span>
          {run.completed_at ? (
            <span className="text-muted-foreground">
              Completed {formatDate(run.completed_at)}
            </span>
          ) : null}
          <Button
            onClick={() => void refreshStatus()}
            size="sm"
            variant="outline"
          >
            <RefreshCw aria-hidden="true" data-icon="inline-start" />
            Refresh status
          </Button>
        </div>

        <p
          className="bg-muted/40 mt-4 rounded-md px-3 py-2 text-sm"
          role="status"
        >
          {statusMessage(run.status)}
        </p>

        {run.status === "READY" ? (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button
              disabled={
                executionMutation.isPending ||
                executionNeedsRefresh ||
                statusQuery.isError
              }
              onClick={() => executionMutation.mutate()}
            >
              {executionMutation.isPending
                ? "Queueing run…"
                : "Execute Exploration"}
            </Button>
            {executionNeedsRefresh ? (
              <span className="text-muted-foreground text-sm">
                Refresh the persisted status before trying again.
              </span>
            ) : null}
          </div>
        ) : null}

        {executionMutation.isError ? (
          <p className="text-destructive mt-3 text-sm" role="alert">
            {executionErrorMessage(executionMutation.error)}
          </p>
        ) : null}
        {statusQuery.isError ? (
          <p className="text-destructive mt-3 text-sm" role="alert">
            Status refresh failed. Polling is paused; use Refresh status to try
            again.
          </p>
        ) : null}
      </header>

      <section aria-labelledby="companies-title" className="mt-6">
        <h2 id="companies-title" className="text-lg font-semibold">
          Selected company results
        </h2>
        {companiesQuery.isPending ? (
          <p
            className="text-muted-foreground mt-3 rounded-lg border p-5 text-sm"
            role="status"
          >
            Loading selected companies…
          </p>
        ) : companiesQuery.isError ? (
          <div
            className="border-destructive/30 mt-3 rounded-lg border p-5"
            role="alert"
          >
            <p className="text-sm font-medium">
              Selected companies could not be loaded.
            </p>
            <Button
              className="mt-3"
              onClick={() => void companiesQuery.refetch()}
              size="sm"
              variant="outline"
            >
              Try again
            </Button>
          </div>
        ) : companiesQuery.data.length === 0 ? (
          <p className="text-muted-foreground mt-3 rounded-lg border border-dashed p-5 text-sm">
            No companies were selected for this run.
          </p>
        ) : (
          <div className="mt-3 grid gap-5 lg:grid-cols-[minmax(14rem,0.35fr)_minmax(0,1fr)]">
            <div className="h-fit rounded-lg border p-4">
              <label className="text-sm font-medium" htmlFor="selected-company">
                Company
              </label>
              <select
                className="border-input bg-background mt-2 h-9 w-full rounded-md border px-3 text-sm"
                id="selected-company"
                onChange={(event) => {
                  setCompanyLinkId(event.target.value);
                  setExpandedHypothesisIds(new Set());
                  setExpandedFactIds(new Set());
                }}
                value={selectedCompanyLinkId}
              >
                {companiesQuery.data.map((company) => (
                  <option key={company.id} value={company.id}>
                    {company.name}
                  </option>
                ))}
              </select>
              {selectedCompany ? (
                <div className="mt-3 space-y-1 text-sm">
                  {selectedCompany.website ? (
                    <ExternalUrl href={selectedCompany.website}>
                      {selectedCompany.website}
                    </ExternalUrl>
                  ) : null}
                  {selectedCompany.domain ? (
                    <p className="text-muted-foreground">
                      {selectedCompany.domain}
                    </p>
                  ) : null}
                </div>
              ) : null}
            </div>

            {selectedCompany ? (
              <section
                aria-labelledby="result-navigation-title"
                className="min-w-0"
              >
                <h3 id="result-navigation-title" className="sr-only">
                  Company result types
                </h3>
                <div
                  aria-label="Company results"
                  className="flex flex-wrap gap-1.5"
                >
                  {resultSections.map((section) => (
                    <Button
                      aria-controls="company-results-panel"
                      aria-pressed={activeSection === section}
                      key={section}
                      onClick={() => setActiveSection(section)}
                      size="sm"
                      variant={
                        activeSection === section ? "secondary" : "ghost"
                      }
                    >
                      {capitalize(section)}
                    </Button>
                  ))}
                </div>
                <div
                  aria-labelledby={`results-${activeSection}-title`}
                  className="mt-3 rounded-lg border p-4 sm:p-5"
                  id="company-results-panel"
                >
                  {activeSection === "evidence" ? (
                    <EvidenceResults
                      query={evidenceQuery}
                      obligations={obligationsQuery.data ?? []}
                      obligationsPending={obligationsQuery.isPending}
                      obligationsError={obligationsQuery.isError}
                    />
                  ) : activeSection === "facts" ? (
                    <StatementResults
                      key={selectedCompanyLinkId}
                      title="Facts"
                      query={factsQuery}
                      kind="facts"
                      onFactToggle={(id, expanded) =>
                        setExpanded(setExpandedFactIds, id, expanded)
                      }
                      expandedFactIds={expandedFactIds}
                      evidenceQuery={evidenceQuery}
                    />
                  ) : (
                    <StatementResults
                      key={selectedCompanyLinkId}
                      title="Hypotheses"
                      query={hypothesesQuery}
                      kind="hypotheses"
                      onHypothesisToggle={(id, expanded) =>
                        setExpanded(setExpandedHypothesisIds, id, expanded)
                      }
                      factsQuery={factsQuery}
                      expandedFactIds={expandedFactIds}
                      onFactToggle={(id, expanded) =>
                        setExpanded(setExpandedFactIds, id, expanded)
                      }
                      evidenceQuery={evidenceQuery}
                    />
                  )}
                </div>
              </section>
            ) : null}
          </div>
        )}
      </section>
    </section>
  );
}

function EvidenceResults({
  query,
  obligations,
  obligationsPending,
  obligationsError,
}: {
  query: UseQueryResult<ExplorationEvidence[], Error>;
  obligations: Awaited<ReturnType<typeof listExplorationObligations>>;
  obligationsPending: boolean;
  obligationsError: boolean;
}) {
  if (query.isPending) return <LoadingResults label="Evidence" />;
  if (query.isError)
    return (
      <ErrorResults label="Evidence" onRetry={() => void query.refetch()} />
    );
  if (query.data.length === 0) return <EmptyResults label="Evidence" />;

  const obligationById = new Map(
    obligations.map((obligation) => [obligation.id, obligation.description]),
  );
  return (
    <>
      <h3 id="results-evidence-title" className="text-sm font-semibold">
        Evidence{" "}
        <span className="text-muted-foreground">({query.data.length})</span>
      </h3>
      {obligationsPending ? (
        <p className="text-muted-foreground mt-2 text-xs" role="status">
          Loading obligation descriptions…
        </p>
      ) : null}
      {obligationsError ? (
        <p className="text-muted-foreground mt-2 text-xs">
          Obligation descriptions are unavailable.
        </p>
      ) : null}
      <ul className="mt-3 space-y-3">
        {query.data.map((evidence) => (
          <li className="rounded-md border p-3" key={evidence.id}>
            <p className="font-medium">{evidence.claim}</p>
            <p className="mt-2 text-sm leading-6 whitespace-pre-wrap">
              {evidence.supporting_excerpt}
            </p>
            <p className="text-muted-foreground mt-2 text-xs">
              <span className="font-medium">Obligation:</span>{" "}
              {obligationById.get(evidence.exploration_obligation_id) ??
                (obligationsPending
                  ? "Loading description…"
                  : "Description unavailable")}
            </p>
            <div className="text-muted-foreground mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              {evidence.source_title ? (
                <span>{evidence.source_title}</span>
              ) : null}
              <time dateTime={evidence.created_at}>
                {formatDate(evidence.created_at)}
              </time>
              <ExternalUrl href={evidence.source_url}>Open source</ExternalUrl>
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

function StatementResults({
  title,
  query,
  kind,
  onHypothesisToggle,
  factsQuery,
  expandedFactIds = new Set(),
  onFactToggle,
  evidenceQuery,
}: {
  title: string;
  query:
    | UseQueryResult<ExplorationFact[], Error>
    | UseQueryResult<ExplorationHypothesis[], Error>;
  kind: "facts" | "hypotheses";
  onHypothesisToggle?: (id: string, expanded: boolean) => void;
  factsQuery?: UseQueryResult<ExplorationFact[], Error>;
  expandedFactIds?: Set<string>;
  onFactToggle?: (id: string, expanded: boolean) => void;
  evidenceQuery: UseQueryResult<ExplorationEvidence[], Error>;
}) {
  if (query.isPending) return <LoadingResults label={title} />;
  if (query.isError)
    return <ErrorResults label={title} onRetry={() => void query.refetch()} />;
  if (!query.data) return <LoadingResults label={title} />;
  if (query.data.length === 0) return <EmptyResults label={title} />;

  return (
    <>
      <h3 id={`results-${kind}-title`} className="text-sm font-semibold">
        {title}{" "}
        <span className="text-muted-foreground">({query.data.length})</span>
      </h3>
      <ul className="mt-3 space-y-2">
        {kind === "facts"
          ? (query.data as ExplorationFact[]).map((fact) => (
              <li className="rounded-md border p-3" key={fact.id}>
                <p className="text-sm leading-6">{fact.statement}</p>
                <AddedAt date={fact.created_at} />
                {onFactToggle ? (
                  <FactEvidenceDisclosure
                    fact={fact}
                    expanded={expandedFactIds.has(fact.id)}
                    onToggle={onFactToggle}
                    evidenceQuery={evidenceQuery}
                  />
                ) : null}
              </li>
            ))
          : (query.data as ExplorationHypothesis[]).map((hypothesis) => (
              <li className="rounded-md border p-3" key={hypothesis.id}>
                <p className="text-sm leading-6">{hypothesis.statement}</p>
                <AddedAt date={hypothesis.created_at} />
                <details
                  className="border-border mt-3 rounded-md border px-3 py-2"
                  onToggle={(event) =>
                    onHypothesisToggle?.(
                      hypothesis.id,
                      event.currentTarget.open &&
                        hypothesis.fact_ids.length > 0,
                    )
                  }
                >
                  <summary className="cursor-pointer text-sm font-medium">
                    Supporting Facts ({hypothesis.fact_ids.length})
                  </summary>
                  {hypothesis.fact_ids.length === 0 ? (
                    <p className="text-muted-foreground mt-2 text-sm">
                      No supporting Facts are recorded.
                    </p>
                  ) : !factsQuery || factsQuery.isPending ? (
                    <LoadingResults label="Supporting Facts" />
                  ) : factsQuery.isError ? (
                    <ErrorResults
                      label="Supporting Facts"
                      onRetry={() => void factsQuery.refetch()}
                    />
                  ) : (
                    <ul className="mt-3 space-y-2">
                      {hypothesis.fact_ids.map((factId) => {
                        const fact = factsQuery.data.find(
                          (candidate) => candidate.id === factId,
                        );
                        return fact ? (
                          <li className="rounded-md border p-3" key={factId}>
                            <p className="text-sm leading-6">
                              {fact.statement}
                            </p>
                            <FactEvidenceDisclosure
                              fact={fact}
                              expanded={expandedFactIds.has(fact.id)}
                              onToggle={onFactToggle ?? (() => undefined)}
                              evidenceQuery={evidenceQuery}
                            />
                          </li>
                        ) : (
                          <li
                            className="text-muted-foreground text-sm"
                            key={factId}
                          >
                            Supporting Fact unavailable for this company.
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </details>
              </li>
            ))}
      </ul>
    </>
  );
}

function AddedAt({ date }: { date: string }) {
  return (
    <time className="text-muted-foreground mt-2 block text-xs" dateTime={date}>
      Added {formatDate(date)}
    </time>
  );
}

function FactEvidenceDisclosure({
  fact,
  expanded,
  onToggle,
  evidenceQuery,
}: {
  fact: ExplorationFact;
  expanded: boolean;
  onToggle: (id: string, expanded: boolean) => void;
  evidenceQuery: UseQueryResult<ExplorationEvidence[], Error>;
}) {
  return (
    <details
      className="border-border mt-3 rounded-md border px-3 py-2"
      onToggle={(event) =>
        onToggle(
          fact.id,
          event.currentTarget.open && fact.evidence_ids.length > 0,
        )
      }
    >
      <summary className="cursor-pointer text-sm font-medium">
        Supporting Evidence ({fact.evidence_ids.length})
      </summary>
      {fact.evidence_ids.length === 0 ? (
        <p className="text-muted-foreground mt-2 text-sm">
          No supporting Evidence is recorded.
        </p>
      ) : !expanded || evidenceQuery.isPending ? (
        <LoadingResults label="Supporting Evidence" />
      ) : evidenceQuery.isError ? (
        <ErrorResults
          label="Supporting Evidence"
          onRetry={() => void evidenceQuery.refetch()}
        />
      ) : (
        <ul className="mt-3 space-y-2">
          {fact.evidence_ids.map((evidenceId) => {
            const evidence = evidenceQuery.data.find(
              (candidate) => candidate.id === evidenceId,
            );
            return evidence ? (
              <li className="rounded-md border p-3" key={evidenceId}>
                <p className="font-medium">{evidence.claim}</p>
                <p className="mt-2 text-sm leading-6 whitespace-pre-wrap">
                  {evidence.supporting_excerpt}
                </p>
                <div className="text-muted-foreground mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                  {evidence.source_title ? (
                    <span>{evidence.source_title}</span>
                  ) : null}
                  <ExternalUrl href={evidence.source_url}>
                    Open source
                  </ExternalUrl>
                </div>
              </li>
            ) : (
              <li className="text-muted-foreground text-sm" key={evidenceId}>
                Supporting Evidence unavailable for this company.
              </li>
            );
          })}
        </ul>
      )}
    </details>
  );
}

function LoadingResults({ label }: { label: string }) {
  return (
    <p className="text-muted-foreground text-sm" role="status">
      Loading {label.toLowerCase()}…
    </p>
  );
}

function ErrorResults({
  label,
  onRetry,
}: {
  label: string;
  onRetry: () => void;
}) {
  return (
    <div role="alert">
      <p className="text-destructive text-sm">{label} could not be loaded.</p>
      <Button className="mt-3" onClick={onRetry} size="sm" variant="outline">
        Try again
      </Button>
    </div>
  );
}

function EmptyResults({ label }: { label: string }) {
  return (
    <div className="rounded-md border border-dashed p-6 text-center">
      <h3
        className="text-sm font-semibold"
        id={`results-${label.toLowerCase()}-title`}
      >
        No {label.toLowerCase()} yet
      </h3>
      <p className="text-muted-foreground mt-1 text-sm">
        No {label.toLowerCase()} have been persisted for this company.
      </p>
    </div>
  );
}

function ExplorationStatusBadge({ status }: { status: ExplorationRunStatus }) {
  const tone =
    status === "COMPLETED"
      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
      : status === "FAILED"
        ? "bg-destructive/10 text-destructive"
        : status === "PARTIAL"
          ? "bg-amber-500/10 text-amber-800 dark:text-amber-300"
          : status === "CANCELLED"
            ? "bg-muted text-muted-foreground"
            : "bg-amber-500/10 text-amber-700 dark:text-amber-300";
  return (
    <Badge className={tone} variant="secondary">
      {status}
    </Badge>
  );
}

function statusMessage(status: ExplorationRunStatus): string {
  switch (status) {
    case "READY":
      return "This run is ready to execute.";
    case "QUEUED":
      return "This run is queued and waiting to start.";
    case "RUNNING":
      return "Exploration is in progress. Results may appear as they are saved.";
    case "COMPLETED":
      return "Exploration completed. Review the persisted results below.";
    case "PARTIAL":
      return "Exploration partially completed. Review any results that were saved.";
    case "FAILED":
      return "Exploration failed. Any persisted results are still available below.";
    case "CANCELLED":
      return "Exploration was cancelled. Any persisted results are still available below.";
  }
}

function isTerminalStatus(status: ExplorationRunStatus): boolean {
  return (
    status === "COMPLETED" ||
    status === "PARTIAL" ||
    status === "FAILED" ||
    status === "CANCELLED"
  );
}

export function explorationRunStatusPollingInterval(
  status: ExplorationRunStatus | undefined,
  hasError: boolean,
): number | false {
  if (hasError) return false;
  return status === "QUEUED" || status === "RUNNING" ? POLL_INTERVAL_MS : false;
}

function executionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return "This run was not found for the selected Exploration.";
    }
    if (error.status === 409) {
      return "The run was already claimed or changed. Its persisted status has been refreshed.";
    }
    if (error.status >= 500) {
      return "The run could not be scheduled. Refresh its status before trying again.";
    }
  }
  return "The run could not be scheduled. Refresh its status before trying again.";
}

function ExternalUrl({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  const safeHref = safeHttpUrl(href);
  if (!safeHref) return null;
  return (
    <a
      className="text-primary inline-flex items-center gap-1 underline underline-offset-2"
      href={safeHref}
      rel="noreferrer noopener"
      target="_blank"
    >
      {children}
      <ExternalLink aria-hidden="true" className="size-3" />
    </a>
  );
}

function safeHttpUrl(value: string): string | null {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:"
      ? parsed.href
      : null;
  } catch {
    return null;
  }
}

function BackToExploration({ explorationId }: { explorationId: string }) {
  return (
    <Link
      className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-sm"
      href={`/explorations/${explorationId}`}
    >
      <ArrowLeft aria-hidden="true" className="size-4" />
      Back to Exploration
    </Link>
  );
}

function capitalize(value: string): string {
  return `${value.slice(0, 1).toUpperCase()}${value.slice(1)}`;
}
