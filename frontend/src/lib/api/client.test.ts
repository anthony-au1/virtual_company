import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch } from "@/lib/api/client";

afterEach(() => vi.restoreAllMocks());

describe("apiFetch", () => {
  it("serializes JSON and returns typed JSON", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ id: "campaign-1" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const result = await apiFetch<{ id: string }>("/api/v1/campaigns", {
      method: "POST",
      body: { name: "Example" },
    });

    expect(result.id).toBe("campaign-1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/backend/api/v1/campaigns",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ name: "Example" }),
      }),
    );
  });

  it("returns undefined for an empty successful response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );

    await expect(apiFetch<void>("/health")).resolves.toBeUndefined();
  });

  it("throws a structured error using backend detail", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Campaign not found" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    );

    await expect(apiFetch("/api/v1/campaigns/missing")).rejects.toMatchObject<
      Partial<ApiError>
    >({
      name: "ApiError",
      message: "Campaign not found",
      status: 404,
    });
  });
});
