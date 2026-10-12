import { afterEach, describe, expect, it, vi } from "vitest";

import { deleteResearchRun } from "@/lib/api/research";

afterEach(() => vi.restoreAllMocks());

describe("research API", () => {
  it("deletes a run using its encoded run ID", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));
    await deleteResearchRun("run/2");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/backend/api/v1/research-runs/run%2F2",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});
