import { ExplorationRunDetailsPage } from "@/features/exploration/components/exploration-run-details-page";

export default async function ExplorationRunRoute({
  params,
  searchParams,
}: {
  params: Promise<{ explorationId: string; runId: string }>;
  searchParams: Promise<{ execution?: string }>;
}) {
  const { explorationId, runId } = await params;
  const { execution } = await searchParams;
  return (
    <ExplorationRunDetailsPage
      executionUnconfirmed={execution === "unconfirmed"}
      explorationId={explorationId}
      runId={runId}
    />
  );
}
