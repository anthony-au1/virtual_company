import { NewExplorationRunPage } from "@/features/exploration/components/new-exploration-run-page";

export default async function NewExplorationRunRoute({
  params,
}: {
  params: Promise<{ explorationId: string }>;
}) {
  const { explorationId } = await params;
  return <NewExplorationRunPage explorationId={explorationId} />;
}
