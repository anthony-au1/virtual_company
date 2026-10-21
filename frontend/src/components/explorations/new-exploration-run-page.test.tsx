import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NewExplorationRunPage } from "@/components/explorations/new-exploration-run-page";
import { ApiError } from "@/lib/api/client";
import type {
  ResearchCompany,
  ResearchResults,
  ResearchRunListItem,
} from "@/lib/api/research";
import { getResearchRunResults, listResearchRuns } from "@/lib/api/research";
import {
  startExplorationRun,
  type StartedExplorationRun,
} from "@/lib/api/explorations";
import { explorationRunsQueryKey } from "@/lib/queries/query-keys";

const { mockPush } = vi.hoisted(() => ({ mockPush: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/lib/api/explorations", () => ({
  listExplorationRuns: vi.fn(),
  startExplorationRun: vi.fn(),
}));

vi.mock("@/lib/api/research", () => ({
  getResearchRunResults: vi.fn(),
  listResearchRuns: vi.fn(),
}));

const mockListResearchRuns = vi.mocked(listResearchRuns);
const mockGetResults = vi.mocked(getResearchRunResults);
const mockStart = vi.mocked(startExplorationRun);

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return {
    client,
    ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>),
  };
}

function researchRun(
  runId: string,
  campaignName: string,
  status = "COMPLETED",
): ResearchRunListItem {
  return {
    run_id: runId,
    status,
    created_at: "2026-10-10T10:00:00Z",
    started_at: "2026-10-10T10:00:00Z",
    completed_at: "2026-10-10T10:10:00Z",
    campaign: {
      id: `campaign-${runId}`,
      name: campaignName,
      target_count: 5,
      max_companies_to_research: 10,
    },
    summary: {
      researched: 3,
      qualified: 1,
      not_qualified: 1,
      insufficient_evidence: 1,
    },
  };
}

function company(
  companyId: string,
  name: string,
  qualification_status: ResearchCompany["qualification_status"],
): ResearchCompany {
  return {
    company_id: companyId,
    name,
    website: `https://${companyId}.example.com`,
    qualification_status,
    summary: { matched: 1, mismatched: 0, unknown: 0 },
    criteria: [
      {
        criterion: "target_market",
        subject: "Australia",
        status: "MATCH",
        reason: "Company operates in Australia.",
        evidence: [],
      },
    ],
  };
}

function results(runId: string, companies: ResearchCompany[]): ResearchResults {
  return {
    research_run: {
      id: runId,
      campaign_id: `campaign-${runId}`,
      status: "COMPLETED",
      started_at: "2026-10-10T10:00:00Z",
      completed_at: "2026-10-10T10:10:00Z",
      error: null,
      companies_found: companies.length,
      created_at: "2026-10-10T10:00:00Z",
    },
    campaign: {
      id: `campaign-${runId}`,
      name: `Campaign ${runId}`,
      description: null,
      target_count: 5,
      max_companies_to_research: 10,
      criteria: {
        target_market: "Australia",
        industry: null,
        keywords: [],
        company_size: null,
      },
    },
    summary: {
      researched: companies.length,
      qualified: 1,
      not_qualified: 1,
      insufficient_evidence: 1,
    },
    companies,
  };
}

const runACompanies = [
  company("a1", "Company A1", "QUALIFIED"),
  company("a2", "Company A2", "NOT_QUALIFIED"),
  company("a3", "Company A3", "INSUFFICIENT_EVIDENCE"),
];
const runBCompanies = [company("b1", "Company B1", "QUALIFIED")];

beforeEach(() => {
  vi.clearAllMocks();
  mockListResearchRuns.mockResolvedValue([
    researchRun("run-a", "Campaign A"),
    researchRun("run-b", "Campaign B"),
    researchRun("run-empty", "Campaign without companies"),
    researchRun("run-active", "Campaign in progress", "RUNNING"),
  ]);
  mockGetResults.mockImplementation(async (runId) =>
    results(
      runId,
      runId === "run-a"
        ? runACompanies
        : runId === "run-empty"
          ? []
          : runBCompanies,
    ),
  );
});

afterEach(() => cleanup());

