import { apiFetch } from "@/lib/api/client";

export type CampaignStatus =
  "DRAFT" | "RUNNING" | "PAUSED" | "COMPLETED" | "FAILED";
export type Campaign = {
  id: string;
  name: string;
  description: string | null;
  target_market: string | null;
  industry: string | null;
  technologies: string[];
  company_size: {
    min: number | null;
    max: number | null;
  } | null;
  target_count: number;
  max_companies_to_research: number;
  status: CampaignStatus;
  created_at: string;
  updated_at: string;
};

export type CreateCampaignPayload = {
  name: string;
  description: string;
  target_market?: string;
  industry?: string;
  technologies: string[];
  company_size: {
    min?: number;
    max?: number;
  } | null;
  target_count: number;
  max_companies_to_research: number;
  status: "DRAFT";
};

export function listCampaigns(): Promise<Campaign[]> {
  return apiFetch<Campaign[]>("/api/v1/campaigns");
}

export function getCampaign(campaignId: string): Promise<Campaign> {
  return apiFetch<Campaign>(
    `/api/v1/campaigns/${encodeURIComponent(campaignId)}`,
  );
}

export function createCampaign(
  payload: CreateCampaignPayload,
): Promise<Campaign> {
  return apiFetch<Campaign>("/api/v1/campaigns", {
    method: "POST",
    body: payload,
  });
}
