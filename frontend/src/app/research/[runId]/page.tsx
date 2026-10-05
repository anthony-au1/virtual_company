import { ResearchResultsPage } from "@/components/research/research-results-page";

export default async function ResearchRunPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  return <ResearchResultsPage runId={runId} />;
}
