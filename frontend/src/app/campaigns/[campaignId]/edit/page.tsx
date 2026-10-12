import { CampaignFormPage } from "@/components/campaigns/campaign-form-page";

export default async function CampaignEditRoute({
  params,
}: {
  params: Promise<{ campaignId: string }>;
}) {
  const { campaignId } = await params;
  return <CampaignFormPage campaignId={campaignId} />;
}
