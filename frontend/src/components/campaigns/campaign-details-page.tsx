"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { CampaignStatusBadge } from "@/components/campaigns/campaigns-page";
import {
  RunStatus,
  formatDate,
} from "@/components/research/research-runs-page";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { getCampaign, type Campaign } from "@/lib/api/campaigns";
import { apiErrorMessages } from "@/lib/api/client";
import { listResearchRuns, startResearch } from "@/lib/api/research";
import {
  campaignQueryKey,
  researchRunsQueryKey,
} from "@/lib/queries/query-keys";
import { cn } from "@/lib/utils";

export function CampaignDetailsPage({ campaignId }: { campaignId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const campaignQuery = useQuery({
    queryKey: campaignQueryKey(campaignId),
    queryFn: () => getCampaign(campaignId),
  });
  const runsQuery = useQuery({
    queryKey: researchRunsQueryKey,
    queryFn: listResearchRuns,
  });
  const startMutation = useMutation({
    mutationKey: ["start-research", campaignId],
    mutationFn: () => startResearch(campaignId),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: researchRunsQueryKey });
      router.push(`/research/${result.research_run_id}`);
    },
  });

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
  const campaignRuns = (runsQuery.data ?? []).filter(
    (run) => run.campaign.id === campaignId,
  );

  return (
    <section aria-labelledby="page-title" className="mx-auto max-w-5xl">
      <BackToCampaigns />
      <header className="mt-4 flex flex-wrap items-start justify-between gap-4 border-b pb-5">
        <div>
          <p className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
            Campaign
          </p>
          <h1 id="page-title" className="text-2xl font-semibold tracking-tight">
            {campaign.name}
          </h1>
          <p className="text-muted-foreground mt-1 font-mono text-xs">
            {campaign.id}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <CampaignStatusBadge status={campaign.status} />
          <Button
            disabled={startMutation.isPending}
            onClick={() => startMutation.mutate()}
          >
            {startMutation.isPending ? "Starting research…" : "Start Research"}
            {!startMutation.isPending ? (
              <ArrowRight aria-hidden="true" data-icon="inline-end" />
            ) : null}
          </Button>
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

      <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(17rem,0.8fr)]">
        <div className="space-y-5">
          <section className="rounded-lg border p-4 sm:p-5">
            <h2 className="text-sm font-semibold">Basic information</h2>
            <dl className="mt-3 grid gap-4 sm:grid-cols-2">
              <Detail
                label="Target companies"
                value={`${campaign.target_count} qualified companies`}
              />
              <Detail label="Created" value={formatDate(campaign.created_at)} />
              <Detail
                label="Description"
                value={campaign.description || "—"}
                wide
              />
            </dl>
          </section>

          <section className="rounded-lg border p-4 sm:p-5">
            <h2 className="text-sm font-semibold">Campaign criteria</h2>
            <div className="mt-4 grid gap-5 sm:grid-cols-2">
              <CriteriaList title="Required criteria">
                {campaign.target_market ? (
                  <CriteriaRow label="Market" value={campaign.target_market} />
                ) : null}
                {campaign.industry ? (
                  <CriteriaRow label="Industry" value={campaign.industry} />
                ) : null}
                {campaign.technologies.required.map((technology) => (
                  <CriteriaRow
                    key={`required-${technology}`}
                    label="Technology"
                    value={technology}
                  />
                ))}
                {sizeRows(campaign, "required")}
                {!hasRequiredCriteria(campaign) ? <EmptyCriteria /> : null}
              </CriteriaList>
              <CriteriaList title="Preferred criteria">
                {campaign.technologies.preferred.map((technology) => (
                  <CriteriaRow
                    key={`preferred-${technology}`}
                    label="Technology"
                    value={technology}
                  />
                ))}
                {sizeRows(campaign, "preferred")}
                {!hasPreferredCriteria(campaign) ? <EmptyCriteria /> : null}
              </CriteriaList>
            </div>
          </section>
        </div>

        <section
          aria-labelledby="history-title"
          className="h-fit rounded-lg border p-4 sm:p-5"
        >
          <div className="flex items-start justify-between gap-2">
            <div>
              <h2 id="history-title" className="text-sm font-semibold">
                Research history
              </h2>
              <p className="text-muted-foreground mt-1 text-xs">
                Each start creates a separate run.
              </p>
            </div>
            {campaignRuns.length ? (
              <Badge variant="secondary">{campaignRuns.length} runs</Badge>
            ) : null}
          </div>
          {runsQuery.isPending ? (
            <p role="status" className="text-muted-foreground mt-4 text-sm">
              Loading history…
            </p>
          ) : runsQuery.isError ? (
            <div role="alert" className="mt-4">
              <p className="text-destructive text-sm">
                Research history could not be loaded.
              </p>
              <Button
                className="mt-2"
                onClick={() => void runsQuery.refetch()}
                size="sm"
                variant="outline"
              >
                Try again
              </Button>
            </div>
          ) : campaignRuns.length === 0 ? (
            <p className="text-muted-foreground mt-4 text-sm">
              No runs yet. Start research to create the first run.
            </p>
          ) : (
            <ul className="mt-4 divide-y">
              {[...campaignRuns]
                .sort((a, b) => b.created_at.localeCompare(a.created_at))
                .map((run) => (
                  <li
                    className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
                    key={run.run_id}
                  >
                    <div className="min-w-0">
                      <p className="truncate font-mono text-xs">{run.run_id}</p>
                      <p className="text-muted-foreground mt-1 text-xs">
                        {formatDate(run.created_at)}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <RunStatus status={run.status} />
                      <Link
                        aria-label={`Open research run ${run.run_id}`}
                        className={cn(
                          buttonVariants({ size: "icon-sm", variant: "ghost" }),
                        )}
                        href={`/research/${run.run_id}`}
                      >
                        <ArrowRight aria-hidden="true" />
                      </Link>
                    </div>
                  </li>
                ))}
            </ul>
          )}
          <Link
            className="text-primary mt-4 inline-flex text-xs underline-offset-2 hover:underline"
            href="/research"
          >
            View all Research Runs
          </Link>
        </section>
      </div>
    </section>
  );
}

function BackToCampaigns() {
  return (
    <Link
      className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-sm"
      href="/campaigns"
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

function sizeRows(campaign: Campaign, requirement: "required" | "preferred") {
  const rows = [];
  if (campaign.company_size?.min?.requirement === requirement) {
    rows.push(
      <CriteriaRow
        key="size-min"
        label="Company size"
        value={`≥ ${campaign.company_size.min.value} employees`}
      />,
    );
  }
  if (campaign.company_size?.max?.requirement === requirement) {
    rows.push(
      <CriteriaRow
        key="size-max"
        label="Company size"
        value={`≤ ${campaign.company_size.max.value} employees`}
      />,
    );
  }
  return rows;
}

function hasRequiredCriteria(campaign: Campaign) {
  return Boolean(
    campaign.target_market ||
    campaign.industry ||
    campaign.technologies.required.length ||
    campaign.company_size?.min?.requirement === "required" ||
    campaign.company_size?.max?.requirement === "required",
  );
}

function hasPreferredCriteria(campaign: Campaign) {
  return Boolean(
    campaign.technologies.preferred.length ||
    campaign.company_size?.min?.requirement === "preferred" ||
    campaign.company_size?.max?.requirement === "preferred",
  );
}
