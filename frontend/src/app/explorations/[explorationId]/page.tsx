import { ExplorationDetailsPage } from "@/features/exploration/components/exploration-details-page";

export default async function ExplorationDetailsRoute({
  params,
}: {
  params: Promise<{ explorationId: string }>;
}) {
  const { explorationId } = await params;
  return <ExplorationDetailsPage explorationId={explorationId} />;
}
