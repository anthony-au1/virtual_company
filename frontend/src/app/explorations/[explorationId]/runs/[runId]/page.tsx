import { ExplorationRunDetailsPage } from "@/components/explorations/exploration-run-details-page";

export default async function ExplorationRunRoute({
  params,
}: {
  params: Promise<{ explorationId: string; runId: string }>;
}) {
  const { explorationId, runId } = await params;
  return (
    <ExplorationRunDetailsPage explorationId={explorationId} runId={runId} />
  );
}
