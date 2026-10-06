import { CampaignDetailsPage } from "@/components/campaigns/campaign-details-page";

export default async function CampaignDetailsRoute({
  params,
}: {
  params: Promise<{ campaignId: string }>;
}) {
  const { campaignId } = await params;
  return <CampaignDetailsPage campaignId={campaignId} />;
}
