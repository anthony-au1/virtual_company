"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Pencil, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { RunStatus } from "@/features/research/components/runs/run-status-badge";
import { isTerminalRunStatus } from "@/features/research/status";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { DeleteRunAction } from "@/features/research/components/runs/delete-run-action";
import { DeleteCampaignAction } from "@/features/research/components/campaigns/delete-campaign-action";
import { getCampaign, type Campaign } from "@/features/research/api/campaigns";
import { apiErrorMessages } from "@/lib/api/client";
import {
  listResearchRuns,
  startResearch,
} from "@/features/research/api/research";
import {
  campaignQueryKey,
  researchRunsQueryKey,
} from "@/features/research/query-keys";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/format-date";

const CAMPAIGN_DELETE_DISABLED_REASON =
  "Campaigns with Research history cannot be deleted.";

export function CampaignDetailsPage({ campaignId }: { campaignId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [startedRunId, setStartedRunId] = useState<string | null>(null);
  const campaignQuery = useQuery({
    queryKey: campaignQueryKey(campaignId),
    queryFn: () => getCampaign(campaignId),
  });
  const runsQuery = useQuery({
    queryKey: researchRunsQueryKey,
    queryFn: listResearchRuns,
    refetchInterval: (current) =>
      current.state.data?.some((run) => !isTerminalRunStatus(run.status))
        ? 2000
        : false,
  });
  const startMutation = useMutation({
    mutationKey: ["start-research", campaignId],
    mutationFn: () => startResearch(campaignId),
    onSuccess: (result) => {
      setStartedRunId(result.research_run_id);
      void queryClient.invalidateQueries({ queryKey: researchRunsQueryKey });
      void queryClient.invalidateQueries({
        queryKey: campaignQueryKey(campaignId),
      });
      router.push(`/research/${result.research_run_id}`);
    },
  });
  const campaignRuns = useMemo(
    () =>
      (runsQuery.data ?? [])
        .filter((run) => run.campaign.id === campaignId)
        .sort((a, b) =>
          (b.started_at ?? b.created_at).localeCompare(
            a.started_at ?? a.created_at,
          ),
        ),
    [campaignId, runsQuery.data],
  );
  const activeRun = campaignRuns.find(
    (run) => !isTerminalRunStatus(run.status),
  );
  const locallyActive =
    startedRunId !== null &&
    !campaignRuns.some(
      (run) => run.run_id === startedRunId && isTerminalRunStatus(run.status),
    );

  if (campaignQuery.isPending) {
    return (
      <div
        role="status"
        className="text-muted-foreground mx-auto max-w-5xl rounded-lg border p-8 text-center text-sm"
      >
        Loading campaign…
      </div>
    );
  }
  if (campaignQuery.isError) {
    const notFound =
      "status" in campaignQuery.error && campaignQuery.error.status === 404;
    return (
      <section className="mx-auto max-w-5xl">
        <BackToCampaigns />
        <div
          role="alert"
          className="border-destructive/30 mt-5 rounded-lg border p-6"
        >
          <h1 className="text-lg font-semibold">
            {notFound ? "Campaign not found" : "Campaign could not be loaded"}
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            {campaignQuery.error.message}
          </p>
          {!notFound ? (
            <Button
              className="mt-4"
              onClick={() => void campaignQuery.refetch()}
              size="sm"
              variant="outline"
            >
              <RefreshCw aria-hidden="true" data-icon="inline-start" />
              Try again
            </Button>
          ) : null}
        </div>
      </section>
    );
  }

  const campaign = campaignQuery.data;
  const cannotDelete =
    campaign.sealed_at !== null ||
    (runsQuery.isSuccess && campaignRuns.length > 0);
  const startDisabled =
    startMutation.isPending ||
    runsQuery.isPending ||
    runsQuery.isError ||
    Boolean(activeRun) ||
    locallyActive;

  return (
    <section aria-labelledby="page-title" className="mx-auto max-w-6xl">
      <BackToCampaigns />
      <header className="mt-4 flex flex-col gap-5 border-b pb-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <p className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
            Campaign workspace
          </p>
          <h1 id="page-title" className="text-2xl font-semibold tracking-tight">
            {campaign.name}
          </h1>
          {campaign.description ? (
            <p className="text-muted-foreground mt-2 max-w-3xl text-sm leading-6">
              {campaign.description}
            </p>
          ) : null}
          <p className="text-muted-foreground mt-2 text-sm">
            {[campaign.target_market, campaign.industry]
              .filter(Boolean)
              .join(" · ") || "No market or industry specified"}
          </p>
        </div>
        <div className="flex flex-wrap items-start gap-2 lg:justify-end">
          <div className="flex flex-col items-end gap-1">
            <div className="flex flex-wrap justify-end gap-2">
              {campaign.sealed_at === null ? (
                <Link
                  className={cn(buttonVariants({ variant: "outline" }))}
                  href={`/campaigns/${campaignId}/edit`}
                >
                  <Pencil aria-hidden="true" data-icon="inline-start" />
                  Edit Campaign
                </Link>
              ) : null}
              <DeleteCampaignAction
                campaignId={campaignId}
                disabled={cannotDelete}
                disabledReason={
                  cannotDelete ? CAMPAIGN_DELETE_DISABLED_REASON : undefined
                }
              />
              <Button
                disabled={startDisabled}
                onClick={() => startMutation.mutate()}
              >
                {startMutation.isPending
                  ? "Starting research…"
                  : activeRun || locallyActive
                    ? "Research in progress"
                    : runsQuery.isPending
                      ? "Checking run history…"
                      : runsQuery.isError
                        ? "Run status unavailable"
                        : "Start Research"}
                {!startMutation.isPending &&
                !activeRun &&
                !runsQuery.isPending &&
                !runsQuery.isError ? (
                  <ArrowRight aria-hidden="true" data-icon="inline-end" />
                ) : null}
              </Button>
            </div>
            {campaign.sealed_at !== null ? (
              <p className="text-muted-foreground max-w-sm text-right text-xs">
                Research criteria are locked after the first execution.
              </p>
            ) : null}
            {runsQuery.isPending ? (
              <p className="text-muted-foreground max-w-sm text-right text-xs">
                Checking for an active Research Run before allowing a new one.
              </p>
            ) : runsQuery.isError ? (
              <p className="text-destructive max-w-sm text-right text-xs">
                Retry Run history to verify that no Research is active.
              </p>
            ) : null}
          </div>
        </div>
      </header>

      {startMutation.isError ? (
        <div
          role="alert"
          className="border-destructive/30 mt-4 rounded-lg border p-4"
        >
          <h2 className="text-sm font-semibold">
            Research could not be started
          </h2>
          <ul className="text-destructive mt-2 list-inside list-disc space-y-1 text-sm">
            {apiErrorMessages(startMutation.error).map((message, index) => (
              <li key={`${index}-${message}`}>{message}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.8fr)]">
        <section
          aria-labelledby="configuration-title"
          className="rounded-lg border p-4 sm:p-5"
        >
          <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
            <h2 id="configuration-title" className="text-base font-semibold">
              Research configuration
            </h2>
            <p className="text-muted-foreground text-xs">
              Created {formatDate(campaign.created_at)}
            </p>
          </div>
          <dl className="mb-5 grid gap-3 sm:grid-cols-2">
            <Detail
              label="Target qualified companies"
              value={`${campaign.target_count}`}
            />
            <Detail
              label="Maximum companies to research"
              value={`${campaign.max_companies_to_research}`}
            />
          </dl>
          <div className="grid gap-4 sm:grid-cols-2">
            <CriteriaList title="Market and industry">
              {campaign.target_market ? (
                <CriteriaRow label="Market" value={campaign.target_market} />
              ) : null}
              {campaign.industry ? (
                <CriteriaRow label="Industry" value={campaign.industry} />
              ) : null}
              {!campaign.target_market && !campaign.industry ? (
                <EmptyCriteria />
              ) : null}
            </CriteriaList>
            <CriteriaList title="Keywords and company size">
              {campaign.keywords.map((keyword) => (
                <CriteriaRow key={keyword} label="Keyword" value={keyword} />
              ))}
              {sizeRows(campaign)}
              {campaign.keywords.length === 0 &&
              campaign.company_size?.min == null &&
              campaign.company_size?.max == null ? (
                <EmptyCriteria />
              ) : null}
            </CriteriaList>
          </div>
        </section>

        <section
          aria-labelledby="history-title"
          className="rounded-lg border p-4 sm:p-5"
        >
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h2 id="history-title" className="text-base font-semibold">
                Research Run history
              </h2>
              <p className="text-muted-foreground mt-1 text-xs">
                Each execution is saved separately under this Campaign.
              </p>
            </div>
            {runsQuery.isSuccess ? (
              <Badge variant="secondary">
                {campaignRuns.length}{" "}
                {campaignRuns.length === 1 ? "run" : "runs"}
              </Badge>
            ) : null}
          </div>

          {activeRun ? (
            <div
              className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-amber-500/30 bg-amber-500/5 p-3"
              role="status"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-medium">Active Run</span>
                <RunStatus status={activeRun.status} />
                <span className="text-muted-foreground text-xs">
                  Started{" "}
                  {formatDate(activeRun.started_at ?? activeRun.created_at)}
                </span>
              </div>
              <Link
                className={cn(
                  buttonVariants({ size: "sm", variant: "outline" }),
                )}
                href={`/research/${activeRun.run_id}`}
              >
                Open active Run
                <ArrowRight aria-hidden="true" data-icon="inline-end" />
              </Link>
            </div>
          ) : null}

          {runsQuery.isPending ? (
            <p role="status" className="text-muted-foreground mt-4 text-sm">
              Loading Research Run history…
            </p>
          ) : runsQuery.isError ? (
            <div role="alert" className="mt-4">
              <p className="text-destructive text-sm">
                Research Run history could not be loaded.
              </p>
              <Button
                className="mt-2"
                onClick={() => void runsQuery.refetch()}
                size="sm"
                variant="outline"
              >
                <RefreshCw aria-hidden="true" data-icon="inline-start" />
                Retry history
              </Button>
            </div>
          ) : campaignRuns.length === 0 ? (
            <p className="text-muted-foreground mt-4 text-sm">
              No Research Runs yet. Start Research to create the first
              execution.
            </p>
          ) : (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[700px] text-left text-sm">
                <thead className="text-muted-foreground border-b text-xs">
                  <tr>
                    <th className="px-3 py-2 font-medium" scope="col">
                      Run date and time
                    </th>
                    <th className="px-3 py-2 font-medium" scope="col">
                      Run status
                    </th>
                    <th className="px-3 py-2 font-medium" scope="col">
                      Outcomes
                    </th>
                    <th className="px-3 py-2 font-medium" scope="col">
                      Duration
                    </th>
                    <th className="px-3 py-2" scope="col">
                      Results
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {campaignRuns.map((run) => (
                    <tr key={run.run_id}>
                      <td className="px-3 py-3 whitespace-nowrap">
                        {formatDate(run.started_at ?? run.created_at)}
                      </td>
                      <td className="px-3 py-3">
                        <div className="space-y-1">
                          <span className="text-muted-foreground block text-[10px] tracking-wide uppercase">
                            Run
                          </span>
                          <RunStatus status={run.status} />
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        {run.summary.researched === 0 &&
                        !isTerminalRunStatus(run.status) ? (
                          <span className="text-muted-foreground text-xs">
                            Awaiting results
                          </span>
                        ) : (
                          <div className="tabular-nums">
                            <p>{run.summary.researched} researched</p>
                            <p className="text-muted-foreground mt-1 text-xs">
                              {run.summary.qualified} qualified ·{" "}
                              {run.summary.not_qualified} not qualified ·{" "}
                              {run.summary.insufficient_evidence} insufficient
                            </p>
                          </div>
                        )}
                      </td>
                      <td className="text-muted-foreground px-3 py-3 whitespace-nowrap">
                        {formatRunDuration(
                          run.started_at,
                          run.completed_at,
                          run.status,
                        )}
                      </td>
                      <td className="px-3 py-3 text-right">
                        <div className="flex justify-end gap-2">
                          <Link
                            aria-label={`Open results for run started ${formatDate(
                              run.started_at ?? run.created_at,
                            )}`}
                            className={cn(
                              buttonVariants({
                                size: "sm",
                                variant: "ghost",
                              }),
                            )}
                            href={`/research/${run.run_id}`}
                          >
                            Open results
                            <ArrowRight
                              aria-hidden="true"
                              data-icon="inline-end"
                            />
                          </Link>
                          {isTerminalRunStatus(run.status) ? (
                            <DeleteRunAction runId={run.run_id} />
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </section>
  );
}

function BackToCampaigns() {
  return (
    <Link
      className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-sm"
      href="/research"
    >
      <ArrowLeft aria-hidden="true" className="size-4" />
      Campaigns
    </Link>
  );
}

function Detail({
  label,
  value,
  wide = false,
}: {
  label: string;
  value: string;
  wide?: boolean;
}) {
  return (
    <div className={wide ? "sm:col-span-2" : ""}>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="mt-1 text-sm whitespace-pre-wrap">{value}</dd>
    </div>
  );
}

function CriteriaList({
  title,
  children,
}: React.PropsWithChildren<{ title: string }>) {
  return (
    <div>
      <h3 className="text-muted-foreground mb-2 text-xs font-semibold tracking-wide uppercase">
        {title}
      </h3>
      <ul className="space-y-2">{children}</ul>
    </div>
  );
}

function CriteriaRow({ label, value }: { label: string; value: string }) {
  return (
    <li className="flex items-start justify-between gap-3 text-sm">
      <span className="text-muted-foreground shrink-0">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </li>
  );
}

function EmptyCriteria() {
  return <li className="text-muted-foreground text-xs">None configured</li>;
}

function sizeRows(campaign: Campaign) {
  const rows = [];
  if (campaign.company_size?.min != null) {
    rows.push(
      <CriteriaRow
        key="size-min"
        label="Company size"
        value={`≥ ${campaign.company_size.min} employees`}
      />,
    );
  }
  if (campaign.company_size?.max != null) {
    rows.push(
      <CriteriaRow
        key="size-max"
        label="Company size"
        value={`≤ ${campaign.company_size.max} employees`}
      />,
    );
  }
  return rows;
}

function formatRunDuration(
  startedAt: string | null,
  completedAt: string | null,
  status: string,
): string {
  if (!completedAt) {
    return isTerminalRunStatus(status) ? "Unavailable" : "In progress";
  }
  if (!startedAt) return "Unavailable";

  const durationMs = Date.parse(completedAt) - Date.parse(startedAt);
  if (!Number.isFinite(durationMs) || durationMs < 0) return "Unavailable";

  const totalSeconds = Math.round(durationMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}
