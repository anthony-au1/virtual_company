"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Plus, RefreshCw } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { listExplorations } from "@/lib/api/explorations";
import { explorationsQueryKey } from "@/lib/queries/query-keys";
import { cn } from "@/lib/utils";

export function ExplorationsPage() {
  const query = useQuery({
    queryKey: explorationsQueryKey,
    queryFn: listExplorations,
  });

  return (
    <section aria-labelledby="page-title" className="mx-auto max-w-6xl">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
            Workspace
          </p>
          <h1 id="page-title" className="text-2xl font-semibold tracking-tight">
            Explorations
          </h1>
          <p className="text-muted-foreground mt-1 max-w-2xl text-sm">
            Investigate a business context through evidence-backed research
            obligations.
          </p>
        </div>
        <Link className={cn(buttonVariants())} href="/explorations/new">
          <Plus aria-hidden="true" data-icon="inline-start" />
          New Exploration
        </Link>
      </div>

      {query.isPending ? (
        <div
          role="status"
          className="text-muted-foreground rounded-lg border p-8 text-center text-sm"
        >
          Loading Explorations…
        </div>
      ) : query.isError ? (
        <div
          role="alert"
          className="border-destructive/30 rounded-lg border p-6"
        >
          <h2 className="text-sm font-semibold">
            Explorations could not be loaded
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
          <h2 className="text-sm font-semibold">No Explorations yet</h2>
          <p className="text-muted-foreground mt-1 text-sm">
            Create an Exploration to turn a business context into focused
            research obligations.
          </p>
          <Link
            className={cn(buttonVariants({ className: "mt-4" }))}
            href="/explorations/new"
          >
            <Plus aria-hidden="true" data-icon="inline-start" />
            New Exploration
          </Link>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="bg-muted/50 text-muted-foreground border-b text-xs">
                <tr>
                  <th className="px-4 py-3 font-medium">Business context</th>
                  <th className="px-4 py-3 font-medium">Maximum obligations</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Updated</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y">
                {[...query.data]
                  .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
                  .map((item) => (
                    <tr className="hover:bg-muted/20" key={item.id}>
                      <td className="max-w-2xl px-4 py-3">
                        <Link
                          className="font-medium hover:underline"
                          href={`/explorations/${item.id}`}
                        >
                          {preview(item.business_context)}
                        </Link>
                      </td>
                      <td className="px-4 py-3 tabular-nums">
                        {item.max_obligations}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant="secondary">{item.status}</Badge>
                      </td>
                      <td className="text-muted-foreground px-4 py-3 whitespace-nowrap">
                        {formatDate(item.updated_at)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Link
                          aria-label={`Open Exploration ${preview(item.business_context)}`}
                          className={cn(
                            buttonVariants({ size: "sm", variant: "ghost" }),
                          )}
                          href={`/explorations/${item.id}`}
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

function preview(value: string): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length > 120 ? `${normalized.slice(0, 117)}…` : normalized;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
