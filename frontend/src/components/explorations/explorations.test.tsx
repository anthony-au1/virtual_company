import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ExplorationDetailsPage } from "@/components/explorations/exploration-details-page";
import { ExplorationFormPage } from "@/components/explorations/exploration-form-page";
import { ExplorationsPage } from "@/components/explorations/explorations-page";
import type {
  Exploration,
  ExplorationObligation,
} from "@/lib/api/explorations";
import { ApiError } from "@/lib/api/client";
import { explorationsQueryKey } from "@/lib/queries/query-keys";

const { mockPush } = vi.hoisted(() => ({ mockPush: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/lib/api/explorations", () => ({
  listExplorations: vi.fn(),
  getExploration: vi.fn(),
  createExploration: vi.fn(),
  updateExploration: vi.fn(),
  deleteExploration: vi.fn(),
  listExplorationObligations: vi.fn(),
}));

import {
  createExploration,
  deleteExploration,
  getExploration,
  listExplorationObligations,
  listExplorations,
  updateExploration,
} from "@/lib/api/explorations";

const mockList = vi.mocked(listExplorations);
const mockGet = vi.mocked(getExploration);
const mockCreate = vi.mocked(createExploration);
const mockUpdate = vi.mocked(updateExploration);
const mockDelete = vi.mocked(deleteExploration);
const mockObligations = vi.mocked(listExplorationObligations);

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return {
    client,
    ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>),
  };
}

function exploration(
  id = "exploration-1",
  context = "Assess market entry for a payments consultancy",
  max = 10,
): Exploration {
  return {
    id,
    business_context: context,
    max_obligations: max,
    status: "DRAFT",
    created_at: "2026-10-05T00:00:00Z",
    updated_at: "2026-10-06T00:00:00Z",
  };
}

function obligation(description: string): ExplorationObligation {
  return { description, created_at: "2026-10-06T00:00:00Z" };
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => cleanup());

