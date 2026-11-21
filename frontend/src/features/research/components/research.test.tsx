import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ResearchResultsPage } from "@/features/research/components/results/research-results-page";
import { ResearchRunsPage } from "@/features/research/components/runs/research-runs-page";
import type {
  ResearchResults,
  ResearchRunListItem,
} from "@/features/research/api/research";
import {
  researchRunResultsQueryKey,
  researchRunsQueryKey,
} from "@/features/research/query-keys";
import { formatDate } from "@/lib/format-date";

const { mockPush } = vi.hoisted(() => ({ mockPush: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/research/runs",
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/features/research/api/research", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/features/research/api/research")>();
  return {
    ...actual,
    listResearchRuns: vi.fn(),
    getResearchRunResults: vi.fn(),
    deleteResearchRun: vi.fn(),
  };
});

import {
  deleteResearchRun,
  getResearchRunResults,
  listResearchRuns,
} from "@/features/research/api/research";

const mockedListRuns = vi.mocked(listResearchRuns);
const mockedGetResults = vi.mocked(getResearchRunResults);
const mockedDeleteRun = vi.mocked(deleteResearchRun);

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return {
    client,
    ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>),
  };
}

function run(id: string, name: string): ResearchRunListItem {
  return {
    run_id: id,
    status: id === "run-b" ? "RUNNING" : "COMPLETED",
    created_at: "2026-10-01T00:00:00Z",
    started_at: "2026-10-01T00:00:00Z",
    completed_at: null,
    campaign: {
      id: `campaign-${id}`,
      name,
      target_count: 5,
      max_companies_to_research: 10,
    },
    summary: {
      researched: 1,
      qualified: 1,
      not_qualified: 0,
      insufficient_evidence: 0,
    },
  };
}

