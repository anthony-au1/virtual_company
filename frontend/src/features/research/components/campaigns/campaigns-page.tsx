"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Plus, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { CampaignStatusBadge } from "@/features/research/components/campaigns/campaign-status-badge";
import { DeleteCampaignAction } from "@/features/research/components/campaigns/delete-campaign-action";
import { RunStatus } from "@/features/research/components/runs/run-status-badge";
import { ResearchSectionNav } from "@/features/research/components/research-section-nav";
import { listCampaigns } from "@/features/research/api/campaigns";
import {
  listResearchRuns,
  type ResearchRunListItem,
} from "@/features/research/api/research";
import {
  campaignsQueryKey,
  researchRunsQueryKey,
} from "@/features/research/query-keys";
import { isTerminalRunStatus } from "@/features/research/status";
import { formatDate } from "@/lib/format-date";
import { cn } from "@/lib/utils";

const CAMPAIGN_DELETE_DISABLED_REASON =
  "Campaigns with Research history cannot be deleted.";

export function CampaignsPage() {
  const query = useQuery({
    queryKey: campaignsQueryKey,
    queryFn: listCampaigns,
  });
  const runsQuery = useQuery({
    queryKey: researchRunsQueryKey,
    queryFn: listResearchRuns,
    refetchInterval: (current) =>
      current.state.data?.some((run) => !isTerminalRunStatus(run.status))
        ? 2000
        : false,
  });
  const runsByCampaign = useMemo(
    () => groupRunsByCampaign(runsQuery.data),
    [runsQuery.data],
  );

  return (
    <section aria-labelledby="page-title" className="mx-auto max-w-6xl">
      <ResearchSectionNav />
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
            Research
          </p>
          <h1 id="page-title" className="text-2xl font-semibold tracking-tight">
            Campaigns
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Configure research criteria and review each Campaign’s run history.
          </p>
        </div>
        <Link className={cn(buttonVariants())} href="/campaigns/new">
          <Plus aria-hidden="true" data-icon="inline-start" />
          Create Campaign
        </Link>
      </div>

      {query.isPending ? (
        <div
          role="status"
          className="text-muted-foreground rounded-lg border p-8 text-center text-sm"
        >
          Loading campaigns…
        </div>
      ) : query.isError ? (
        <div
          role="alert"
          className="border-destructive/30 rounded-lg border p-6"
        >
          <h2 className="text-sm font-semibold">
            Campaigns could not be loaded
          </h2>
          <p className="text-muted-foreground mt-1 text-sm">
            {query.error.message}
          </p>
          <Button
            className="mt-4"
            onClick={() => void query.refetch()}
            size="sm"
            variant="outline"
          >
            <RefreshCw aria-hidden="true" data-icon="inline-start" />
            Try again
          </Button>
        </div>
      ) : (
        <>
          {runsQuery.isPending ? (
            <p role="status" className="text-muted-foreground mb-3 text-xs">
              Loading Research Run activity…
            </p>
          ) : runsQuery.isError ? (
            <div
              role="alert"
              className="border-destructive/30 mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3"
            >
              <p className="text-sm">
                Run activity is unavailable. Campaigns are still available.
              </p>
              <Button
                onClick={() => void runsQuery.refetch()}
                size="sm"
                variant="outline"
              >
                <RefreshCw aria-hidden="true" data-icon="inline-start" />
                Retry activity
              </Button>
            </div>
          ) : null}

          {query.data.length === 0 ? (
            <div className="rounded-lg border border-dashed p-10 text-center">
              <h2 className="text-sm font-semibold">No campaigns yet</h2>
              <p className="text-muted-foreground mt-1 text-sm">
                Create a Campaign to define criteria for company research.
              </p>
              <Link
                className={cn(buttonVariants({ className: "mt-4" }))}
                href="/campaigns/new"
              >
                <Plus aria-hidden="true" data-icon="inline-start" />
                Create Campaign
              </Link>
            </div>
          ) : (
            <div className="overflow-hidden rounded-lg border">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[900px] text-left text-sm">
                  <thead className="bg-muted/50 text-muted-foreground border-b text-xs">
                    <tr>
                      <th className="px-4 py-3 font-medium" scope="col">
                        Campaign
                      </th>
                      <th className="px-4 py-3 font-medium" scope="col">
                        Market &amp; industry
                      </th>
                      <th className="px-4 py-3 font-medium" scope="col">
                        Research configuration
                      </th>
                      <th className="px-4 py-3 font-medium" scope="col">
                        Campaign status
                      </th>
                      <th className="px-4 py-3 font-medium" scope="col">
                        Latest Research Run
                      </th>
                      <th className="px-4 py-3" scope="col">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {[...query.data]
                      .sort((a, b) => b.created_at.localeCompare(a.created_at))
                      .map((campaign) => {
                        const campaignRuns = runsByCampaign.get(campaign.id);
                        const latestRun =
                          campaignRuns?.length && runsQuery.isSuccess
                            ? campaignRuns[0]
                            : undefined;
                        const runCount = runsQuery.isSuccess
                          ? (campaignRuns?.length ?? 0)
                          : undefined;
                        const campaignCannotBeDeleted =
                          campaign.sealed_at !== null || (runCount ?? 0) > 0;

                        return (
                          <tr className="hover:bg-muted/20" key={campaign.id}>
                            <td className="max-w-72 px-4 py-3">
                              <Link
                                className="font-medium hover:underline"
                                href={`/campaigns/${campaign.id}`}
                              >
                                {campaign.name}
                              </Link>
                              {campaign.description ? (
                                <p className="text-muted-foreground mt-1 line-clamp-2 text-xs">
                                  {campaign.description}
                                </p>
                              ) : null}
                            </td>
                            <td className="px-4 py-3">
                              <p className="max-w-52 truncate">
                                {campaign.target_market || "—"}
                              </p>
                              <p className="text-muted-foreground mt-1 max-w-52 truncate text-xs">
                                {campaign.industry || "No industry"}
                              </p>
                            </td>
                            <td className="px-4 py-3 tabular-nums">
                              <p>{campaign.target_count} qualified target</p>
                              <p className="text-muted-foreground mt-1 text-xs">
                                Up to {campaign.max_companies_to_research}{" "}
                                researched
                              </p>
                            </td>
                            <td className="px-4 py-3">
                              <div className="space-y-1">
                                <span className="text-muted-foreground block text-[10px] tracking-wide uppercase">
                                  Campaign
                                </span>
                                <CampaignStatusBadge status={campaign.status} />
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              {runsQuery.isPending ? (
                                <span className="text-muted-foreground text-xs">
                                  Loading activity…
                                </span>
                              ) : runsQuery.isError ? (
                                <span className="text-muted-foreground text-xs">
                                  Activity unavailable
                                </span>
                              ) : latestRun ? (
                                <div className="space-y-1">
                                  <div className="flex items-center gap-2">
                                    <RunStatus status={latestRun.status} />
                                    <span className="text-muted-foreground text-xs">
                                      {runCount}{" "}
                                      {runCount === 1 ? "run" : "runs"}
                                    </span>
                                  </div>
                                  <p className="text-muted-foreground text-xs whitespace-nowrap">
                                    {formatDate(
                                      latestRun.started_at ??
                                        latestRun.created_at,
                                    )}
                                  </p>
                                </div>
                              ) : (
                                <span className="text-muted-foreground text-xs">
                                  No runs yet
                                </span>
                              )}
                            </td>
                            <td className="px-4 py-3 text-right">
                              <div className="flex justify-end gap-2">
                                <Link
                                  aria-label={`Open ${campaign.name}`}
                                  className={cn(
                                    buttonVariants({
                                      size: "sm",
                                      variant: "ghost",
                                    }),
                                  )}
                                  href={`/campaigns/${campaign.id}`}
                                >
                                  Open{" "}
                                  <ArrowRight
                                    aria-hidden="true"
                                    data-icon="inline-end"
                                  />
                                </Link>
                                <DeleteCampaignAction
                                  campaignId={campaign.id}
                                  disabled={campaignCannotBeDeleted}
                                  disabledReason={
                                    campaignCannotBeDeleted
                                      ? CAMPAIGN_DELETE_DISABLED_REASON
                                      : undefined
                                  }
                                  navigateOnSuccess={false}
                                />
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function groupRunsByCampaign(
  runs: ResearchRunListItem[] | undefined,
): Map<string, ResearchRunListItem[]> {
  const grouped = new Map<string, ResearchRunListItem[]>();
  for (const run of runs ?? []) {
    const campaignRuns = grouped.get(run.campaign.id) ?? [];
    campaignRuns.push(run);
    grouped.set(run.campaign.id, campaignRuns);
  }
  for (const campaignRuns of grouped.values()) {
    campaignRuns.sort((a, b) =>
      (b.started_at ?? b.created_at).localeCompare(
        a.started_at ?? a.created_at,
      ),
    );
  }
  return grouped;
}
