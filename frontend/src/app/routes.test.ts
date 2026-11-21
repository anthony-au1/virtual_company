import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockRedirect } = vi.hoisted(() => ({ mockRedirect: vi.fn() }));

vi.mock("next/navigation", () => ({ redirect: mockRedirect }));

import Home from "@/app/page";
import CampaignsRoute from "@/app/campaigns/page";

describe("legacy and root route redirects", () => {
  beforeEach(() => mockRedirect.mockClear());

  it("redirects the root route to the Research landing page", () => {
    Home();
    expect(mockRedirect).toHaveBeenCalledWith("/research");
  });

  it("redirects the legacy Campaign list route to the Research landing page", () => {
    CampaignsRoute();
    expect(mockRedirect).toHaveBeenCalledWith("/research");
  });
});
