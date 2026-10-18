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

import { ResearchResultsPage } from "@/components/research/research-results-page";
import { ResearchRunsPage } from "@/components/research/research-runs-page";
import type { ResearchResults, ResearchRunListItem } from "@/lib/api/research";
import {
  researchRunResultsQueryKey,
  researchRunsQueryKey,
} from "@/lib/queries/query-keys";

const { mockPush } = vi.hoisted(() => ({ mockPush: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/lib/api/research", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/research")>();
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
} from "@/lib/api/research";

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
      qualified: 1,
      not_qualified: 0,
      insufficient_evidence: 0,
    },
    companies: [
      {
        company_id: "same-company-id",
        name: "Airwallex",
        website: "https://airwallex.com",
        qualification_status: "QUALIFIED",
        summary: {
          matched: 2,
          mismatched: 0,
          unknown: 2,
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
    expect(screen.getAllByText("Australia")).toHaveLength(2);
    expect(screen.getByText("Java")).toBeInTheDocument();
    expect(screen.getByText("≥ 500")).toBeInTheDocument();
    expect(screen.getByText("AI: QUALIFIED")).toBeInTheDocument();
    expect(screen.queryByText(/Human review/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Accept" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Reject" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/2 matched · 0 mismatched · 2 unknown/),
    ).toBeInTheDocument();
    expect(screen.getByText("MATCH")).toBeInTheDocument();
    expect(screen.getByText("MISMATCH")).toBeInTheDocument();
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();

    const criterionDetails = screen
      .getByText("Australia", { selector: "summary span" })
      .closest("details");
    criterionDetails?.setAttribute("open", "");
    expect(criterionDetails).toHaveTextContent(
      "Airwallex is an Australian-founded company.",
    );
    expect(
      within(criterionDetails as HTMLElement).getByRole("link", {
        name: /Company profile/,
      }),
    ).toHaveAttribute("href", "https://example.com/source");
  });

  it("confirms deletion, clears results, and navigates back to Research Runs", async () => {
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
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/research"));
    expect(
      client.getQueryData(researchRunResultsQueryKey("run-a")),
    ).toBeUndefined();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: researchRunsQueryKey });
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
