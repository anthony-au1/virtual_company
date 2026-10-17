import { apiFetch } from "@/lib/api/client";

export type QualificationStatus =
  "QUALIFIED" | "NOT_QUALIFIED" | "INSUFFICIENT_EVIDENCE";
export type CriterionStatus = "MATCH" | "MISMATCH" | "UNKNOWN";

export type ResearchRunListItem = {
  run_id: string;
  status: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  campaign: {
    id: string;
    name: string;
    target_count: number;
    max_companies_to_research: number;
  };
  summary: {
    researched: number;
    qualified: number;
    not_qualified: number;
    insufficient_evidence: number;
  };
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
    max_companies_to_research: number;
    criteria: {
      target_market: string | null;
      industry: string | null;
      keywords: string[];
      company_size: {
        min: number | null;
        max: number | null;
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
  summary: {
    matched: number;
    mismatched: number;
    unknown: number;
  };
  criteria: CriterionResult[];
};

export type ResearchEvidence = {
  id: string;
  claim: string;
  evidence_text: string;
  source_url: string;
  source_title: string | null;
  source_type: string | null;
};

export type CriterionResult = {
  criterion: string;
  subject: string | null;
  status: CriterionStatus;
  reason: string;
  evidence: ResearchEvidence[];
};

export function listResearchRuns(): Promise<ResearchRunListItem[]> {
  return apiFetch("/api/v1/research-runs");
}

export function getResearchRunResults(runId: string): Promise<ResearchResults> {
  return apiFetch(`/api/v1/research-runs/${encodeURIComponent(runId)}/results`);
}

export function deleteResearchRun(runId: string): Promise<void> {
  return apiFetch(`/api/v1/research-runs/${encodeURIComponent(runId)}`, {
    method: "DELETE",
  });
}

export function startResearch(campaignId: string): Promise<{
  research_run_id: string;
  status: string;
  companies_found: number;
}> {
  return apiFetch(
    `/api/v1/campaigns/${encodeURIComponent(campaignId)}/research`,
    { method: "POST" },
  );
}
