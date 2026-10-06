"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Plus, RefreshCw } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { listCampaigns } from "@/lib/api/campaigns";
import { campaignsQueryKey } from "@/lib/queries/query-keys";
import { cn } from "@/lib/utils";
import { formatDate } from "@/components/research/research-runs-page";

export function CampaignsPage() {
  const query = useQuery({
    queryKey: campaignsQueryKey,
    queryFn: listCampaigns,
  });

  return (
    <section aria-labelledby="page-title" className="mx-auto max-w-6xl">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
            Workspace
          </p>
          <h1 id="page-title" className="text-2xl font-semibold tracking-tight">
            Campaigns
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Configure reusable research criteria and start independent runs.
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
      ) : query.data.length === 0 ? (
        <div className="rounded-lg border border-dashed p-10 text-center">
          <h2 className="text-sm font-semibold">No campaigns yet</h2>
          <p className="text-muted-foreground mt-1 text-sm">
            Create a campaign to define the criteria for company research.
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
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead className="bg-muted/50 text-muted-foreground border-b text-xs">
                <tr>
                  <th className="px-4 py-3 font-medium">Campaign</th>
                  <th className="px-4 py-3 font-medium">Target</th>
                  <th className="px-4 py-3 font-medium">Market</th>
                  <th className="px-4 py-3 font-medium">Industry</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Created</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y">
                {[...query.data]
                  .sort((a, b) => b.created_at.localeCompare(a.created_at))
                  .map((campaign) => (
                    <tr className="hover:bg-muted/20" key={campaign.id}>
                      <td className="px-4 py-3">
                        <Link
                          className="font-medium hover:underline"
                          href={`/campaigns/${campaign.id}`}
                        >
                          {campaign.name}
                        </Link>
                        <p className="text-muted-foreground mt-0.5 font-mono text-[11px]">
                          {campaign.id}
                        </p>
                      </td>
                      <td className="px-4 py-3 tabular-nums">
                        {campaign.target_count}
                      </td>
                      <td className="px-4 py-3">
                        {campaign.target_market || "—"}
                      </td>
                      <td className="px-4 py-3">{campaign.industry || "—"}</td>
                      <td className="px-4 py-3">
                        <CampaignStatusBadge status={campaign.status} />
                      </td>
                      <td className="text-muted-foreground px-4 py-3 whitespace-nowrap">
                        {formatDate(campaign.created_at)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Link
                          aria-label={`Open ${campaign.name}`}
                          className={cn(
                            buttonVariants({ size: "sm", variant: "ghost" }),
                          )}
                          href={`/campaigns/${campaign.id}`}
                        >
                          Open{" "}
                          <ArrowRight
                            aria-hidden="true"
                            data-icon="inline-end"
                          />
                        </Link>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

export function CampaignStatusBadge({ status }: { status: string }) {
  const style =
    status === "COMPLETED"
      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
      : status === "FAILED"
        ? "bg-destructive/10 text-destructive"
        : status === "RUNNING"
          ? "bg-amber-500/10 text-amber-700 dark:text-amber-300"
          : "";
  return (
    <Badge className={style} variant="secondary">
      {status}
    </Badge>
  );
}
