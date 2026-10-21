"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Plus, Pencil, RefreshCw } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { DeleteExplorationAction } from "@/components/explorations/delete-exploration-action";
import {
  getExploration,
  listExplorationObligations,
  listExplorationRuns,
} from "@/lib/api/explorations";
import {
  explorationObligationsQueryKey,
  explorationQueryKey,
  explorationRunsQueryKey,
} from "@/lib/queries/query-keys";
import { cn } from "@/lib/utils";

export function ExplorationDetailsPage({
  explorationId,
}: {
  explorationId: string;
}) {
  const explorationQuery = useQuery({
    queryKey: explorationQueryKey(explorationId),
    queryFn: () => getExploration(explorationId),
  });
  const obligationsQuery = useQuery({
    queryKey: explorationObligationsQueryKey(explorationId),
    queryFn: () => listExplorationObligations(explorationId),
  });
  const runsQuery = useQuery({
    queryKey: explorationRunsQueryKey(explorationId),
    queryFn: () => listExplorationRuns(explorationId),
  });

  if (explorationQuery.isPending) {
    return (
      <p role="status" className="mx-auto max-w-5xl p-8 text-center text-sm">
        Loading Exploration…
      </p>
    );
  }
  if (explorationQuery.isError) {
    const notFound =
      "status" in explorationQuery.error &&
      explorationQuery.error.status === 404;
    return (
      <section className="mx-auto max-w-5xl">
        <BackToExplorations />
        <div
          role="alert"
          className="border-destructive/30 mt-5 rounded-lg border p-6"
        >
          <h1 className="text-lg font-semibold">
            {notFound
              ? "Exploration not found"
              : "Exploration could not be loaded"}
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            {explorationQuery.error.message}
          </p>
          {!notFound ? (
            <Button
              className="mt-4"
              onClick={() => void explorationQuery.refetch()}
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

  const exploration = explorationQuery.data;
  const editLocked =
    runsQuery.isPending ||
    runsQuery.isError ||
    Boolean(runsQuery.data && runsQuery.data.length > 0);

  return (
    <section aria-labelledby="page-title" className="mx-auto max-w-5xl">
      <BackToExplorations />
      <header className="mt-4 flex flex-wrap items-start justify-between gap-4 border-b pb-5">
        <div className="min-w-0">
          <p className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
            Exploration
          </p>
          <h1 id="page-title" className="text-2xl font-semibold tracking-tight">
            {contextHeading(exploration.business_context)}
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Updated {formatDate(exploration.updated_at)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{exploration.status}</Badge>
          <DeleteExplorationAction explorationId={explorationId} />
          {editLocked ? (
            <Button
              disabled
              title={
                runsQuery.data && runsQuery.data.length > 0
                  ? "Business Context and obligation settings are locked after the first run."
                  : "Run status is being checked before editing."
              }
              variant="outline"
            >
              <Pencil aria-hidden="true" data-icon="inline-start" />
              Edit Exploration
            </Button>
          ) : (
            <Link
              className={cn(buttonVariants({ variant: "outline" }))}
              href={`/explorations/${explorationId}/edit`}
            >
              <Pencil aria-hidden="true" data-icon="inline-start" />
              Edit Exploration
            </Link>
          )}
        </div>
      </header>

      <section
        aria-labelledby="runs-title"
        className="mt-6 rounded-lg border p-4 sm:p-5"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 id="runs-title" className="text-sm font-semibold">
              Exploration Runs
            </h2>
            <p className="text-muted-foreground mt-1 text-xs leading-5">
              Each run saves a company selection from one Research Run.
            </p>
          </div>
          <Link
            className={cn(buttonVariants({ size: "sm" }))}
            href={`/explorations/${explorationId}/runs/new`}
          >
            <Plus aria-hidden="true" data-icon="inline-start" />
            New Exploration Run
          </Link>
        </div>

        {runsQuery.isPending ? (
          <p className="text-muted-foreground mt-4 text-sm" role="status">
            Loading Exploration Runs…
          </p>
        ) : runsQuery.isError ? (
          <div className="mt-4" role="alert">
            <p className="text-destructive text-sm">
              Exploration Runs could not be loaded.
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
        ) : runsQuery.data.length === 0 ? (
          <p className="text-muted-foreground mt-4 rounded-md border border-dashed p-4 text-sm">
            No Exploration Runs yet. Start one to save a company selection from
            Research.
          </p>
        ) : (
          <ul className="mt-4 space-y-2">
            {runsQuery.data.map((run, index) => (
              <li
                className="bg-muted/40 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-md px-3 py-3"
                key={run.id}
              >
                <div className="min-w-0">
                  <p className="font-medium">Run {index + 1}</p>
                  <p className="text-muted-foreground mt-0.5 text-sm">
                    Research Run from {run.campaign_name}
                  </p>
                  <p className="text-muted-foreground mt-1 font-mono text-xs">
                    Research Run {run.research_run_id}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <Badge variant="secondary">{run.status}</Badge>
                  <span className="text-muted-foreground text-sm">
                    {run.selected_company_count} selected{" "}
                    {run.selected_company_count === 1 ? "company" : "companies"}
                  </span>
                  <span className="text-muted-foreground text-xs">
                    Started {formatDate(run.started_at)}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(18rem,0.85fr)]">
        <section className="h-fit rounded-lg border p-4 sm:p-5">
          <h2 className="text-sm font-semibold">Business context</h2>
          <p className="text-muted-foreground mt-3 text-sm leading-6 whitespace-pre-wrap">
            {exploration.business_context}
          </p>
          <dl className="mt-5 border-t pt-4">
            <div className="flex items-center justify-between gap-4 text-sm">
              <dt className="text-muted-foreground">Maximum obligations</dt>
              <dd className="font-medium tabular-nums">
                {exploration.max_obligations}
              </dd>
            </div>
            <p className="text-muted-foreground mt-1 text-xs">
              Upper bound; fewer shared company-investigation obligations may be
              generated.
            </p>
          </dl>
        </section>

        <section
          aria-labelledby="obligations-title"
          className="rounded-lg border p-4 sm:p-5"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 id="obligations-title" className="text-sm font-semibold">
                Research obligations
              </h2>
              <p className="text-muted-foreground mt-1 text-xs leading-5">
                Generated from the Business Context as shared questions or
                conditions to establish for companies selected from Research.
              </p>
            </div>
            {obligationsQuery.data ? (
              <Badge variant="secondary">
                {obligationsQuery.data.length} generated
              </Badge>
            ) : null}
          </div>

          {obligationsQuery.isPending ? (
            <p role="status" className="text-muted-foreground mt-4 text-sm">
              Loading research obligations…
            </p>
          ) : obligationsQuery.isError ? (
            <div role="alert" className="mt-4">
              <p className="text-destructive text-sm">
                Research obligations could not be loaded.
              </p>
              <Button
                className="mt-2"
                onClick={() => void obligationsQuery.refetch()}
                size="sm"
                variant="outline"
              >
                Try again
              </Button>
            </div>
          ) : obligationsQuery.data.length === 0 ? (
            <p className="text-muted-foreground mt-4 rounded-md border border-dashed p-4 text-sm leading-6">
              No company-investigation obligations were generated from the
              current Business Context. This is valid when investigating
              selected companies cannot meaningfully support the goal. You can
              refine it and update this Exploration before a future run.
            </p>
          ) : (
            <ol className="mt-4 divide-y">
              {obligationsQuery.data.map((obligation, index) => (
                <li
                  className="flex gap-3 py-3 first:pt-0 last:pb-0"
                  key={`${index}-${obligation.description}`}
                >
                  <span
                    aria-hidden="true"
                    className="bg-muted text-muted-foreground flex size-6 shrink-0 items-center justify-center rounded-full text-xs tabular-nums"
                  >
                    {index + 1}
                  </span>
                  <p className="text-sm leading-6">{obligation.description}</p>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </section>
  );
}

function BackToExplorations() {
  return (
    <Link
      className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-sm"
      href="/explorations"
    >
      <ArrowLeft aria-hidden="true" className="size-4" />
      Explorations
    </Link>
  );
}

function contextHeading(value: string): string {
  const line = value.replace(/\s+/g, " ").trim();
  return line.length > 90 ? `${line.slice(0, 87)}…` : line;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
