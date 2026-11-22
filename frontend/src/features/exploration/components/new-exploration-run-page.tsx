"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";

import { ResearchCompanyCard } from "@/features/research/components/results/research-company-card";
import { formatDate } from "@/lib/format-date";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import {
  executeExplorationRun,
  startExplorationRun,
} from "@/features/exploration/api/explorations";
import {
  getResearchRunResults,
  listResearchRuns,
} from "@/features/research/api/research";
import {
  explorationQueryKey,
  explorationRunsQueryKey,
} from "@/features/exploration/query-keys";
import {
  researchRunResultsQueryKey,
  researchRunsQueryKey,
} from "@/features/research/query-keys";
import { cn } from "@/lib/utils";

type StartSelection = {
  researchRunId: string;
  companyIds: string[];
  action: "save" | "execute";
};

export function NewExplorationRunPage({
  explorationId,
}: {
  explorationId: string;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [selectedRunId, setSelectedRunId] = useState("");
  const [selectedCompanyIds, setSelectedCompanyIds] = useState<Set<string>>(
    () => new Set(),
  );
  const submitLock = useRef(false);

  const researchRunsQuery = useQuery({
    queryKey: researchRunsQueryKey,
    queryFn: listResearchRuns,
  });
  const completedRuns = useMemo(
    () =>
      [...(researchRunsQuery.data ?? [])]
        .filter((run) => run.status === "COMPLETED")
        .sort((left, right) => {
          const leftTimestamp = Date.parse(
            left.completed_at ?? left.started_at ?? left.created_at,
          );
          const rightTimestamp = Date.parse(
            right.completed_at ?? right.started_at ?? right.created_at,
          );
          const leftOrder = Number.isNaN(leftTimestamp)
            ? Number.NEGATIVE_INFINITY
            : leftTimestamp;
          const rightOrder = Number.isNaN(rightTimestamp)
            ? Number.NEGATIVE_INFINITY
            : rightTimestamp;

          if (leftOrder !== rightOrder) return rightOrder - leftOrder;
          return left.run_id.localeCompare(right.run_id);
        }),
    [researchRunsQuery.data],
  );
  const resultsQuery = useQuery({
    queryKey: researchRunResultsQueryKey(selectedRunId),
    queryFn: () => getResearchRunResults(selectedRunId),
    enabled: Boolean(selectedRunId),
  });
  const selectedRunResults =
    resultsQuery.data?.research_run.id === selectedRunId
      ? resultsQuery.data
      : undefined;
  const companies = selectedRunResults?.companies ?? [];
  const currentSelectedCompanyIds = companies
    .filter((company) => selectedCompanyIds.has(company.company_id))
    .map((company) => company.company_id);
  const sourceRunCompleted =
    selectedRunResults?.research_run.status === "COMPLETED";

  const startMutation = useMutation({
    mutationFn: async ({
      researchRunId,
      companyIds,
      action,
    }: StartSelection) => {
      const run = await startExplorationRun(explorationId, {
        research_run_id: researchRunId,
        company_ids: companyIds,
      });
      if (action === "save") return { run, executionUnconfirmed: false };

      try {
        await executeExplorationRun(explorationId, run.id);
        return { run, executionUnconfirmed: false };
      } catch {
        return { run, executionUnconfirmed: true };
      }
    },
    onSuccess: async ({ run, executionUnconfirmed }) => {
      setSelectedRunId("");
      setSelectedCompanyIds(new Set());
      await queryClient.invalidateQueries({
        queryKey: explorationRunsQueryKey(explorationId),
      });
      await queryClient.invalidateQueries({
        queryKey: explorationQueryKey(explorationId),
      });
      const path = `/explorations/${explorationId}/runs/${run.id}`;
      router.push(
        executionUnconfirmed ? `${path}?execution=unconfirmed` : path,
      );
    },
    onSettled: () => {
      submitLock.current = false;
    },
  });

  function chooseResearchRun(researchRunId: string) {
    if (researchRunId === selectedRunId) return;
    setSelectedCompanyIds(new Set());
    setSelectedRunId(researchRunId);
    startMutation.reset();
  }

  function setCompanySelected(companyId: string, selected: boolean) {
    setSelectedCompanyIds((current) => {
      const next = new Set(current);
      if (selected) next.add(companyId);
      else next.delete(companyId);
      return next;
    });
    startMutation.reset();
  }

  function submit(action: StartSelection["action"]) {
    if (
      submitLock.current ||
      !selectedRunResults ||
      !sourceRunCompleted ||
      currentSelectedCompanyIds.length === 0
    ) {
      return;
    }
    submitLock.current = true;
    startMutation.mutate({
      researchRunId: selectedRunId,
      companyIds: currentSelectedCompanyIds,
      action,
    });
  }

  const submissionDisabled =
    startMutation.isPending ||
    !selectedRunResults ||
    !sourceRunCompleted ||
    currentSelectedCompanyIds.length === 0;

  return (
    <section aria-labelledby="page-title" className="mx-auto max-w-6xl">
      <Link
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-sm"
        href={`/explorations/${explorationId}`}
      >
        <ArrowLeft aria-hidden="true" className="size-4" />
        Back to Exploration
      </Link>

      <header className="mt-4 border-b pb-5">
        <p className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
          Exploration
        </p>
        <h1 id="page-title" className="text-2xl font-semibold tracking-tight">
          New Exploration Run
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Choose one completed Research Run, then select companies from its
          results.
        </p>
      </header>

      <div className="mt-6 space-y-6">
        <fieldset className="min-w-0 space-y-3">
          <legend className="text-lg font-semibold">1. Research Run</legend>
          {researchRunsQuery.isPending ? (
            <p
              className="text-muted-foreground rounded-lg border p-5 text-sm"
              role="status"
            >
              Loading completed Research Runs…
            </p>
          ) : researchRunsQuery.isError ? (
            <div
              className="border-destructive/30 rounded-lg border p-5"
              role="alert"
            >
              <p className="text-sm font-medium">
                Research Runs could not be loaded
              </p>
              <p className="text-muted-foreground mt-1 text-sm">
                Try again to load available completed runs.
              </p>
              <Button
                className="mt-3"
                onClick={() => void researchRunsQuery.refetch()}
                size="sm"
                variant="outline"
              >
                <RefreshCw aria-hidden="true" data-icon="inline-start" />
                Try again
              </Button>
            </div>
          ) : completedRuns.length === 0 ? (
            <p className="text-muted-foreground rounded-lg border border-dashed p-5 text-sm">
              No completed Research Runs are available. Complete a Research Run
              before starting an Exploration Run.
            </p>
          ) : (
            <div className="overflow-hidden rounded-lg border">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-left text-sm">
                  <thead className="bg-muted/50 text-muted-foreground border-b text-xs">
                    <tr>
                      <th className="w-10 px-3 py-3" scope="col">
                        <span className="sr-only">Select</span>
                      </th>
                      <th className="px-3 py-3 font-medium" scope="col">
                        Campaign
                      </th>
                      <th className="px-3 py-3 font-medium" scope="col">
                        Completed
                      </th>
                      <th
                        className="px-3 py-3 text-right font-medium"
                        scope="col"
                      >
                        Researched
                      </th>
                      <th className="px-3 py-3 font-medium" scope="col">
                        Results
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {completedRuns.map((run) => {
                      const completedAt = formatDate(run.completed_at);
                      const selected = selectedRunId === run.run_id;
                      return (
                        <tr
                          className={cn(
                            "hover:bg-muted/30 focus-within:bg-muted/30 cursor-pointer transition-colors",
                            selected && "bg-primary/5 hover:bg-primary/10",
                            startMutation.isPending &&
                              "cursor-not-allowed opacity-70",
                          )}
                          key={run.run_id}
                          onClick={(event) => {
                            if (
                              event.target instanceof Element &&
                              event.target.closest("input[type='radio']")
                            ) {
                              return;
                            }
                            chooseResearchRun(run.run_id);
                          }}
                        >
                          <td className="px-3 py-3">
                            <input
                              aria-label={`Select ${run.campaign.name}, completed ${completedAt}, Research Run ${run.run_id}`}
                              checked={selected}
                              className="border-input accent-primary focus-visible:ring-ring size-4 cursor-pointer rounded-full focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
                              disabled={startMutation.isPending}
                              name="research-run"
                              onChange={() => chooseResearchRun(run.run_id)}
                              type="radio"
                            />
                          </td>
                          <td className="px-3 py-3 font-medium">
                            {run.campaign.name}
                          </td>
                          <td className="px-3 py-3 whitespace-nowrap">
                            <div className="flex items-center gap-2">
                              <Badge variant="secondary">COMPLETED</Badge>
                              <span>{completedAt}</span>
                            </div>
                          </td>
                          <td className="px-3 py-3 text-right tabular-nums">
                            {run.summary.researched}
                          </td>
                          <td className="text-muted-foreground px-3 py-3 text-xs">
                            <span className="whitespace-nowrap">
                              {run.summary.qualified} qualified
                            </span>
                            <span aria-hidden="true"> · </span>
                            <span className="whitespace-nowrap">
                              {run.summary.not_qualified} not qualified
                            </span>
                            <span aria-hidden="true"> · </span>
                            <span className="whitespace-nowrap">
                              {run.summary.insufficient_evidence} insufficient
                              evidence
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </fieldset>

        {selectedRunId ? (
          <section aria-labelledby="companies-title" className="space-y-4">
            <div className="flex flex-wrap items-end justify-between gap-3 border-t pt-5">
              <div>
                <h2 id="companies-title" className="text-lg font-semibold">
                  2. Companies
                </h2>
                <p className="text-muted-foreground mt-1 text-sm">
                  All qualification statuses are selectable. Companies come only
                  from the selected Research Run.
                </p>
              </div>
              {selectedRunResults ? (
                <span aria-live="polite" className="text-sm font-medium">
                  {currentSelectedCompanyIds.length} companies selected
                </span>
              ) : null}
            </div>

            {resultsQuery.isPending ? (
              <p
                className="text-muted-foreground rounded-lg border p-5 text-sm"
                role="status"
              >
                Loading results from the selected Research Run…
              </p>
            ) : resultsQuery.isError ? (
              <div
                className="border-destructive/30 rounded-lg border p-5"
                role="alert"
              >
                <p className="text-sm font-medium">
                  Research Run results could not be loaded
                </p>
                <p className="text-muted-foreground mt-1 text-sm">
                  {"status" in resultsQuery.error &&
                  resultsQuery.error.status === 404
                    ? "This Research Run is no longer available. Choose another completed run."
                    : "Try again to load this Research Run's results."}
                </p>
                <Button
                  className="mt-3"
                  onClick={() => void resultsQuery.refetch()}
                  size="sm"
                  variant="outline"
                >
                  Try again
                </Button>
              </div>
            ) : selectedRunResults && !sourceRunCompleted ? (
              <p
                className="text-destructive border-destructive/30 rounded-lg border p-5 text-sm"
                role="alert"
              >
                This Research Run is no longer completed. Choose another
                completed Research Run.
              </p>
            ) : companies.length === 0 ? (
              <p className="text-muted-foreground rounded-lg border border-dashed p-6 text-sm">
                This Research Run has no company results to select.
              </p>
            ) : (
              <>
                <div className="flex flex-wrap gap-2">
                  <Button
                    disabled={startMutation.isPending}
                    onClick={() =>
                      setSelectedCompanyIds(
                        new Set(companies.map((company) => company.company_id)),
                      )
                    }
                    size="sm"
                    variant="outline"
                  >
                    Select all
                  </Button>
                  <Button
                    disabled={
                      startMutation.isPending ||
                      currentSelectedCompanyIds.length === 0
                    }
                    onClick={() => setSelectedCompanyIds(new Set())}
                    size="sm"
                    variant="ghost"
                  >
                    Clear selection
                  </Button>
                </div>
                <div className="space-y-3">
                  {companies.map((company) => (
                    <ResearchCompanyCard
                      company={company}
                      key={company.company_id}
                      onSelectedChange={(selected) =>
                        setCompanySelected(company.company_id, selected)
                      }
                      selected={selectedCompanyIds.has(company.company_id)}
                    />
                  ))}
                </div>
              </>
            )}

            {startMutation.isError ? (
              <div
                className="border-destructive/30 rounded-lg border p-4"
                role="alert"
              >
                <h3 className="text-sm font-semibold">
                  Exploration Run could not be saved
                </h3>
                <p className="text-destructive mt-1 text-sm">
                  {startErrorMessage(startMutation.error)}
                </p>
              </div>
            ) : null}

            <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
              <p className="text-muted-foreground text-xs">
                Save for Later keeps this Run ready to execute. Save & Execute
                starts it now.
              </p>
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  disabled={submissionDisabled}
                  onClick={() => submit("save")}
                  type="button"
                  variant="outline"
                >
                  {startMutation.isPending &&
                  startMutation.variables?.action === "save"
                    ? "Saving for later…"
                    : "Save for Later"}
                </Button>
                <Button
                  disabled={submissionDisabled}
                  onClick={() => submit("execute")}
                  type="button"
                >
                  {startMutation.isPending &&
                  startMutation.variables?.action === "execute"
                    ? "Saving & executing…"
                    : "Save & Execute"}
                </Button>
              </div>
            </div>
          </section>
        ) : null}
      </div>
    </section>
  );
}

function startErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 400) {
      return "One or more selected companies are no longer in this Research Run. Review the selection and try again.";
    }
    if (error.status === 404) {
      return "The Exploration or Research Run is no longer available. Return to the Exploration and try again.";
    }
    if (error.status === 409) {
      return "This Research Run is no longer eligible. Choose another completed Research Run.";
    }
    if (error.status === 422) {
      return "The selection could not be validated. Choose one or more companies and try again.";
    }
  }
  return "We couldn't start this Exploration Run. Please try again.";
}
