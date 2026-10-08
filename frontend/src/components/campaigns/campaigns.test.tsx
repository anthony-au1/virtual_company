import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CampaignDetailsPage } from "@/components/campaigns/campaign-details-page";
import { CampaignFormPage } from "@/components/campaigns/campaign-form-page";
import { CampaignsPage } from "@/components/campaigns/campaigns-page";
import type { Campaign } from "@/lib/api/campaigns";
import { ApiError } from "@/lib/api/client";
import type { ResearchRunListItem } from "@/lib/api/research";

const { mockPush } = vi.hoisted(() => ({ mockPush: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/campaigns",
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/lib/api/campaigns", () => ({
  listCampaigns: vi.fn(),
  getCampaign: vi.fn(),
  createCampaign: vi.fn(),
}));

vi.mock("@/lib/api/research", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/research")>();
  return { ...actual, listResearchRuns: vi.fn(), startResearch: vi.fn() };
});

import {
  createCampaign,
  getCampaign,
  listCampaigns,
} from "@/lib/api/campaigns";
import { listResearchRuns, startResearch } from "@/lib/api/research";

const mockListCampaigns = vi.mocked(listCampaigns);
const mockGetCampaign = vi.mocked(getCampaign);
const mockCreateCampaign = vi.mocked(createCampaign);
const mockListRuns = vi.mocked(listResearchRuns);
const mockStartResearch = vi.mocked(startResearch);

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
}

function campaign(id: string, name: string): Campaign {
  return {
    id,
    name,
    description: "Find Australian fintech companies.",
    target_market: "Australia",
    industry: "Fin tech",
    technologies: ["Java", "Kafka"],
    company_size: {
      min: 500,
      max: 5000,
    },
    target_count: 5,
    max_companies_to_research: 10,
    status: "DRAFT",
    created_at: "2026-10-05T00:00:00Z",
    updated_at: "2026-10-05T00:00:00Z",
  };
}

function run(runId: string, campaignId: string): ResearchRunListItem {
  return {
    run_id: runId,
    status: "COMPLETED",
    created_at: "2026-10-05T01:00:00Z",
    started_at: "2026-10-05T01:00:00Z",
    completed_at: "2026-10-05T01:10:00Z",
    campaign: {
      id: campaignId,
      name: "Fintech",
      target_count: 5,
      max_companies_to_research: 10,
    },
    summary: {
      researched: 2,
      qualified: 1,
      not_qualified: 1,
      insufficient_evidence: 0,
      accepted: 0,
      rejected: 0,
      unreviewed: 2,
    },
  };
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => cleanup());

