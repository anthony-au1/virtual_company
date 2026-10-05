import { afterEach, describe, expect, it, vi } from "vitest";

import { updateCompanyReview } from "@/lib/api/research";

afterEach(() => vi.restoreAllMocks());

describe("research API", () => {
  it("sends a review update scoped by run ID and company ID", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ company_id: "company/1", review_status: "ACCEPTED" }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );

    await updateCompanyReview("run/2", "company/1", "ACCEPTED");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/backend/api/v1/research-runs/run%2F2/companies/company%2F1/review",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ status: "ACCEPTED" }),
      }),
    );
  });
});
