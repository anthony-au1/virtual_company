import { apiFetch } from "@/lib/api/client";

export type Exploration = {
  id: string;
  business_context: string;
  max_obligations: number;
  status: string;
  created_at: string;
  updated_at: string;
};

export type ExplorationObligation = {
  description: string;
  created_at: string;
};

export type ExplorationRunSummary = {
  id: string;
  research_run_id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  campaign_name: string;
  selected_company_count: number;
};

export type StartExplorationRunPayload = {
  research_run_id: string;
  company_ids: string[];
};

export type StartedExplorationRun = {
  id: string;
  exploration_id: string;
  research_run_id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  company_ids: string[];
};

export type CreateExplorationPayload = {
  business_context: string;
  max_obligations: number;
};

export type UpdateExplorationPayload = Partial<CreateExplorationPayload>;

export function listExplorations(): Promise<Exploration[]> {
  return apiFetch<Exploration[]>("/api/v1/explorations");
}

export function getExploration(explorationId: string): Promise<Exploration> {
  return apiFetch<Exploration>(
    `/api/v1/explorations/${encodeURIComponent(explorationId)}`,
  );
}

export function createExploration(
  payload: CreateExplorationPayload,
): Promise<Exploration> {
  return apiFetch<Exploration>("/api/v1/explorations", {
    method: "POST",
    body: payload,
  });
}

export function updateExploration(
  explorationId: string,
  payload: UpdateExplorationPayload,
): Promise<Exploration> {
  return apiFetch<Exploration>(
    `/api/v1/explorations/${encodeURIComponent(explorationId)}`,
    { method: "PATCH", body: payload },
  );
}

export function deleteExploration(explorationId: string): Promise<void> {
  return apiFetch<void>(
    `/api/v1/explorations/${encodeURIComponent(explorationId)}`,
    { method: "DELETE" },
  );
}

export function listExplorationObligations(
  explorationId: string,
): Promise<ExplorationObligation[]> {
  return apiFetch<ExplorationObligation[]>(
    `/api/v1/explorations/${encodeURIComponent(explorationId)}/obligations`,
  );
}

export function listExplorationRuns(
  explorationId: string,
): Promise<ExplorationRunSummary[]> {
  return apiFetch<ExplorationRunSummary[]>(
    `/api/v1/explorations/${encodeURIComponent(explorationId)}/runs`,
  );
}

export function startExplorationRun(
  explorationId: string,
  payload: StartExplorationRunPayload,
): Promise<StartedExplorationRun> {
  return apiFetch<StartedExplorationRun>(
    `/api/v1/explorations/${encodeURIComponent(explorationId)}/runs`,
    { method: "POST", body: payload },
  );
}
