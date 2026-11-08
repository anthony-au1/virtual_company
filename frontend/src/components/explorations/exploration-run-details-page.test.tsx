import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ExplorationRunDetailsPage,
  explorationRunStatusPollingInterval,
} from "@/components/explorations/exploration-run-details-page";
import { ApiError } from "@/lib/api/client";
import {
  executeExplorationRun,
  getExplorationRun,
  listExplorationCompanyEvidence,
  listExplorationCompanyFacts,
  listExplorationCompanyHypotheses,
  listExplorationObligations,
  listExplorationRunCompanies,
  listExplorationRuns,
} from "@/lib/api/explorations";

vi.mock("@/lib/api/explorations", () => ({
  executeExplorationRun: vi.fn(),
  getExplorationRun: vi.fn(),
  listExplorationCompanyEvidence: vi.fn(),
  listExplorationCompanyFacts: vi.fn(),
  listExplorationCompanyHypotheses: vi.fn(),
  listExplorationObligations: vi.fn(),
  listExplorationRunCompanies: vi.fn(),
  listExplorationRuns: vi.fn(),
}));

const mockExecute = vi.mocked(executeExplorationRun);
const mockGetStatus = vi.mocked(getExplorationRun);
const mockEvidence = vi.mocked(listExplorationCompanyEvidence);
const mockFacts = vi.mocked(listExplorationCompanyFacts);
const mockHypotheses = vi.mocked(listExplorationCompanyHypotheses);
const mockObligations = vi.mocked(listExplorationObligations);
const mockCompanies = vi.mocked(listExplorationRunCompanies);
const mockRuns = vi.mocked(listExplorationRuns);

const explorationId = "exploration-1";
const runId = "run-1";

function runStatus(
  status:
    | "READY"
    | "QUEUED"
    | "RUNNING"
    | "COMPLETED"
    | "PARTIAL"
    | "FAILED"
    | "CANCELLED",
) {
  return {
    id: runId,
    exploration_id: explorationId,
    status,
    started_at: "2026-11-08T10:00:00Z",
    completed_at:
      status === "COMPLETED" ||
      status === "PARTIAL" ||
      status === "FAILED" ||
      status === "CANCELLED"
        ? "2026-11-08T10:10:00Z"
        : null,
  };
}

const companies = [
  {
    id: "exploration-company-link-1",
    company_id: "research-company-1",
    name: "Company One",
    website: "https://one.example.test",
    domain: "one.example.test",
  },
  {
    id: "exploration-company-link-2",
    company_id: "research-company-2",
    name: "Company Two",
    website: null,
    domain: "two.example.test",
  },
];

