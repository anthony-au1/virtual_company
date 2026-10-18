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

export function listExplorationObligations(
  explorationId: string,
): Promise<ExplorationObligation[]> {
  return apiFetch<ExplorationObligation[]>(
    `/api/v1/explorations/${encodeURIComponent(explorationId)}/obligations`,
  );
}