describe("ExplorationsPage", () => {
  it("lists Explorations and links to their detail and create routes", async () => {
    mockList.mockResolvedValue([
      exploration("e1", "Find payment companies in Australia"),
      exploration("e2", "Understand regulation in New Zealand", 4),
    ]);
    renderWithQuery(<ExplorationsPage />);

    expect(
      await screen.findByText("Find payment companies in Australia"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Understand regulation in New Zealand"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "New Exploration" }),
    ).toHaveAttribute("href", "/explorations/new");
    expect(
      screen.getByRole("link", {
        name: "Open Exploration Find payment companies in Australia",
      }),
    ).toHaveAttribute("href", "/explorations/e1");
    expect(
      within(
        screen.getByRole("row", { name: /Find payment companies/ }),
      ).getByRole("button", { name: "Delete Exploration" }),
    ).toBeInTheDocument();
    expect(
      within(
        screen.getByRole("row", { name: /Understand regulation/ }),
      ).getByRole("link", {
        name: "Open Exploration Understand regulation in New Zealand",
      }),
    ).toHaveAttribute("href", "/explorations/e2");
    expect(
      within(
        screen.getByRole("row", { name: /Understand regulation/ }),
      ).getByRole("button", { name: "Delete Exploration" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("DRAFT")).toHaveLength(2);
  });

  it("confirms row deletion, prevents duplicate submits, and refreshes the list", async () => {
    const first = exploration("e1", "Find payment companies in Australia");
    const second = exploration("e2", "Understand regulation in New Zealand", 4);
    mockList
      .mockResolvedValueOnce([first, second])
      .mockResolvedValueOnce([second]);
    let resolveDelete!: () => void;
    mockDelete.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveDelete = resolve;
      }),
    );
    const { client } = renderWithQuery(<ExplorationsPage />);

    const row = await screen.findByRole("row", {
      name: /Find payment companies in Australia/,
    });
    expect(
      within(row).getByRole("link", {
        name: "Open Exploration Find payment companies in Australia",
      }),
    ).toHaveAttribute("href", "/explorations/e1");
    fireEvent.click(
      within(row).getByRole("button", { name: "Delete Exploration" }),
    );
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "permanently delete this Exploration and its generated research obligations",
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(mockDelete).not.toHaveBeenCalled();

    fireEvent.click(
      within(row).getByRole("button", { name: "Delete Exploration" }),
    );
    const confirm = within(screen.getByRole("alertdialog")).getByRole(
      "button",
      {
        name: "Delete Exploration",
      },
    );
    fireEvent.click(confirm);
    await waitFor(() => expect(confirm).toBeDisabled());
    fireEvent.click(confirm);
    expect(mockDelete).toHaveBeenCalledTimes(1);
    expect(mockDelete).toHaveBeenCalledWith("e1");
    expect(mockPush).not.toHaveBeenCalled();
    expect(client.getQueryData(explorationsQueryKey)).toHaveLength(2);

    resolveDelete();
    await waitFor(() =>
      expect(
        screen.queryByRole("row", { name: /Find payment companies/ }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("row", { name: /Understand regulation/ }),
    ).toBeInTheDocument();
    expect(mockList).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("keeps the row and shows the lifecycle message when deletion returns 409", async () => {
    mockList.mockResolvedValue([
      exploration("e1", "Find payment companies in Australia"),
    ]);
    mockDelete.mockRejectedValue(
      new ApiError("conflict", 409, { detail: "internal lifecycle detail" }),
    );
    renderWithQuery(<ExplorationsPage />);

    const row = await screen.findByRole("row", {
      name: /Find payment companies in Australia/,
    });
    fireEvent.click(
      within(row).getByRole("button", { name: "Delete Exploration" }),
    );
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Delete Exploration",
      }),
    );

    expect(
      await screen.findByText(
        "This Exploration cannot be deleted because it has already been run.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("row", { name: /Find payment companies/ }),
    ).toBeInTheDocument();
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("keeps the row and shows a safe error for other delete failures", async () => {
    mockList.mockResolvedValue([
      exploration("e1", "Find payment companies in Australia"),
    ]);
    mockDelete.mockRejectedValue(new ApiError("internal detail", 500, {}));
    renderWithQuery(<ExplorationsPage />);

    const row = await screen.findByRole("row", {
      name: /Find payment companies in Australia/,
    });
    fireEvent.click(
      within(row).getByRole("button", { name: "Delete Exploration" }),
    );
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Delete Exploration",
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Exploration could not be deleted. Please try again.",
    );
    expect(
      screen.getByRole("row", { name: /Find payment companies/ }),
    ).toBeInTheDocument();
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("shows loading, empty, and error states", async () => {
    let resolve!: (items: Exploration[]) => void;
    mockList.mockReturnValue(new Promise((done) => (resolve = done)));
    const view = renderWithQuery(<ExplorationsPage />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading Explorations",
    );
    resolve([]);
    expect(await screen.findByText("No Explorations yet")).toBeInTheDocument();
    view.unmount();

    mockList.mockRejectedValueOnce(new Error("Could not connect"));
    renderWithQuery(<ExplorationsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not connect",
    );
  });
});

describe("ExplorationFormPage create", () => {
  it("shows the fields and defaults maximum obligations to 10", () => {
    renderWithQuery(<ExplorationFormPage />);
    expect(screen.getByLabelText("Business context").tagName).toBe("TEXTAREA");
    expect(screen.getByText(/business goal or question/)).toBeInTheDocument();
    expect(
      screen.getByText(/broader question their investigation can help answer/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Maximum obligations")).toHaveValue(10);
    expect(
      screen.getByText(/This is a ceiling, not an exact count/),
    ).toBeInTheDocument();
  });

  it("validates the obligation range and submits the payload", async () => {
    mockCreate.mockResolvedValue(exploration("created"));
    renderWithQuery(<ExplorationFormPage />);
    fireEvent.change(screen.getByLabelText("Maximum obligations"), {
      target: { value: "0" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Exploration" }));
    expect(
      await screen.findByText("Maximum obligations must be at least 1."),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Maximum obligations"), {
      target: { value: "21" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Exploration" }));
    expect(
      await screen.findByText("Maximum obligations cannot exceed 20."),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Maximum obligations"), {
      target: { value: "20" },
    });
    fireEvent.change(screen.getByLabelText("Business context"), {
      target: { value: "  Investigate the proposed market entry.  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Exploration" }));

    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith({
        business_context: "Investigate the proposed market entry.",
        max_obligations: 20,
      }),
    );
    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("/explorations/created"),
    );
  });

  it("disables submit while creation and synchronous generation are pending", async () => {
    let resolve!: (value: Exploration) => void;
    mockCreate.mockReturnValue(new Promise((done) => (resolve = done)));
    renderWithQuery(<ExplorationFormPage />);
    fireEvent.change(screen.getByLabelText("Business context"), {
      target: { value: "Investigate market entry" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Exploration" }));
    expect(
      await screen.findByRole("button", {
        name: "Creating Exploration and generating obligations…",
      }),
    ).toBeDisabled();
    resolve(exploration("created"));
  });

  it("shows a safe generation failure for HTTP 503", async () => {
    mockCreate.mockRejectedValue(
      new ApiError("provider technical detail", 503, {
        detail: "Obligation generation failed",
      }),
    );
    renderWithQuery(<ExplorationFormPage />);
    fireEvent.change(screen.getByLabelText("Business context"), {
      target: { value: "Investigate market entry" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Exploration" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "We couldn't generate research obligations for this Exploration. Please try again.",
    );
    expect(alert).not.toHaveTextContent("provider technical detail");
    expect(mockPush).not.toHaveBeenCalled();
  });
});

describe("ExplorationDetailsPage", () => {
  it("shows Exploration information and read-only generated obligations", async () => {
    mockGet.mockResolvedValue(exploration());
    mockObligations.mockResolvedValue([
      obligation("Determine which licences apply."),
      obligation("Assess market demand."),
    ]);
    renderWithQuery(<ExplorationDetailsPage explorationId="exploration-1" />);

    expect(
      await screen.findByRole("heading", {
        name: "Assess market entry for a payments consultancy",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Maximum obligations").nextSibling,
    ).toHaveTextContent("10");
    expect(
      screen.getByText("Determine which licences apply."),
    ).toBeInTheDocument();
    expect(screen.getByText("Assess market demand.")).toBeInTheDocument();
    expect(screen.getByText("2 generated")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Edit Exploration" }),
    ).toHaveAttribute("href", "/explorations/exploration-1/edit");
    expect(
      screen.queryByRole("button", { name: /add obligation/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /edit obligation/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /delete obligation/i }),
    ).not.toBeInTheDocument();
  });

  it("treats zero generated obligations as a valid empty state", async () => {
    mockGet.mockResolvedValue(exploration());
    mockObligations.mockResolvedValue([]);
    renderWithQuery(<ExplorationDetailsPage explorationId="exploration-1" />);

    expect(
      await screen.findByText(
        /This is valid when investigating selected companies cannot meaningfully support the goal/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("0 generated")).toBeInTheDocument();
  });

  it("requires confirmation and navigates only after successful deletion", async () => {
    mockGet.mockResolvedValue(exploration());
    mockObligations.mockResolvedValue([]);
    const { client } = renderWithQuery(
      <ExplorationDetailsPage explorationId="exploration-1" />,
    );
    mockDelete.mockResolvedValue(undefined);

    await screen.findByRole("heading", {
      name: "Assess market entry for a payments consultancy",
    });
    fireEvent.click(screen.getByRole("button", { name: "Delete Exploration" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "permanently delete this Exploration and its generated research obligations",
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(mockDelete).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Delete Exploration" }));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Delete Exploration",
      }),
    );
    await waitFor(() =>
      expect(mockDelete).toHaveBeenCalledWith("exploration-1"),
    );
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/explorations"));
    expect(client.getQueryData(["explorations"])).toBeUndefined();
  });

  it("keeps the detail page and shows the lifecycle conflict on 409", async () => {
    mockGet.mockResolvedValue(exploration());
    mockObligations.mockResolvedValue([]);
    mockDelete.mockRejectedValue(
      new ApiError("conflict", 409, { detail: "internal lifecycle detail" }),
    );
    renderWithQuery(<ExplorationDetailsPage explorationId="exploration-1" />);

    await screen.findByRole("heading", {
      name: "Assess market entry for a payments consultancy",
    });
    fireEvent.click(screen.getByRole("button", { name: "Delete Exploration" }));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Delete Exploration",
      }),
    );
    expect(
      await screen.findByText(
        "This Exploration cannot be deleted because it has already been run.",
      ),
    ).toBeInTheDocument();
    expect(mockPush).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("disables confirmation while pending and refreshes the list after success", async () => {
    mockGet.mockResolvedValue(exploration());
    mockObligations.mockResolvedValue([]);
    let resolveDelete!: () => void;
    mockDelete.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveDelete = resolve;
      }),
    );
    const { client } = renderWithQuery(
      <ExplorationDetailsPage explorationId="exploration-1" />,
    );
    client.setQueryData(["explorations"], [exploration()]);
    const invalidate = vi.spyOn(client, "invalidateQueries");

    await screen.findByRole("heading", {
      name: "Assess market entry for a payments consultancy",
    });
    fireEvent.click(screen.getByRole("button", { name: "Delete Exploration" }));
    const confirm = within(screen.getByRole("alertdialog")).getByRole(
      "button",
      {
        name: "Delete Exploration",
      },
    );
    fireEvent.click(confirm);
    await waitFor(() => expect(confirm).toBeDisabled());
    expect(mockPush).not.toHaveBeenCalled();
    expect(client.getQueryData(["explorations"])).toHaveLength(1);

    resolveDelete();
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/explorations"));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["explorations"] });
  });

  it("keeps detail visible and reports a safe message for other delete failures", async () => {
    mockGet.mockResolvedValue(exploration());
    mockObligations.mockResolvedValue([]);
    mockDelete.mockRejectedValue(new ApiError("failed", 500, {}));
    renderWithQuery(<ExplorationDetailsPage explorationId="exploration-1" />);

    await screen.findByRole("heading", {
      name: "Assess market entry for a payments consultancy",
    });
    fireEvent.click(screen.getByRole("button", { name: "Delete Exploration" }));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Delete Exploration",
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Exploration could not be deleted. Please try again.",
    );
    expect(mockPush).not.toHaveBeenCalled();
  });
});

describe("ExplorationFormPage update", () => {
  it("PATCHes changed inputs and invalidates obligations after success", async () => {
    mockGet.mockResolvedValue(exploration());
    mockUpdate.mockResolvedValue(
      exploration("exploration-1", "Updated context", 12),
    );
    const { client } = renderWithQuery(
      <ExplorationFormPage explorationId="exploration-1" />,
    );
    const obligationsKey = [
      "exploration-obligations",
      "exploration-1",
    ] as const;
    client.setQueryData(obligationsKey, [obligation("Old question")]);

    expect(await screen.findByLabelText("Business context")).toHaveValue(
      "Assess market entry for a payments consultancy",
    );
    fireEvent.change(screen.getByLabelText("Business context"), {
      target: { value: "Updated context" },
    });
    fireEvent.change(screen.getByLabelText("Maximum obligations"), {
      target: { value: "12" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith("exploration-1", {
        business_context: "Updated context",
        max_obligations: 12,
      }),
    );
    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("/explorations/exploration-1"),
    );
    expect(client.getQueryState(obligationsKey)?.isInvalidated).toBe(true);
  });

  it("handles HTTP 409 without losing current form values", async () => {
    mockGet.mockResolvedValue(exploration());
    mockUpdate.mockRejectedValue(
      new ApiError("conflict", 409, { detail: "conflict" }),
    );
    renderWithQuery(<ExplorationFormPage explorationId="exploration-1" />);

    const context = await screen.findByLabelText("Business context");
    fireEvent.change(context, { target: { value: "Attempted change" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This Exploration can no longer be changed because it has already been run.",
    );
    expect(context).toHaveValue("Attempted change");
  });

  it("keeps prior form values and shows safe error when regeneration fails", async () => {
    mockGet.mockResolvedValue(exploration());
    mockUpdate.mockRejectedValue(
      new ApiError("provider details", 503, {
        detail: "Obligation generation failed",
      }),
    );
    renderWithQuery(<ExplorationFormPage explorationId="exploration-1" />);

    const context = await screen.findByLabelText("Business context");
    fireEvent.change(context, { target: { value: "New context" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "We couldn't generate research obligations",
    );
    expect(alert).not.toHaveTextContent("provider details");
    expect(context).toHaveValue("New context");
    expect(mockPush).not.toHaveBeenCalled();
  });
});