const evidence = {
  id: "evidence-1",
  exploration_company_id: "exploration-company-link-1",
  exploration_obligation_id: "obligation-1",
  claim: "Supports the company claim",
  supporting_excerpt: "A quoted supporting excerpt.",
  source_url: "https://one.example.test/source",
  requested_url: null,
  source_title: "Source title",
  created_at: "2026-11-08T10:05:00Z",
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <ExplorationRunDetailsPage
          explorationId={explorationId}
          runId={runId}
        />
      </QueryClientProvider>,
    ),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGetStatus.mockResolvedValue(runStatus("READY"));
  mockRuns.mockResolvedValue([
    {
      id: runId,
      research_run_id: "source-research-run",
      status: "READY",
      started_at: "2026-11-08T10:00:00Z",
      completed_at: null,
      campaign_name: "Source campaign",
      selected_company_count: companies.length,
    },
  ]);
  mockCompanies.mockResolvedValue(companies);
  mockEvidence.mockResolvedValue([evidence]);
  mockFacts.mockResolvedValue([
    {
      id: "fact-1",
      exploration_company_id: "exploration-company-link-1",
      statement: "A persisted fact.",
      created_at: "2026-11-08T10:06:00Z",
    },
  ]);
  mockHypotheses.mockResolvedValue([
    {
      id: "hypothesis-1",
      exploration_company_id: "exploration-company-link-1",
      statement: "A persisted hypothesis.",
      created_at: "2026-11-08T10:07:00Z",
    },
  ]);
  mockObligations.mockResolvedValue([
    {
      id: "obligation-1",
      exploration_id: explorationId,
      description: "Identify relevant capabilities.",
      created_at: "2026-11-08T09:00:00Z",
    },
  ]);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("ExplorationRunDetailsPage", () => {
  it("shows source run details and offers execution only while READY", async () => {
    renderPage();

    expect(
      await screen.findByRole("button", { name: "Execute Exploration" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("link", { name: /Source Research Run/ }),
    ).toHaveAttribute("href", "/research/source-research-run");
    await waitFor(() =>
      expect(screen.getByLabelText("Company")).toHaveValue(
        "exploration-company-link-1",
      ),
    );
    expect(
      await screen.findByText("Identify relevant capabilities."),
    ).toBeInTheDocument();
    expect(mockEvidence).toHaveBeenCalledWith(
      explorationId,
      "exploration-company-link-1",
    );
    expect(mockEvidence).not.toHaveBeenCalledWith(
      explorationId,
      "research-company-1",
    );
  });

  it.each([
    "QUEUED",
    "RUNNING",
    "COMPLETED",
    "PARTIAL",
    "FAILED",
    "CANCELLED",
  ] as const)("does not offer execution for %s", async (status) => {
    mockGetStatus.mockResolvedValue(runStatus(status));
    renderPage();

    expect(await screen.findByText(status)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Execute Exploration" }),
    ).not.toBeInTheDocument();
  });

  it("disables duplicate execution and refreshes to QUEUED after 202", async () => {
    let resolveExecution!: (result: {
      exploration_run_id: string;
      status: "QUEUED";
    }) => void;
    mockExecute.mockReturnValue(
      new Promise((resolve) => {
        resolveExecution = resolve;
      }),
    );
    mockGetStatus
      .mockResolvedValueOnce(runStatus("READY"))
      .mockResolvedValue(runStatus("QUEUED"));
    renderPage();

    const button = await screen.findByRole("button", {
      name: "Execute Exploration",
    });
    fireEvent.click(button);
    const pendingButton = await screen.findByRole("button", {
      name: "Queueing run…",
    });
    expect(pendingButton).toBeDisabled();
    fireEvent.click(pendingButton);
    expect(mockExecute).toHaveBeenCalledTimes(1);
    expect(mockExecute).toHaveBeenCalledWith(explorationId, runId);

    resolveExecution({ exploration_run_id: runId, status: "QUEUED" });
    expect(
      await screen.findByText("This run is queued and waiting to start."),
    ).toBeInTheDocument();
  });

  it("refreshes status after 409 without resubmitting the execute request", async () => {
    mockExecute.mockRejectedValue(new ApiError("conflict", 409, {}));
    mockGetStatus
      .mockResolvedValueOnce(runStatus("READY"))
      .mockResolvedValue(runStatus("QUEUED"));
    renderPage();

    fireEvent.click(
      await screen.findByRole("button", { name: "Execute Exploration" }),
    );

    expect(
      await screen.findByText("This run is queued and waiting to start."),
    ).toBeInTheDocument();
    expect(mockExecute).toHaveBeenCalledTimes(1);
    expect(mockGetStatus).toHaveBeenCalledTimes(2);
  });

  it("requires a successful status refresh after a server error before another attempt", async () => {
    mockExecute.mockRejectedValue(new ApiError("server error", 500, {}));
    renderPage();

    fireEvent.click(
      await screen.findByRole("button", { name: "Execute Exploration" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Refresh its status before trying again.",
    );
    expect(
      screen.getByRole("button", { name: "Execute Exploration" }),
    ).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Execute Exploration" }),
      ).toBeEnabled(),
    );
    expect(mockExecute).toHaveBeenCalledTimes(1);
  });

  it("loads result sections lazily and switches companies by ExplorationCompany link", async () => {
    renderPage();
    expect(
      await screen.findByText("Supports the company claim"),
    ).toBeInTheDocument();
    expect(mockFacts).not.toHaveBeenCalled();
    expect(mockHypotheses).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Facts" }));
    expect(await screen.findByText("A persisted fact.")).toBeInTheDocument();
    expect(mockFacts).toHaveBeenCalledWith(
      explorationId,
      "exploration-company-link-1",
    );

    fireEvent.change(screen.getByLabelText("Company"), {
      target: { value: "exploration-company-link-2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Hypotheses" }));
    expect(
      await screen.findByText("A persisted hypothesis."),
    ).toBeInTheDocument();
    expect(mockHypotheses).toHaveBeenCalledWith(
      explorationId,
      "exploration-company-link-2",
    );
  });

  it("shows valid empty results and omits unsafe optional source URLs", async () => {
    mockEvidence.mockResolvedValue([
      { ...evidence, source_url: "javascript:alert(1)", source_title: null },
    ]);
    renderPage();
    expect(
      await screen.findByText("Supports the company claim"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Open source" }),
    ).not.toBeInTheDocument();

    mockFacts.mockResolvedValue([]);
    fireEvent.click(screen.getByRole("button", { name: "Facts" }));
    expect(await screen.findByText("No facts yet")).toBeInTheDocument();
  });

  it("renders result query errors with a retry action", async () => {
    mockEvidence.mockRejectedValue(new ApiError("temporary", 503, {}));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Evidence could not be loaded.",
    );
    expect(
      screen.getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
  });

  it("polls only queued and running states and stops on errors or terminal states", () => {
    expect(explorationRunStatusPollingInterval("READY", false)).toBe(false);
    expect(explorationRunStatusPollingInterval("QUEUED", false)).toBe(2_500);
    expect(explorationRunStatusPollingInterval("RUNNING", false)).toBe(2_500);
    for (const status of [
      "COMPLETED",
      "PARTIAL",
      "FAILED",
      "CANCELLED",
    ] as const) {
      expect(explorationRunStatusPollingInterval(status, false)).toBe(false);
    }
    expect(explorationRunStatusPollingInterval("RUNNING", true)).toBe(false);
  });

  it("cleans up active polling after unmount", async () => {
    vi.useFakeTimers();
    mockGetStatus.mockResolvedValue(runStatus("QUEUED"));
    const view = renderPage();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const callsBeforeUnmount = mockGetStatus.mock.calls.length;
    view.unmount();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });

    expect(callsBeforeUnmount).toBeGreaterThan(0);
    expect(mockGetStatus).toHaveBeenCalledTimes(callsBeforeUnmount);
  });
});
