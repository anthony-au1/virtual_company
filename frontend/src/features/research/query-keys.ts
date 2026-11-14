export const campaignsQueryKey = ["campaigns"] as const;
export const campaignQueryKey = (campaignId: string) =>
  ["campaign", campaignId] as const;
export const researchRunsQueryKey = ["research-runs"] as const;
export const researchRunResultsQueryKey = (runId: string) =>
  ["research-run-results", runId] as const;
