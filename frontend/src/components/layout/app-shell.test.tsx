import { cleanup, render, screen, within } from "@testing-library/react";
import { ThemeProvider } from "next-themes";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { pathname } = vi.hoisted(() => ({ pathname: { value: "/" } }));
vi.mock("next/navigation", () => ({
  usePathname: () => pathname.value,
}));

import { AppShell } from "@/components/layout/app-shell";
import { TooltipProvider } from "@/components/ui/tooltip";

describe("AppShell", () => {
  afterEach(cleanup);

  beforeEach(() => {
    pathname.value = "/";
  });

  function renderShell() {
    render(
      <ThemeProvider attribute="class">
        <TooltipProvider>
          <AppShell>
            <h1>Foundation content</h1>
          </AppShell>
        </TooltipProvider>
      </ThemeProvider>,
    );
  }

  it("renders one Research entry, unchanged Exploration and disabled Leads", () => {
    renderShell();
    expect(screen.getByText("Virtual Consultancy")).toBeInTheDocument();
    const primaryNav = screen.getByRole("navigation", { name: "Primary" });
    expect(primaryNav).toBeInTheDocument();
    expect(
      within(primaryNav)
        .getAllByRole("listitem")
        .map((item) => item.textContent?.trim()),
    ).toEqual(["Research", "Explorations", "Leads"]);
    expect(
      within(primaryNav).getByRole("link", { name: "Research" }),
    ).toHaveAttribute(
      "href",
      "/research",
    );
    expect(
      screen.queryByRole("link", { name: "Campaigns" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Explorations" })).toHaveAttribute(
      "href",
      "/explorations",
    );
    expect(
      screen.getByRole("heading", { name: "Foundation content" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Toggle color theme" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Leads")).toHaveAttribute("aria-disabled", "true");
  });

  it.each([
    "/research",
    "/research/runs",
    "/research/run-123",
    "/campaigns/new",
    "/campaigns/campaign-123",
    "/campaigns/campaign-123/edit",
  ])("marks Research active at %s without marking Exploration active", (path) => {
    pathname.value = path;
    renderShell();

    expect(
      within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
        "link",
        { name: "Research" },
      ),
    ).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
        "link",
        { name: "Explorations" },
      ),
    ).not.toHaveAttribute("aria-current", "page");
  });
});
