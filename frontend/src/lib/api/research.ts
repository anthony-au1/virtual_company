import { apiFetch } from "@/lib/api/client";

export type QualificationStatus =
  "QUALIFIED" | "NOT_QUALIFIED" | "INSUFFICIENT_EVIDENCE";
export type ReviewStatus = "UNREVIEWED" | "ACCEPTED" | "REJECTED";
export type CriterionStatus = "MATCH" | "MISMATCH" | "UNKNOWN";
export type CriterionRequirement = "required" | "preferred";

export type ResearchRunListItem = {
  run_id: string;
  status: string;
  created_at: string;
  started_at: string;
  completed_at: string | null;
  campaign: { id: string; name: string; target_count: number };
  summary: {
    researched: number;
    qualified: number;
    not_qualified: number;
    insufficient_evidence: number;
    accepted: number;
    rejected: number;
    unreviewed: number;
  };
};

export type CampaignCriterion = {
  value: string | null;
  requirement: CriterionRequirement;
};

export type ResearchResults = {
  research_run: {
    id: string;
    campaign_id: string;
    status: string;
    started_at: string;
    completed_at: string | null;
    error: string | null;
    companies_found: number;
    created_at: string;
  };
  campaign: {
    id: string;
    name: string;
    description: string | null;
    target_count: number;
    criteria: {
      target_market: CampaignCriterion;
      industry: CampaignCriterion;
      technologies: { required: string[]; preferred: string[] };
      company_size: {
        min: { value: number; requirement: CriterionRequirement } | null;
        max: { value: number; requirement: CriterionRequirement } | null;
      } | null;
    };
  };
  summary: {
    researched: number;
    qualified: number;
    not_qualified: number;
    insufficient_evidence: number;
  };
  companies: ResearchCompany[];
};

export type ResearchCompany = {
  company_id: string;
  name: string;
  website: string | null;
  qualification_status: QualificationStatus;
  review_status: ReviewStatus;
  summary: {
    required: { matched: number; mismatched: number; unknown: number };
    preferred: { matched: number; mismatched: number; unknown: number };
  };
  criteria: CriterionResult[];
};

export type CriterionResult = {
  criterion: string;
  subject: string | null;
  requirement: CriterionRequirement;
  status: CriterionStatus;
  reason: string;
  evidence: Array<{
    id: string;
    claim: string;
    evidence_text: string;
    source_url: string;
    source_title: string | null;
    source_type: string | null;
  }>;
};

export function listResearchRuns(): Promise<ResearchRunListItem[]> {
  return apiFetch("/api/v1/research-runs");
}

export function getResearchRunResults(runId: string): Promise<ResearchResults> {
  return apiFetch(`/api/v1/research-runs/${encodeURIComponent(runId)}/results`);
}

export function updateCompanyReview(
  runId: string,
  companyId: string,
  status: ReviewStatus,
): Promise<{ company_id: string; review_status: ReviewStatus }> {
  return apiFetch(
    `/api/v1/research-runs/${encodeURIComponent(runId)}/companies/${encodeURIComponent(companyId)}/review`,
    { method: "PATCH", body: { status } },
  );
}
