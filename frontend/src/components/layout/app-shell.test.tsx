import { render, screen, within } from "@testing-library/react";
import { ThemeProvider } from "next-themes";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

import { AppShell } from "@/components/layout/app-shell";
import { TooltipProvider } from "@/components/ui/tooltip";

describe("AppShell", () => {
  it("renders the product shell and page content", () => {
    render(
      <ThemeProvider attribute="class">
        <TooltipProvider>
          <AppShell>
            <h1>Foundation content</h1>
          </AppShell>
        </TooltipProvider>
      </ThemeProvider>,
    );

    expect(screen.getByText("Virtual Consultancy")).toBeInTheDocument();
    const primaryNav = screen.getByRole("navigation", { name: "Primary" });
    expect(primaryNav).toBeInTheDocument();
    expect(
      within(primaryNav)
        .getAllByRole("listitem")
        .map((item) => item.textContent?.trim()),
    ).toEqual(["Campaigns", "Research", "Explorations", "Leads"]);
    expect(screen.getByRole("link", { name: "Research" })).toHaveAttribute(
      "href",
      "/research",
    );
    expect(screen.getByRole("link", { name: "Campaigns" })).toHaveAttribute(
      "href",
      "/campaigns",
    );
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
  });
});
