import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ExplorationRunDetailsPage,
  explorationRunStatusPollingInterval,
} from "@/features/exploration/components/exploration-run-details-page";
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
  type ExplorationEvidence,
  type ExplorationFact,
  type ExplorationHypothesis,
} from "@/features/exploration/api/explorations";
import { explorationCompanyEvidenceQueryKey } from "@/features/exploration/query-keys";

const { mockReplace, mockRouter } = vi.hoisted(() => {
  const replace = vi.fn();
  return { mockReplace: replace, mockRouter: { replace } };
});

vi.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
}));

vi.mock("@/features/exploration/api/explorations", () => ({
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
  id = runId,
) {
  return {
    id,
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

function evidenceRecords(count: number): ExplorationEvidence[] {
  return Array.from({ length: count }, (_, index) => ({
    ...evidence,
    id: `evidence-${index + 1}`,
    claim: `Evidence claim ${index + 1}`,
  }));
}

function factRecords(
  count: number,
  evidenceIds: string[] = [],
): ExplorationFact[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `fact-${index + 1}`,
    exploration_company_id: companies[0].id,
    statement: `Fact statement ${index + 1}`,
    created_at: "2026-11-08T10:06:00Z",
    evidence_ids: evidenceIds,
  }));
}

function hypothesisRecords(
  count: number,
  factIds: string[] = [],
): ExplorationHypothesis[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `hypothesis-${index + 1}`,
    exploration_company_id: companies[0].id,
    statement: `Hypothesis statement ${index + 1}`,
    created_at: "2026-11-08T10:07:00Z",
    fact_ids: factIds,
  }));
}

