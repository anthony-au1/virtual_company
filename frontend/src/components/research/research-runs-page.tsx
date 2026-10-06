"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, RefreshCw, Search } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { listResearchRuns } from "@/lib/api/research";
import { researchRunsQueryKey } from "@/lib/queries/query-keys";

export function ResearchRunsPage() {
  const query = useQuery({
    queryKey: researchRunsQueryKey,
    queryFn: listResearchRuns,
  });

  return (
    <section aria-labelledby="page-title" className="mx-auto max-w-6xl">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
            Research
          </p>
          <h1 id="page-title" className="text-2xl font-semibold tracking-tight">
            Research Runs
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Review persisted company research and qualification results.
          </p>
        </div>
        {query.data && query.data.length > 0 ? (
          <Badge variant="secondary">{query.data.length} runs</Badge>
        ) : null}
      </div>

      {query.isPending ? (
        <div
          role="status"
          className="text-muted-foreground rounded-lg border p-8 text-center text-sm"
        >
          Loading research runs…
        </div>
      ) : query.isError ? (
        <div
          role="alert"
          className="border-destructive/30 rounded-lg border p-6"
        >
          <h2 className="text-sm font-semibold">
            Research runs could not be loaded
          </h2>
          <p className="text-muted-foreground mt-1 text-sm">
            {query.error.message || "Check the connection and try again."}
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
          <Search
            aria-hidden="true"
            className="text-muted-foreground mx-auto size-5"
          />
          <h2 className="mt-3 text-sm font-semibold">No research runs yet</h2>
          <p className="text-muted-foreground mt-1 text-sm">
            Completed and in-progress research runs will appear here.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="bg-muted/50 text-muted-foreground border-b text-xs">
                <tr>
                  <th className="px-4 py-3 font-medium">Campaign</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Results</th>
                  <th className="px-4 py-3 font-medium">Review</th>
                  <th className="px-4 py-3 font-medium">Started</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y">
                {query.data.map((run) => (
                  <tr className="hover:bg-muted/20" key={run.run_id}>
                    <td className="px-4 py-3">
                      <Link
                        className="font-medium hover:underline"
                        href={`/research/${run.run_id}`}
                      >
                        {run.campaign.name}
                      </Link>
                      <p className="text-muted-foreground mt-0.5 font-mono text-[11px]">
                        {run.run_id}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <RunStatus status={run.status} />
                    </td>
                    <td className="px-4 py-3 tabular-nums">
                      {run.summary.researched > 0
                        ? `${run.summary.qualified} qualified · ${run.summary.researched} researched`
                        : run.status === "RUNNING"
                          ? "Researching…"
                          : "—"}
                      <span className="text-muted-foreground mt-0.5 block text-xs">
                        Target {run.campaign.target_count}
                      </span>
                    </td>
                    <td className="px-4 py-3 tabular-nums">
                      {run.summary.accepted} accepted
                      <span className="text-muted-foreground mt-0.5 block text-xs">
                        {run.summary.rejected} rejected ·{" "}
                        {run.summary.unreviewed} unreviewed
                      </span>
                    </td>
                    <td className="text-muted-foreground px-4 py-3 whitespace-nowrap">
                      {formatDate(run.started_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        aria-label={`Open ${run.campaign.name}`}
                        className={cn(
                          buttonVariants({ size: "sm", variant: "ghost" }),
                        )}
                        href={`/research/${run.run_id}`}
                      >
                        Open{" "}
                        <ArrowRight aria-hidden="true" data-icon="inline-end" />
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

export function RunStatus({ status }: { status: string }) {
  const tone =
    status === "COMPLETED"
      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
      : status === "FAILED"
        ? "bg-destructive/10 text-destructive"
        : "bg-amber-500/10 text-amber-700 dark:text-amber-300";
  return (
    <Badge className={tone} variant="secondary">
      {status.replaceAll("_", " ")}
    </Badge>
  );
}

export function formatDate(value: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
