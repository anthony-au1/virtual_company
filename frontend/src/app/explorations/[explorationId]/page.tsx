import { ExplorationDetailsPage } from "@/components/explorations/exploration-details-page";

export default async function ExplorationDetailsRoute({
  params,
}: {
  params: Promise<{ explorationId: string }>;
}) {
  const { explorationId } = await params;
  return <ExplorationDetailsPage explorationId={explorationId} />;
}