describe("CampaignsPage", () => {
  it("renders multiple campaigns and opens their explicit campaign IDs", async () => {
    mockListCampaigns.mockResolvedValue([
      campaign("campaign-a", "Australian Fintech"),
      campaign("campaign-b", "AI Companies"),
    ]);
    renderWithQuery(<CampaignsPage />);

    expect(await screen.findByText("Australian Fintech")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open Australian Fintech" }),
    ).toHaveAttribute("href", "/campaigns/campaign-a");
    expect(
      screen.getByRole("link", { name: "Open AI Companies" }),
    ).toHaveAttribute("href", "/campaigns/campaign-b");
    expect(
      screen.getByRole("link", { name: "Create Campaign" }),
    ).toHaveAttribute("href", "/campaigns/new");
  });

  it("shows loading, empty, and error states", async () => {
    let resolveCampaigns!: (items: Campaign[]) => void;
    mockListCampaigns.mockReturnValue(
      new Promise((resolve) => {
        resolveCampaigns = resolve;
      }),
    );
    const view = renderWithQuery(<CampaignsPage />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading campaigns");
    resolveCampaigns([]);
    expect(await screen.findByText("No campaigns yet")).toBeInTheDocument();
    view.unmount();

    mockListCampaigns.mockRejectedValueOnce(
      new Error("Campaign service unavailable"),
    );
    renderWithQuery(<CampaignsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Campaign service unavailable",
    );
  });
});

describe("CampaignFormPage", () => {
  it("validates campaign fields and accepts technologies from one list", async () => {
    mockCreateCampaign.mockResolvedValue(campaign("created", "Campaign"));
    renderWithQuery(<CampaignFormPage />);

    fireEvent.change(document.getElementById("target-count")!, {
      target: { value: "0" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Campaign" }));
    expect(
      await screen.findByText("Enter a campaign name."),
    ).toBeInTheDocument();

    fireEvent.change(document.getElementById("target-count")!, {
      target: { value: "5" },
    });

    fireEvent.change(screen.getByRole("textbox", { name: /Campaign name/ }), {
      target: { value: "Fintech" },
    });
    fireEvent.change(
      screen.getByRole("textbox", { name: "Add technologies" }),
      {
        target: { value: "Java" },
      },
    );
    fireEvent.keyDown(
      screen.getByRole("textbox", { name: "Add technologies" }),
      {
        key: "Enter",
      },
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: "Add technologies" }),
      {
        target: { value: " java " },
      },
    );
    fireEvent.keyDown(
      screen.getByRole("textbox", { name: "Add technologies" }),
      {
        key: "Enter",
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Campaign" }));

    await waitFor(() => expect(mockCreateCampaign).toHaveBeenCalled());
  });

  it("submits backend-shaped criteria and navigates using the returned campaign ID", async () => {
    mockCreateCampaign.mockResolvedValue(
      campaign("campaign-created", "Fintech Java"),
    );
    renderWithQuery(<CampaignFormPage />);

    fireEvent.change(screen.getByLabelText("Campaign name"), {
      target: { value: "Fintech Java" },
    });
    fireEvent.change(screen.getByLabelText("Target company count"), {
      target: { value: "7" },
    });
    fireEvent.change(screen.getByLabelText("Target market"), {
      target: { value: "Australia" },
    });
    fireEvent.change(screen.getByLabelText("Industry"), {
      target: { value: "Fin tech" },
    });
    fireEvent.change(
      screen.getByRole("textbox", { name: "Add technologies" }),
      {
        target: { value: "Java" },
      },
    );
    fireEvent.keyDown(
      screen.getByRole("textbox", { name: "Add technologies" }),
      {
        key: "Enter",
      },
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: "Add technologies" }),
      {
        target: { value: "Kafka" },
      },
    );
    fireEvent.keyDown(
      screen.getByRole("textbox", { name: "Add technologies" }),
      {
        key: "Enter",
      },
    );
    fireEvent.change(screen.getByLabelText("Minimum employees"), {
      target: { value: "500" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Create Campaign" }));

    await waitFor(() =>
      expect(mockCreateCampaign.mock.calls[0]?.[0]).toEqual({
        name: "Fintech Java",
        description: "",
        target_count: 7,
        max_companies_to_research: 15,
        status: "DRAFT",
        target_market: "Australia",
        industry: "Fin tech",
        technologies: ["Java", "Kafka"],
        company_size: { min: 500 },
      }),
    );
    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("/campaigns/campaign-created"),
    );
  });

  it("shows backend validation details", async () => {
    mockCreateCampaign.mockRejectedValueOnce(
      new ApiError("Request failed", 422, {
        detail: [
          {
            loc: ["body", "technologies", 1],
            msg: "Duplicate technology",
          },
        ],
      }),
    );
    renderWithQuery(<CampaignFormPage />);
    fireEvent.change(screen.getByLabelText("Campaign name"), {
      target: { value: "Valid campaign" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Campaign" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "technologies → 1: Duplicate technology",
    );
  });
});

describe("CampaignDetailsPage", () => {
  it("shows persisted criteria and only history for this campaign", async () => {
    mockGetCampaign.mockResolvedValue(
      campaign("campaign-a", "Australian Fintech"),
    );
    mockListRuns.mockResolvedValue([
      run("run-a1", "campaign-a"),
      run("run-b1", "campaign-b"),
    ]);
    renderWithQuery(<CampaignDetailsPage campaignId="campaign-a" />);

    expect(
      await screen.findByRole("heading", { name: "Australian Fintech" }),
    ).toBeInTheDocument();
    expect(screen.getByText("campaign-a")).toBeInTheDocument();
    expect(screen.getByText("Australia")).toBeInTheDocument();
    expect(screen.getByText("Java")).toBeInTheDocument();
    expect(screen.getByText("≥ 500 employees")).toBeInTheDocument();
    expect(screen.getByText("≤ 5000 employees")).toBeInTheDocument();
    expect(screen.getByText("run-a1")).toBeInTheDocument();
    expect(screen.queryByText("run-b1")).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open research run run-a1" }),
    ).toHaveAttribute("href", "/research/run-a1");
  });

  it("prevents a duplicate pending start and navigates with each returned run ID", async () => {
    mockGetCampaign.mockResolvedValue(
      campaign("campaign-a", "Australian Fintech"),
    );
    mockListRuns.mockResolvedValue([]);
    let finishStart!: (result: {
      research_run_id: string;
      status: string;
      companies_found: number;
    }) => void;
    mockStartResearch.mockReturnValueOnce(
      new Promise((resolve) => {
        finishStart = resolve;
      }),
    );
    mockStartResearch.mockResolvedValueOnce({
      research_run_id: "run-second",
      status: "COMPLETED",
      companies_found: 1,
    });
    renderWithQuery(<CampaignDetailsPage campaignId="campaign-a" />);

    const startButton = await screen.findByRole("button", {
      name: "Start Research",
    });
    fireEvent.click(startButton);
    await waitFor(() => expect(startButton).toBeDisabled());
    fireEvent.click(startButton);
    expect(mockStartResearch).toHaveBeenCalledTimes(1);

    finishStart({
      research_run_id: "run-first",
      status: "COMPLETED",
      companies_found: 1,
    });
    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("/research/run-first"),
    );
    await waitFor(() => expect(startButton).not.toBeDisabled());
    fireEvent.click(startButton);
    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("/research/run-second"),
    );
    expect(mockStartResearch).toHaveBeenNthCalledWith(1, "campaign-a");
    expect(mockStartResearch).toHaveBeenNthCalledWith(2, "campaign-a");
  });
});
