import { render, screen } from "@testing-library/react";
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
    expect(
      screen.getByRole("navigation", { name: "Primary" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Research" })).toHaveAttribute(
      "href",
      "/research",
    );
    expect(screen.getByText("Campaigns")).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(
      screen.getByRole("heading", { name: "Foundation content" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Toggle color theme" }),
    ).toBeInTheDocument();
  });
});
