import { expect, test } from "@playwright/test";

test("shows the Virtual Consultancy application shell", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveTitle(/Virtual Consultancy/);
  await expect(page.getByText("Virtual Consultancy").first()).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await expect(page.getByText("Foundation ready")).toBeVisible();
});
