import { ExplorationFormPage } from "@/components/explorations/exploration-form-page";

export default async function EditExplorationRoute({
  params,
}: {
  params: Promise<{ explorationId: string }>;
}) {
  const { explorationId } = await params;
  return <ExplorationFormPage explorationId={explorationId} />;
}
