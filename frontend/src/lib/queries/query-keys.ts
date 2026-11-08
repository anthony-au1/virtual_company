export const campaignsQueryKey = ["campaigns"] as const;
export const campaignQueryKey = (campaignId: string) =>
  ["campaign", campaignId] as const;
export const researchRunsQueryKey = ["research-runs"] as const;
export const researchRunResultsQueryKey = (runId: string) =>
  ["research-run-results", runId] as const;
export const explorationsQueryKey = ["explorations"] as const;
export const explorationQueryKey = (explorationId: string) =>
  ["exploration", explorationId] as const;
export const explorationObligationsQueryKey = (explorationId: string) =>
  ["exploration-obligations", explorationId] as const;
export const explorationRunsQueryKey = (explorationId: string) =>
  ["exploration-runs", explorationId] as const;
export const explorationRunStatusQueryKey = (
  explorationId: string,
  runId: string,
) => ["exploration-run-status", explorationId, runId] as const;
export const explorationRunCompaniesQueryKey = (
  explorationId: string,
  runId: string,
) => ["exploration-run-companies", explorationId, runId] as const;
export const explorationCompanyEvidenceQueryKey = (
  explorationId: string,
  runId: string,
  companyLinkId?: string,
) =>
  [
    "exploration-company-evidence",
    explorationId,
    runId,
    ...(companyLinkId ? [companyLinkId] : []),
  ] as const;
export const explorationCompanyFactsQueryKey = (
  explorationId: string,
  runId: string,
  companyLinkId?: string,
) =>
  [
    "exploration-company-facts",
    explorationId,
    runId,
    ...(companyLinkId ? [companyLinkId] : []),
  ] as const;
export const explorationCompanyHypothesesQueryKey = (
  explorationId: string,
  runId: string,
  companyLinkId?: string,
) =>
  [
    "exploration-company-hypotheses",
    explorationId,
    runId,
    ...(companyLinkId ? [companyLinkId] : []),
  ] as const;