describe("NewExplorationRunPage", () => {
  it("offers completed ResearchRuns and loads only the selected run's results", async () => {
    renderWithQuery(<NewExplorationRunPage explorationId="exploration-1" />);

    expect(await screen.findByLabelText(/Campaign A/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Campaign B/)).toBeInTheDocument();
    expect(
      screen.queryByLabelText(/Campaign in progress/),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/Campaign A/));

    expect(await screen.findByText("Company A1")).toBeInTheDocument();
    expect(screen.getByText("Company A2")).toBeInTheDocument();
    expect(screen.getByText("Company A3")).toBeInTheDocument();
    expect(screen.getByText("AI: QUALIFIED")).toBeInTheDocument();
    expect(screen.getByText("AI: NOT QUALIFIED")).toBeInTheDocument();
    expect(screen.getByText("AI: INSUFFICIENT EVIDENCE")).toBeInTheDocument();
    expect(screen.getAllByText("MATCH")).toHaveLength(3);
    expect(mockGetResults).toHaveBeenCalledWith("run-a");
    expect(
      screen.getByRole("button", { name: "Start Exploration Run" }),
    ).toBeDisabled();
  });

  it("allows selection across qualification statuses and submits one selected run", async () => {
    const { client } = renderWithQuery(
      <NewExplorationRunPage explorationId="exploration-1" />,
    );
    client.setQueryData(explorationRunsQueryKey("exploration-1"), []);
    fireEvent.click(await screen.findByLabelText(/Campaign A/));
    const qualified = await screen.findByLabelText("Select Company A1");
    const notQualified = screen.getByLabelText("Select Company A2");
    const insufficient = screen.getByLabelText("Select Company A3");
    fireEvent.click(qualified);
    fireEvent.click(notQualified);
    fireEvent.click(insufficient);

    expect(screen.getByText("3 companies selected")).toBeInTheDocument();
    const startButton = screen.getByRole("button", {
      name: "Start Exploration Run",
    });
    expect(startButton).toBeEnabled();
    mockStart.mockResolvedValue({
      id: "exploration-run-1",
      exploration_id: "exploration-1",
      research_run_id: "run-a",
      status: "RUNNING",
      started_at: "2026-10-10T11:00:00Z",
      completed_at: null,
      company_ids: ["a1", "a2", "a3"],
    });
    fireEvent.click(startButton);

    await waitFor(() =>
      expect(mockStart).toHaveBeenCalledWith("exploration-1", {
        research_run_id: "run-a",
        company_ids: ["a1", "a2", "a3"],
      }),
    );
    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("/explorations/exploration-1"),
    );
    expect(
      client.getQueryState(explorationRunsQueryKey("exploration-1"))
        ?.isInvalidated,
    ).toBe(true);
    expect(mockGetResults).toHaveBeenCalledTimes(1);
  });

  it("clears prior company IDs when switching ResearchRuns", async () => {
    renderWithQuery(<NewExplorationRunPage explorationId="exploration-1" />);
    fireEvent.click(await screen.findByLabelText(/Campaign A/));
    fireEvent.click(await screen.findByLabelText("Select Company A1"));
    fireEvent.click(screen.getByLabelText(/Campaign B/));

    expect(await screen.findByText("Company B1")).toBeInTheDocument();
    expect(screen.queryByText("Company A1")).not.toBeInTheDocument();
    expect(screen.getByText("0 companies selected")).toBeInTheDocument();
    expect(screen.getByLabelText("Select Company B1")).not.toBeChecked();
    expect(
      screen.getByRole("button", { name: "Start Exploration Run" }),
    ).toBeDisabled();

    fireEvent.click(screen.getByLabelText("Select Company B1"));
    mockStart.mockResolvedValue({
      id: "new-run",
      exploration_id: "exploration-1",
      research_run_id: "run-b",
      status: "RUNNING",
      started_at: "2026-10-10T11:00:00Z",
      completed_at: null,
      company_ids: ["b1"],
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Start Exploration Run" }),
    );

    await waitFor(() =>
      expect(mockStart).toHaveBeenCalledWith("exploration-1", {
        research_run_id: "run-b",
        company_ids: ["b1"],
      }),
    );
  });

  it("prevents duplicate submission while the Start request is pending", async () => {
    let resolveStart!: (value: StartedExplorationRun) => void;
    mockStart.mockReturnValue(
      new Promise((resolve) => {
        resolveStart = resolve;
      }),
    );
    renderWithQuery(<NewExplorationRunPage explorationId="exploration-1" />);
    fireEvent.click(await screen.findByLabelText(/Campaign A/));
    fireEvent.click(await screen.findByLabelText("Select Company A1"));
    const button = screen.getByRole("button", {
      name: "Start Exploration Run",
    });
    fireEvent.click(button);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Starting Exploration Run…" }),
      ).toBeDisabled(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Starting Exploration Run…" }),
    );
    expect(mockStart).toHaveBeenCalledTimes(1);

    resolveStart({
      id: "new-run",
      exploration_id: "exploration-1",
      research_run_id: "run-a",
      status: "RUNNING",
      started_at: "2026-10-10T11:00:00Z",
      completed_at: null,
      company_ids: ["a1"],
    });
    await waitFor(() => expect(mockPush).toHaveBeenCalled());
  });

  it("loads results for exactly one ResearchRun and never posts an empty selection", async () => {
    renderWithQuery(<NewExplorationRunPage explorationId="exploration-1" />);
    fireEvent.click(await screen.findByLabelText(/Campaign B/));

    expect(await screen.findByText("Company B1")).toBeInTheDocument();
    expect(mockGetResults).toHaveBeenCalledTimes(1);
    expect(mockGetResults).toHaveBeenCalledWith("run-b");
    expect(
      screen.getByRole("button", { name: "Start Exploration Run" }),
    ).toBeDisabled();
    expect(mockStart).not.toHaveBeenCalled();
  });

  it("shows an empty state when the chosen ResearchRun has no company results", async () => {
    renderWithQuery(<NewExplorationRunPage explorationId="exploration-1" />);
    fireEvent.click(await screen.findByLabelText(/Campaign without companies/));

    expect(
      await screen.findByText(
        "This Research Run has no company results to select.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Start Exploration Run" }),
    ).toBeDisabled();
  });

  it.each([
    [400, "One or more selected companies are no longer in this Research Run."],
    [404, "The Exploration or Research Run is no longer available."],
    [409, "This Research Run is no longer eligible."],
    [422, "The selection could not be validated."],
  ])("shows a safe message for backend status %i", async (status, message) => {
    mockStart.mockRejectedValue(
      new ApiError("private backend detail", status, {
        detail: "private backend detail",
      }),
    );
    renderWithQuery(<NewExplorationRunPage explorationId="exploration-1" />);
    fireEvent.click(await screen.findByLabelText(/Campaign A/));
    fireEvent.click(await screen.findByLabelText("Select Company A1"));
    fireEvent.click(
      screen.getByRole("button", { name: "Start Exploration Run" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("alert")).not.toHaveTextContent(
      "private backend detail",
    );
    expect(mockPush).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Select Company A1")).toBeChecked();
  });
});