function results(runId: string): ResearchResults {
  return {
    research_run: {
      id: runId,
      campaign_id: "campaign-1",
      status: "COMPLETED",
      started_at: "2026-10-01T00:00:00Z",
      completed_at: "2026-10-01T00:10:00Z",
      error: null,
      companies_found: 1,
      created_at: "2026-10-01T00:00:00Z",
    },
    campaign: {
      id: "campaign-1",
      name: "Australian Fintech Java Research",
      description: null,
      target_count: 5,
      max_companies_to_research: 10,
      criteria: {
        target_market: "Australia",
        industry: "Fin tech",
        keywords: ["Java", "Spring", "Kafka"],
        company_size: {
          min: 500,
          max: null,
        },
      },
    },
    summary: {
      researched: 1,
      qualified: 0,
      not_qualified: 1,
      insufficient_evidence: 0,
    },
    companies: [
      {
        company_id: "same-company-id",
        name: "Airwallex",
        website: "https://airwallex.com",
        qualification_status: "NOT_QUALIFIED",
        summary: {
          matched: 1,
          mismatched: 1,
          unknown: 1,
        },
        criteria: [
          {
            criterion: "target_market",
            subject: "Australia",
            status: "MATCH",
            reason: "Company operates in Australia.",
            evidence: [
              {
                id: "evidence-1",
                claim: "Australian operations",
                evidence_text: "Airwallex is an Australian-founded company.",
                source_url: "https://example.com/source",
                source_title: "Company profile",
                source_type: "company_site",
              },
            ],
          },
          {
            criterion: "keyword",
            subject: "Spring",
            status: "UNKNOWN",
            reason: "No reliable evidence found.",
            evidence: [],
          },
          {
            criterion: "industry",
            subject: "Fin tech",
            status: "MISMATCH",
            reason: "Sources indicate a different industry.",
            evidence: [],
          },
        ],
      },
    ],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("ResearchRunsPage", () => {
  it("renders multiple runs and links each row to its explicit run ID", async () => {
    mockedListRuns.mockResolvedValue([
      run("run-a", "Australian Fintech Java Research"),
      run("run-b", "Australian Payments Research"),
    ]);

    renderWithQuery(<ResearchRunsPage />);

    expect(screen.getByRole("link", { name: "All Runs" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Campaigns" })).toHaveAttribute(
      "href",
      "/research",
    );
    expect(
      await screen.findByText("Australian Fintech Java Research"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: "Open Australian Fintech Java Research",
      }),
    ).toHaveAttribute("href", "/research/run-a");
    expect(
      screen.getByRole("link", { name: "Open Australian Payments Research" }),
    ).toHaveAttribute("href", "/research/run-b");
    expect(screen.getByText("RUNNING")).toBeInTheDocument();
    const deleteButton = screen.getByRole("button", {
      name: "Delete run run-a",
    });
    expect(deleteButton).toHaveTextContent("Delete Run");
    expect(deleteButton).toHaveClass("bg-destructive/10");
    expect(
      deleteButton.querySelector("svg.lucide-trash-2"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Delete run run-b" }),
    ).not.toBeInTheDocument();
  });

  it("shows loading, empty, and request error states", async () => {
    let resolveRuns!: (value: ResearchRunListItem[]) => void;
    mockedListRuns.mockReturnValue(
      new Promise((resolve) => {
        resolveRuns = resolve;
      }),
    );
    const loading = renderWithQuery(<ResearchRunsPage />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading research runs",
    );
    resolveRuns([]);
    expect(await screen.findByText("No research runs yet")).toBeInTheDocument();
    loading.unmount();

    mockedListRuns.mockRejectedValueOnce(new Error("Backend unavailable"));
    renderWithQuery(<ResearchRunsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Backend unavailable",
    );
  });

  it("confirms run deletion and removes the run from the list", async () => {
    mockedListRuns
      .mockResolvedValueOnce([run("run-a", "Research A")])
      .mockResolvedValue([]);
    mockedDeleteRun.mockResolvedValue(undefined);
    renderWithQuery(<ResearchRunsPage />);
    await screen.findByText("Research A");

    expect(
      screen.getByRole("link", { name: "Open Research A" }),
    ).toHaveAttribute("href", "/research/run-a");
    fireEvent.click(screen.getByRole("button", { name: "Delete run run-a" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "Delete Research Run?",
    );
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "persisted evidence and qualification results",
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(mockedDeleteRun).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Delete run run-a" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete Run" }));
    await waitFor(() => expect(mockedDeleteRun).toHaveBeenCalledWith("run-a"));
    await waitFor(() =>
      expect(screen.queryByText("Research A")).not.toBeInTheDocument(),
    );
    expect(mockedListRuns).toHaveBeenCalledTimes(2);
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("keeps the run visible and shows the delete error when deletion fails", async () => {
    mockedListRuns.mockResolvedValue([run("run-a", "Research A")]);
    mockedDeleteRun.mockRejectedValue(new Error("Delete request failed"));
    renderWithQuery(<ResearchRunsPage />);
    const runName = await screen.findByText("Research A");

    fireEvent.click(screen.getByRole("button", { name: "Delete run run-a" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete Run" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Delete request failed",
    );
    expect(runName).toBeInTheDocument();
    expect(mockPush).not.toHaveBeenCalled();
  });
});

describe("ResearchResultsPage", () => {
  it("renders campaign criteria, statuses, status counts, and criterion-linked evidence", async () => {
    mockedGetResults.mockResolvedValue(results("run-a"));
    renderWithQuery(<ResearchResultsPage runId="run-a" />);

    expect(
      await screen.findByRole("heading", {
        name: "Australian Fintech Java Research",
      }),
    ).toBeInTheDocument();
    const breadcrumbs = screen.getByRole("navigation", {
      name: "Research breadcrumbs",
    });
    expect(
      within(breadcrumbs).getByRole("link", { name: "Research" }),
    ).toHaveAttribute("href", "/research");
    expect(
      within(breadcrumbs).getByRole("link", {
        name: "Australian Fintech Java Research",
      }),
    ).toHaveAttribute("href", "/campaigns/campaign-1");
    expect(within(breadcrumbs).getByText("Research Run")).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByText("Run duration").parentElement).toHaveTextContent(
      "10m 0s",
    );
    expect(screen.getAllByText("Australia")).toHaveLength(2);
    expect(screen.getByText("Java")).toBeInTheDocument();
    expect(screen.getByText("≥ 500")).toBeInTheDocument();
    expect(screen.getByText("AI: NOT QUALIFIED")).toBeInTheDocument();
    expect(
      screen.getByText(
        "At least one criterion is contradicted by the available evidence.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Human review/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Accept" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Reject" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/1 matched · 1 mismatched · 1 unknown/),
    ).toBeInTheDocument();
    expect(screen.getByText("MATCH")).toBeInTheDocument();
    expect(screen.getByText("MISMATCH")).toBeInTheDocument();
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
    expect(screen.getByText("Supported by evidence.")).toBeInTheDocument();
    expect(screen.getByText("Contradicted by evidence.")).toBeInTheDocument();
    expect(
      screen.getByText("Not enough evidence to determine."),
    ).toBeInTheDocument();

    const criterionDetails = screen
      .getByText("Australia", { selector: "summary span" })
      .closest("details");
    criterionDetails?.setAttribute("open", "");
    expect(criterionDetails).toHaveTextContent(
      "Airwallex is an Australian-founded company.",
    );
    expect(
      within(criterionDetails as HTMLElement).queryByText("AI assessment"),
    ).not.toBeInTheDocument();
    expect(
      within(criterionDetails as HTMLElement).getByRole("link", {
        name: /Company profile/,
      }),
    ).toHaveAttribute("href", "https://example.com/source");
  });

  it("shows model assessment and validator override separately from the final reason", async () => {
    const base = results("run-a");
    const criterion = base.companies[0].criteria[1];
    criterion.model_assessment = {
      state: "supported",
      reason: "The excerpt describes the company's own automation capability.",
      reason_truncated: true,
    };
    criterion.validation_override = {
      original_state: "supported",
      validated_state: "unknown",
      reason: "No cited Evidence was admissible for this criterion.",
    };
    mockedGetResults.mockResolvedValue(base);
    renderWithQuery(<ResearchResultsPage runId="run-a" />);

    const summary = await screen.findByText("Spring", {
      selector: "summary span",
    });
    const details = summary.closest("details");
    details?.setAttribute("open", "");
    const scope = within(details as HTMLElement);

    expect(scope.getByText("UNKNOWN")).toBeInTheDocument();
    expect(scope.getByText("No reliable evidence found.")).toBeInTheDocument();
    expect(scope.getByText(/AI assessment · supported/)).toBeInTheDocument();
    expect(
      scope.getByText(
        "The excerpt describes the company's own automation capability.",
      ),
    ).toBeInTheDocument();
    expect(
      scope.getByText("Explanation shortened for display."),
    ).toBeInTheDocument();
    expect(scope.getByText("Evidence validation override")).toBeInTheDocument();
    expect(
      scope.getByText(
        /final UNKNOWN result differs from the model’s supported assessment/,
      ),
    ).toBeInTheDocument();
  });

  it("confirms deletion, clears results, and returns to the originating Campaign", async () => {
    mockedGetResults.mockResolvedValue(results("run-a"));
    mockedDeleteRun.mockResolvedValue(undefined);
    const { client } = renderWithQuery(<ResearchResultsPage runId="run-a" />);
    await screen.findByRole("heading", {
      name: "Australian Fintech Java Research",
    });
    client.setQueryData(researchRunResultsQueryKey("run-a"), results("run-a"));
    const invalidate = vi.spyOn(client, "invalidateQueries");

    expect(
      screen.getByRole("button", { name: "Delete run run-a" }),
    ).toHaveClass("bg-destructive/10");
    fireEvent.click(screen.getByRole("button", { name: "Delete run run-a" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "Delete Research Run?",
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(mockedDeleteRun).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Delete run run-a" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete Run" }));
    await waitFor(() => expect(mockedDeleteRun).toHaveBeenCalledWith("run-a"));
    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("/campaigns/campaign-1"),
    );
    expect(
      client.getQueryData(researchRunResultsQueryKey("run-a")),
    ).toBeUndefined();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: researchRunsQueryKey });
  });

  it("falls back to All Runs after deletion when Campaign context is unavailable", async () => {
    const runResults = results("run-a");
    runResults.campaign.id = "";
    mockedGetResults.mockResolvedValue(runResults);
    mockedDeleteRun.mockResolvedValue(undefined);
    renderWithQuery(<ResearchResultsPage runId="run-a" />);
    await screen.findByRole("heading", {
      name: "Australian Fintech Java Research",
    });

    fireEvent.click(screen.getByRole("button", { name: "Delete run run-a" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete Run" }));
    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("/research/runs"),
    );
  });

  it("disables detail deletion while pending and keeps the page on failure", async () => {
    mockedGetResults.mockResolvedValue(results("run-a"));
    let rejectDelete!: (error: Error) => void;
    mockedDeleteRun.mockReturnValue(
      new Promise<void>((_resolve, reject) => {
        rejectDelete = reject;
      }),
    );
    renderWithQuery(<ResearchResultsPage runId="run-a" />);
    await screen.findByRole("heading", {
      name: "Australian Fintech Java Research",
    });

    fireEvent.click(screen.getByRole("button", { name: "Delete run run-a" }));
    const confirm = screen.getByRole("button", { name: "Delete Run" });
    fireEvent.click(confirm);
    await waitFor(() => expect(confirm).toBeDisabled());
    fireEvent.click(confirm);
    expect(mockedDeleteRun).toHaveBeenCalledTimes(1);
    expect(mockPush).not.toHaveBeenCalled();

    rejectDelete(new Error("Delete request failed"));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Delete request failed",
    );
    expect(
      screen.getByRole("heading", { name: "Australian Fintech Java Research" }),
    ).toBeInTheDocument();
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("keeps automatic qualification statuses available as filters", async () => {
    const base = results("run-a");
    mockedGetResults.mockResolvedValue({
      ...base,
      companies: [
        ...base.companies,
        {
          ...base.companies[0],
          company_id: "company-b",
          name: "Afterpay",
          qualification_status: "INSUFFICIENT_EVIDENCE",
        },
        {
          ...base.companies[0],
          company_id: "company-c",
          name: "Tyro",
          qualification_status: "NOT_QUALIFIED",
        },
      ],
    });
    renderWithQuery(<ResearchResultsPage runId="run-a" />);
    await screen.findByText("Airwallex");
    fireEvent.click(
      screen.getByRole("button", { name: /Insufficient evidence/i }),
    );
    expect(screen.getByText("Afterpay")).toBeInTheDocument();
    expect(screen.queryByText("Airwallex")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 1 of 3 companies")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByText("Airwallex")).toBeInTheDocument();
    expect(screen.getByText("Showing 3 of 3 companies")).toBeInTheDocument();
    fireEvent.change(
      screen.getByRole("textbox", { name: "Search companies" }),
      {
        target: { value: "pay" },
      },
    );
    expect(screen.getByText("Afterpay")).toBeInTheDocument();
    expect(screen.queryByText("Airwallex")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 1 of 3 companies")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByText("Airwallex")).toBeInTheDocument();
  });

  it("keeps excerpts visible while marking missing and unsafe source links unavailable", async () => {
    const runResults = results("run-a");
    runResults.companies[0].website = "javascript:alert(1)";
    runResults.companies[0].criteria[0].evidence[0].source_url =
      "data:text/html,unsafe";
    runResults.companies[0].criteria[0].evidence[0].source_title = null;
    mockedGetResults.mockResolvedValue(runResults);
    renderWithQuery(<ResearchResultsPage runId="run-a" />);

    const summary = await screen.findByText("Australia", {
      selector: "summary span",
    });
    const details = summary.closest("details");
    details?.setAttribute("open", "");
    expect(details).toHaveTextContent(
      "Airwallex is an Australian-founded company.",
    );
    expect(
      within(details as HTMLElement).getByText("Source link unavailable"),
    ).toBeInTheDocument();
    expect(
      within(details as HTMLElement).queryByRole("link", {
        name: /Company profile/,
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /javascript:/ }),
    ).not.toBeInTheDocument();
  });

  it("shows provisional running metrics and completion data when available", async () => {
    const active = results("run-a");
    active.research_run.status = "RUNNING";
    active.research_run.completed_at = null;
    mockedGetResults.mockResolvedValue(active);
    renderWithQuery(<ResearchResultsPage runId="run-a" />);

    await screen.findByText(
      "This run is still in progress. Showing the results currently available.",
    );
    expect(
      screen.getByText("Researched so far").parentElement,
    ).toHaveTextContent("1");
    expect(screen.getByText("Run duration").parentElement).toHaveTextContent(
      "In progress",
    );
    expect(screen.queryByText(/Completed/)).not.toBeInTheDocument();
  });

  it("shows queued duration and preserves partial results with failure details", async () => {
    const failed = results("run-a");
    failed.research_run.status = "FAILED";
    failed.research_run.error = "Provider request timed out";
    failed.research_run.completed_at = null;
    mockedGetResults.mockResolvedValue(failed);
    renderWithQuery(<ResearchResultsPage runId="run-a" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Provider request timed out",
    );
    expect(screen.getByText("FAILED")).toBeInTheDocument();
    expect(screen.getByText("Airwallex")).toBeInTheDocument();
    expect(
      screen.getByText("Companies researched before run ended").parentElement,
    ).toHaveTextContent("1");
    cleanup();

    const queued = results("run-a");
    queued.research_run.status = "QUEUED";
    queued.research_run.started_at = "";
    queued.research_run.completed_at = null;
    mockedGetResults.mockResolvedValue(queued);
    renderWithQuery(<ResearchResultsPage runId="run-a" />);
    expect(
      (await screen.findByText("Run duration")).parentElement,
    ).toHaveTextContent("Queued");
    expect(screen.getByRole("status")).toHaveTextContent("This run is queued");
  });

  it("does not render unavailable API metrics as zero", async () => {
    const partial = results("run-a");
    partial.summary.researched = undefined as unknown as number;
    mockedGetResults.mockResolvedValue(partial);
    renderWithQuery(<ResearchResultsPage runId="run-a" />);

    await screen.findByRole("heading", {
      name: "Australian Fintech Java Research",
    });
    expect(
      screen.getByText("Companies researched").parentElement,
    ).toHaveTextContent("Unavailable");
  });

  it("handles missing or invalid timestamps without throwing", async () => {
    const runResults = results("run-a");
    runResults.research_run.started_at = "";
    runResults.research_run.completed_at = "invalid-date";
    mockedGetResults.mockResolvedValue(runResults);
    renderWithQuery(<ResearchResultsPage runId="run-a" />);

    await screen.findByRole("heading", {
      name: "Australian Fintech Java Research",
    });
    expect(
      screen.getByText(
        `Execution started ${formatDate("2026-10-01T00:00:00Z")}`,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Run duration").parentElement).toHaveTextContent(
      "Unavailable",
    );
    expect(screen.getByText("Completed Unavailable")).toBeInTheDocument();
  });

  it("explains Qualified and mixed MATCH/UNKNOWN outcomes", async () => {
    const base = results("run-a");
    const company = base.companies[0];
    const matched = company.criteria.find(
      (criterion) => criterion.status === "MATCH",
    );
    const unknown = company.criteria.find(
      (criterion) => criterion.status === "UNKNOWN",
    );
    expect(matched).toBeDefined();
    expect(unknown).toBeDefined();

    const insufficient = {
      ...company,
      company_id: "company-insufficient",
      name: "Insufficient Co",
      qualification_status: "INSUFFICIENT_EVIDENCE" as const,
      summary: { matched: 8, mismatched: 0, unknown: 2 },
      criteria: [
        ...Array.from({ length: 8 }, (_, index) => ({
          ...matched!,
          subject: `Supported criterion ${index + 1}`,
        })),
        ...Array.from({ length: 2 }, (_, index) => ({
          ...unknown!,
          subject: `Unverified criterion ${index + 1}`,
        })),
      ],
    };
    const qualified = {
      ...company,
      company_id: "company-qualified",
      name: "Qualified Co",
      qualification_status: "QUALIFIED" as const,
      summary: { matched: 10, mismatched: 0, unknown: 0 },
      criteria: Array.from({ length: 10 }, (_, index) => ({
        ...matched!,
        subject: `Supported criterion ${index + 1}`,
      })),
    };
    mockedGetResults.mockResolvedValue({
      ...base,
      companies: [company, insufficient, qualified],
    });

    renderWithQuery(<ResearchResultsPage runId="run-a" />);
    await screen.findByText("Insufficient Co");

    expect(
      screen.getByText(
        "No criterion is contradicted, but at least one cannot be verified.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Evidence supports every configured criterion."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/8 matched · 0 mismatched · 2 unknown/),
    ).toBeInTheDocument();
  });

  it("renders empty and failed runs", async () => {
    mockedGetResults.mockResolvedValueOnce({
      ...results("run-empty"),
      companies: [],
    });
    const empty = renderWithQuery(<ResearchResultsPage runId="run-empty" />);
    expect(
      await screen.findByText("No companies in this run"),
    ).toBeInTheDocument();
    empty.unmount();

    mockedGetResults.mockRejectedValueOnce(
      Object.assign(new Error("Research run not found"), { status: 404 }),
    );
    renderWithQuery(<ResearchResultsPage runId="missing" />);
    expect(
      await screen.findByRole("heading", { name: "Research Run not found" }),
    ).toBeInTheDocument();
  });
});
