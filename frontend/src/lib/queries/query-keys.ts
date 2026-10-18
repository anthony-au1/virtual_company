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
