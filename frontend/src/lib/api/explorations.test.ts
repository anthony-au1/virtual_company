import { afterEach, describe, expect, it, vi } from "vitest";

import * as explorationApi from "@/lib/api/explorations";

afterEach(() => vi.restoreAllMocks());

describe("Exploration API", () => {
  it("lists Exploration runs and starts a run with only its ResearchRun and companies", async () => {
    const responsePayload = {
      id: "exploration-run-1",
      exploration_id: "exploration/1",
      research_run_id: "research-run-1",
      status: "RUNNING",
      started_at: "2026-10-15T10:00:00Z",
      completed_at: null,
      company_ids: ["company-1", "company-2"],
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async () =>
        new Response(JSON.stringify(responsePayload), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );

    await explorationApi.listExplorationRuns("exploration/1");
    await explorationApi.startExplorationRun("exploration/1", {
      research_run_id: "research-run-1",
      company_ids: ["company-1", "company-2"],
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/backend/api/v1/explorations/exploration%2F1/runs",
    );
    expect(fetchMock.mock.calls[1]).toEqual([
      "/api/backend/api/v1/explorations/exploration%2F1/runs",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          research_run_id: "research-run-1",
          company_ids: ["company-1", "company-2"],
        }),
      }),
    ]);
  });

  it("uses the existing list, create, read, update, and obligation endpoints", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async () =>
        new Response(JSON.stringify([]), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    await explorationApi.listExplorations();
    await explorationApi.createExploration({
      business_context: "context",
      max_obligations: 10,
    });
    await explorationApi.getExploration("id/1");
    await explorationApi.updateExploration("id/1", { max_obligations: 12 });
    await explorationApi.listExplorationObligations("id/1");
    const deleteResponse = new Response(null, { status: 204 });
    fetchMock.mockResolvedValueOnce(deleteResponse);
    await explorationApi.deleteExploration("id/1");

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/backend/api/v1/explorations",
      "/api/backend/api/v1/explorations",
      "/api/backend/api/v1/explorations/id%2F1",
      "/api/backend/api/v1/explorations/id%2F1",
      "/api/backend/api/v1/explorations/id%2F1/obligations",
      "/api/backend/api/v1/explorations/id%2F1",
    ]);
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          business_context: "context",
          max_obligations: 10,
        }),
      }),
    );
    expect(fetchMock.mock.calls[3]?.[1]).toEqual(
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ max_obligations: 12 }),
      }),
    );
    expect(fetchMock.mock.calls[5]?.[1]).toEqual(
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("does not define manual obligation mutation methods", () => {
    expect("createExplorationObligation" in explorationApi).toBe(false);
    expect("updateExplorationObligation" in explorationApi).toBe(false);
    expect("deleteExplorationObligation" in explorationApi).toBe(false);
    expect("deleteExplorationObligation" in explorationApi).toBe(false);
  });
});
