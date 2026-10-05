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

vi.mock("@/lib/api/research", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/research")>();
  return {
    ...actual,
    listResearchRuns: vi.fn(),
    getResearchRunResults: vi.fn(),
    updateCompanyReview: vi.fn(),
  };
});

import {
  getResearchRunResults,
  listResearchRuns,
  updateCompanyReview,
} from "@/lib/api/research";

const mockedListRuns = vi.mocked(listResearchRuns);
const mockedGetResults = vi.mocked(getResearchRunResults);
const mockedUpdateReview = vi.mocked(updateCompanyReview);

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
}

function run(id: string, name: string): ResearchRunListItem {
  return {
    run_id: id,
    status: id === "run-b" ? "RUNNING" : "COMPLETED",
    created_at: "2026-10-01T00:00:00Z",
    started_at: "2026-10-01T00:00:00Z",
    completed_at: null,
    campaign: { id: `campaign-${id}`, name, target_count: 5 },
    summary: {
      researched: 1,
      qualified: 1,
      not_qualified: 0,
      insufficient_evidence: 0,
      accepted: 0,
      rejected: 0,
      unreviewed: 1,
    },
  };
}

function results(
  runId: string,
  reviewStatus: "UNREVIEWED" | "ACCEPTED" | "REJECTED" = "UNREVIEWED",
): ResearchResults {
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
      criteria: {
        target_market: { value: "Australia", requirement: "required" },
        industry: { value: "Fin tech", requirement: "required" },
        technologies: { required: ["Java", "Spring"], preferred: ["Kafka"] },
        company_size: {
          min: { value: 500, requirement: "preferred" },
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
        review_status: reviewStatus,
        summary: {
          required: { matched: 2, mismatched: 0, unknown: 0 },
          preferred: { matched: 0, mismatched: 0, unknown: 2 },
        },
        criteria: [
          {
            criterion: "target_market",
            subject: "Australia",
            requirement: "required",
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
            criterion: "technology",
            subject: "Spring",
            requirement: "required",
            status: "UNKNOWN",
            reason: "No reliable evidence found.",
            evidence: [],
          },
          {
            criterion: "industry",
            subject: "Fin tech",
            requirement: "required",
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
    expect(screen.getByText("Human review: UNREVIEWED")).toBeInTheDocument();
    expect(
      screen.getByText(/2 matched · 0 mismatched · 0 unknown/),
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

  it("supports accept, reject, and reset using run and company IDs, then updates review state", async () => {
    mockedGetResults.mockResolvedValue(results("run-a"));
    mockedUpdateReview.mockImplementation(
      async (_runId, companyId, status) => ({
        company_id: companyId,
        review_status: status,
      }),
    );
    renderWithQuery(<ResearchResultsPage runId="run-a" />);

    const company = await screen.findByRole("article");
    fireEvent.click(within(company).getByRole("button", { name: "Accept" }));
    await waitFor(() =>
      expect(
        within(company).getByText("Human review: ACCEPTED"),
      ).toBeInTheDocument(),
    );
    fireEvent.click(within(company).getByRole("button", { name: "Reject" }));
    await waitFor(() =>
      expect(
        within(company).getByText("Human review: REJECTED"),
      ).toBeInTheDocument(),
    );
    fireEvent.click(within(company).getByRole("button", { name: "Reset" }));
    await waitFor(() =>
      expect(
        within(company).getByText("Human review: UNREVIEWED"),
      ).toBeInTheDocument(),
    );

    expect(mockedUpdateReview.mock.calls).toEqual([
      ["run-a", "same-company-id", "ACCEPTED"],
      ["run-a", "same-company-id", "REJECTED"],
      ["run-a", "same-company-id", "UNREVIEWED"],
    ]);
  });

  it("keeps identical company IDs isolated between run result caches", async () => {
    mockedGetResults.mockImplementation(async (runId) =>
      results(runId, runId === "run-a" ? "ACCEPTED" : "REJECTED"),
    );
    renderWithQuery(
      <>
        <ResearchResultsPage runId="run-a" />
        <ResearchResultsPage runId="run-b" />
      </>,
    );
    await screen.findAllByText("Airwallex");

    expect(screen.getAllByText("Human review: ACCEPTED")).toHaveLength(1);
    expect(screen.getAllByText("Human review: REJECTED")).toHaveLength(1);
    expect(mockedGetResults).toHaveBeenCalledWith("run-a");
    expect(mockedGetResults).toHaveBeenCalledWith("run-b");
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
