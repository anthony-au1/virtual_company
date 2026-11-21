import { expect, test } from "@playwright/test";

test("shows the Virtual Consultancy application shell", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveURL(/\/research$/);
  await expect(page).toHaveTitle(/Virtual Consultancy/);
  await expect(page.getByText("Virtual Consultancy").first()).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Campaigns" })).toBeVisible();
  await expect(page.getByRole("link", { name: "All Runs" })).toHaveAttribute(
    "href",
    "/research/runs",
  );
  await expect(
    page.getByRole("link", { name: "Research", exact: true }),
  ).toHaveAttribute("aria-current", "page");
});

test("shows the global run list at the All Runs route", async ({ page }) => {
  await page.goto("/research/runs");

  await expect(
    page.getByRole("heading", { name: "Research Runs" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "All Runs" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("redirects the legacy Campaign list route to Research", async ({ page }) => {
  await page.goto("/campaigns");

  await expect(page).toHaveURL(/\/research$/);
  await expect(page.getByRole("heading", { name: "Campaigns" })).toBeVisible();
});

test("keeps the mobile primary navigation usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/research");

  const primaryNav = page.getByRole("navigation", { name: "Primary" });
  await expect(primaryNav).toBeVisible();
  await expect(primaryNav.getByRole("link", { name: "Research" })).toBeVisible();
  await expect(
    primaryNav.getByRole("link", { name: "Explorations" }),
  ).toBeVisible();
  await expect(primaryNav.getByText("Leads")).toHaveAttribute(
    "aria-disabled",
    "true",
  );
});