function renderPage({
  executionUnconfirmed = false,
  pageRunId = runId,
}: { executionUnconfirmed?: boolean; pageRunId?: string } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <ExplorationRunDetailsPage
          executionUnconfirmed={executionUnconfirmed}
          explorationId={explorationId}
          runId={pageRunId}
        />
      </QueryClientProvider>,
    ),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockExecute.mockReset();
  mockExecute.mockResolvedValue({
    exploration_run_id: runId,
    status: "QUEUED",
  });
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
      evidence_ids: ["evidence-1"],
    },
  ]);
  mockHypotheses.mockResolvedValue([
    {
      id: "hypothesis-1",
      exploration_company_id: "exploration-company-link-1",
      statement: "A persisted hypothesis.",
      created_at: "2026-11-08T10:07:00Z",
      fact_ids: ["fact-1"],
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

  it("shows the Save & Execute handoff error from persisted READY status", async () => {
    renderPage({ executionUnconfirmed: true });

    expect(
      await screen.findByText(
        "The Run was saved, but execution was not confirmed. It remains READY; use Execute Exploration to try again.",
      ),
    ).toBeInTheDocument();
    expect(mockReplace).toHaveBeenCalledWith(
      `/explorations/${explorationId}/runs/${runId}`,
      { scroll: false },
    );
    expect(
      screen.getByRole("button", { name: "Execute Exploration" }),
    ).toBeEnabled();

    fireEvent.click(
      screen.getByRole("button", { name: "Execute Exploration" }),
    );
    await waitFor(() => expect(mockExecute).toHaveBeenCalledTimes(1));
    expect(
      screen.queryByText(/The Run was saved, but execution was not confirmed/),
    ).not.toBeInTheDocument();
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

  it("paginates 520 top-level Evidence records and clamps controls at both ends", async () => {
    mockEvidence.mockResolvedValue(evidenceRecords(520));
    renderPage();

    expect(await screen.findByText("Evidence claim 1")).toBeInTheDocument();
    const panel = document.getElementById("company-results-panel");
    expect(panel).not.toBeNull();
    expect(within(panel as HTMLElement).getAllByRole("listitem")).toHaveLength(
      50,
    );
    expect(
      screen.getByRole("heading", { name: "Evidence (520)" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Showing 1–50 of 520")).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 11")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Evidence claim 51")).toBeInTheDocument();
    expect(screen.queryByText("Evidence claim 1")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 51–100 of 520")).toBeInTheDocument();
    expect(within(panel as HTMLElement).getAllByRole("listitem")).toHaveLength(
      50,
    );

    for (let page = 2; page < 11; page += 1) {
      fireEvent.click(screen.getByRole("button", { name: "Next" }));
    }
    expect(screen.getByText("Evidence claim 501")).toBeInTheDocument();
    expect(screen.getByText("Evidence claim 520")).toBeInTheDocument();
    expect(screen.getByText("Showing 501–520 of 520")).toBeInTheDocument();
    expect(screen.getByText("Page 11 of 11")).toBeInTheDocument();
    expect(within(panel as HTMLElement).getAllByRole("listitem")).toHaveLength(
      20,
    );
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(screen.getByText("Showing 451–500 of 520")).toBeInTheDocument();
    expect(screen.getByText("Evidence claim 451")).toBeInTheDocument();
  });

  it("paginates Facts independently and leaves small Hypotheses unpaginated", async () => {
    mockFacts.mockResolvedValue(factRecords(411));
    mockHypotheses.mockResolvedValue(hypothesisRecords(10));
    renderPage();

    await screen.findByLabelText("Company");
    fireEvent.click(screen.getByRole("button", { name: "Facts" }));
    expect(await screen.findByText("Fact statement 1")).toBeInTheDocument();
    const panel = document.getElementById("company-results-panel");
    expect(panel).not.toBeNull();
    expect(within(panel as HTMLElement).getAllByRole("listitem")).toHaveLength(
      50,
    );
    expect(
      screen.getByRole("heading", { name: "Facts (411)" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 9")).toBeInTheDocument();
    expect(screen.getByText("Showing 1–50 of 411")).toBeInTheDocument();

    for (let page = 1; page < 9; page += 1) {
      fireEvent.click(screen.getByRole("button", { name: "Next" }));
    }
    expect(screen.getByText("Fact statement 401")).toBeInTheDocument();
    expect(screen.getByText("Fact statement 411")).toBeInTheDocument();
    expect(screen.getByText("Showing 401–411 of 411")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(within(panel as HTMLElement).getAllByRole("listitem")).toHaveLength(
      11,
    );

    fireEvent.click(screen.getByRole("button", { name: "Hypotheses" }));
    expect(
      await screen.findByText("Hypothesis statement 1"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Hypotheses (10)" }),
    ).toBeInTheDocument();
    expect(within(panel as HTMLElement).getAllByRole("listitem")).toHaveLength(
      10,
    );
    expect(
      screen.queryByRole("navigation", { name: "Hypotheses pagination" }),
    ).not.toBeInTheDocument();
  });

  it("keeps each tab page and resets every category when the company changes", async () => {
    mockEvidence.mockResolvedValue(evidenceRecords(110));
    mockFacts.mockResolvedValue(factRecords(110));
    mockHypotheses.mockResolvedValue(hypothesisRecords(110));
    renderPage();

    expect(await screen.findByText("Evidence claim 1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Facts" }));
    expect(await screen.findByText("Fact statement 1")).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    fireEvent.click(screen.getByRole("button", { name: "Hypotheses" }));
    expect(
      await screen.findByText("Hypothesis statement 1"),
    ).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    fireEvent.click(screen.getByRole("button", { name: "Evidence" }));
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Facts" }));
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Company"), {
      target: { value: companies[1].id },
    });
    expect(screen.getByLabelText("Company")).toHaveValue(companies[1].id);
    await waitFor(() =>
      expect(screen.getByText("Page 1 of 3")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Hypotheses" }));
    await waitFor(() =>
      expect(screen.getByText("Page 1 of 3")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Evidence" }));
    await waitFor(() =>
      expect(screen.getByText("Page 1 of 3")).toBeInTheDocument(),
    );
  });

  it("resets pagination when the Exploration Run changes", async () => {
    mockEvidence.mockResolvedValue(evidenceRecords(110));
    const view = renderPage();
    expect(await screen.findByText("Evidence claim 1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();

    mockGetStatus.mockResolvedValue(runStatus("READY", "run-2"));
    view.rerender(
      <QueryClientProvider client={view.client}>
        <ExplorationRunDetailsPage
          explorationId={explorationId}
          runId="run-2"
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Evidence claim 1")).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
  });

  it("clamps the current page when refreshed results shrink", async () => {
    mockEvidence
      .mockResolvedValueOnce(evidenceRecords(120))
      .mockResolvedValueOnce(evidenceRecords(10));
    const { client } = renderPage();
    expect(await screen.findByText("Evidence claim 1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Page 3 of 3")).toBeInTheDocument();

    act(() => {
      client.setQueryData(
        explorationCompanyEvidenceQueryKey(
          explorationId,
          runId,
          companies[0].id,
        ),
        evidenceRecords(10),
      );
    });

    expect(
      await screen.findByRole("heading", { name: "Evidence (10)" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Page 3 of 3")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Evidence pagination" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Evidence claim 10")).toBeInTheDocument();
  });

  it("keeps all nested supporting Facts and Evidence outside top-level pagination", async () => {
    const nestedEvidence = evidenceRecords(55);
    const nestedFacts = factRecords(
      55,
      nestedEvidence.map((record) => record.id),
    );
    mockEvidence.mockResolvedValue(nestedEvidence);
    mockFacts.mockResolvedValue(nestedFacts);
    mockHypotheses.mockResolvedValue(
      hypothesisRecords(
        1,
        nestedFacts.map((record) => record.id),
      ),
    );
    renderPage();

    await screen.findByLabelText("Company");
    fireEvent.click(screen.getByRole("button", { name: "Evidence" }));
    expect(await screen.findByText("Evidence claim 1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hypotheses" }));
    fireEvent.click(await screen.findByText("Supporting Facts (55)"));
    expect(await screen.findByText("Fact statement 1")).toBeInTheDocument();
    expect(screen.getByText("Fact statement 55")).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Supporting Facts pagination" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByText("Supporting Evidence (55)")[0]);
    expect(await screen.findByText("Evidence claim 1")).toBeInTheDocument();
    expect(screen.getAllByText("Supporting Evidence (55)")).toHaveLength(55);
    expect(
      screen.queryByRole("navigation", {
        name: "Supporting Evidence pagination",
      }),
    ).not.toBeInTheDocument();
  });

  it("preserves result loading and Company selection styling", async () => {
    mockEvidence.mockReturnValue(new Promise(() => undefined));
    renderPage();

    expect(await screen.findByText("Loading evidence…")).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Evidence pagination" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Company")).toHaveClass("pr-10");
    expect(
      screen.getByLabelText("Company").parentElement?.querySelector("svg"),
    ).toHaveClass("top-1/2", "-translate-y-1/2");
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

  it("navigates Hypothesis to supporting Facts and Evidence", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Hypotheses" }));

    fireEvent.click(await screen.findByText("Supporting Facts (1)"));
    expect(await screen.findByText("A persisted fact.")).toBeInTheDocument();
    expect(mockFacts).toHaveBeenCalledWith(
      explorationId,
      "exploration-company-link-1",
    );

    fireEvent.click(screen.getByText("Supporting Evidence (1)"));
    expect(
      await screen.findByText("Supports the company claim"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("A quoted supporting excerpt."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open source" })).toHaveAttribute(
      "href",
      "https://one.example.test/source",
    );
  });

  it("shows nested provenance from the Facts view", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Facts" }));

    fireEvent.click(await screen.findByText("Supporting Evidence (1)"));
    expect(
      await screen.findByText("Supports the company claim"),
    ).toBeInTheDocument();
  });

  it("shows neutral unavailable states for unresolved supporting records", async () => {
    mockHypotheses.mockResolvedValue([
      {
        id: "hypothesis-missing-fact",
        exploration_company_id: "exploration-company-link-1",
        statement: "A hypothesis with an unresolved reference.",
        created_at: "2026-11-08T10:07:00Z",
        fact_ids: ["missing-fact"],
      },
    ]);
    mockFacts.mockResolvedValue([]);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Hypotheses" }));
    fireEvent.click(await screen.findByText("Supporting Facts (1)"));

    expect(
      await screen.findByText("Supporting Fact unavailable for this company."),
    ).toBeInTheDocument();
  });

  it("shows unavailable when a supporting Evidence ID is not in the company collection", async () => {
    mockFacts.mockResolvedValue([
      {
        id: "fact-missing-evidence",
        exploration_company_id: "exploration-company-link-1",
        statement: "A fact with an unresolved reference.",
        created_at: "2026-11-08T10:06:00Z",
        evidence_ids: ["missing-evidence"],
      },
    ]);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Facts" }));
    fireEvent.click(await screen.findByText("Supporting Evidence (1)"));

    expect(
      await screen.findByText(
        "Supporting Evidence unavailable for this company.",
      ),
    ).toBeInTheDocument();
  });

  it("shows an error and retry action while resolving supporting records", async () => {
    mockFacts.mockRejectedValue(new ApiError("temporary", 503, {}));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Hypotheses" }));
    fireEvent.click(await screen.findByText("Supporting Facts (1)"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Supporting Facts could not be loaded.",
    );
    expect(
      screen.getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
  });

  it("clears expanded provenance when switching companies", async () => {
    mockHypotheses.mockImplementation(async (_explorationId, companyLinkId) =>
      companyLinkId === "exploration-company-link-1"
        ? [
            {
              id: "hypothesis-1",
              exploration_company_id: "exploration-company-link-1",
              statement: "Company One hypothesis.",
              created_at: "2026-11-08T10:07:00Z",
              fact_ids: ["fact-1"],
            },
          ]
        : [],
    );
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Hypotheses" }));
    fireEvent.click(await screen.findByText("Supporting Facts (1)"));
    expect(await screen.findByText("A persisted fact.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Company"), {
      target: { value: "exploration-company-link-2" },
    });
    expect(await screen.findByText("No hypotheses yet")).toBeInTheDocument();
    expect(screen.queryByText("A persisted fact.")).not.toBeInTheDocument();
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
