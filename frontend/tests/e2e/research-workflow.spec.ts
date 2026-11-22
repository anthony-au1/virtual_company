import { expect, test, type Page } from "@playwright/test";
import type { ResearchRunListItem } from "@/features/research/api/research";

const campaign = {
  id: "campaign-1",
  name: "Australian Fintech Research",
  description: "Find Australian fintech companies.",
  target_market: "Australia",
  industry: "Financial technology",
  keywords: ["payments"],
  company_size: { min: 50, max: 5000 },
  target_count: 5,
  max_companies_to_research: 10,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  sealed_at: "2026-10-01T00:00:00Z",
};

const run: ResearchRunListItem = {
  run_id: "run-1",
  status: "COMPLETED",
  created_at: "2026-10-01T00:00:00Z",
  started_at: "2026-10-01T00:00:00Z",
  completed_at: "2026-10-01T00:10:00Z",
  campaign: {
    id: campaign.id,
    name: campaign.name,
    target_count: campaign.target_count,
    max_companies_to_research: campaign.max_companies_to_research,
  },
  summary: {
    researched: 2,
    qualified: 1,
    not_qualified: 1,
    insufficient_evidence: 0,
  },
};

const runResults = {
  research_run: {
    id: run.run_id,
    campaign_id: campaign.id,
    status: "COMPLETED",
    started_at: run.started_at,
    completed_at: run.completed_at,
    error: null,
    companies_found: 2,
    created_at: run.created_at,
  },
  campaign: {
    id: campaign.id,
    name: campaign.name,
    description: campaign.description,
    target_count: campaign.target_count,
    max_companies_to_research: campaign.max_companies_to_research,
    criteria: {
      target_market: campaign.target_market,
      industry: campaign.industry,
      keywords: campaign.keywords,
      company_size: campaign.company_size,
    },
  },
  summary: {
    researched: 2,
    qualified: 1,
    not_qualified: 1,
    insufficient_evidence: 0,
  },
  companies: [
    {
      company_id: "company-1",
      name: "Alpine Payments",
      website: "https://alpine.example",
      qualification_status: "QUALIFIED",
      summary: { matched: 2, mismatched: 0, unknown: 0 },
      criteria: [
        {
          criterion: "target_market",
          subject: "Australia",
          status: "MATCH",
          reason: "The company operates in Australia.",
          evidence: [
            {
              id: "evidence-1",
              claim: "Australian operations",
              evidence_text: "Alpine Payments operates from Sydney, Australia.",
              source_url: "https://source.example/about",
              source_title: "Company profile",
              source_type: "company_site",
            },
          ],
        },
      ],
    },
    {
      company_id: "company-2",
      name: "Harbour Systems",
      website: null,
      qualification_status: "NOT_QUALIFIED",
      summary: { matched: 0, mismatched: 1, unknown: 1 },
      criteria: [],
    },
    {
      company_id: "company-3",
      name: "Southern Ledger",
      website: null,
      qualification_status: "INSUFFICIENT_EVIDENCE",
      summary: { matched: 1, mismatched: 0, unknown: 1 },
      criteria: [],
    },
  ],
};

async function mockRunList(page: Page, item = run) {
  await page.route("**/api/backend/api/v1/research-runs", (route) =>
    route.fulfill({ json: [item] }),
  );
}

async function mockCampaignDetail(page: Page, value = campaign) {
  await page.route("**/api/backend/api/v1/campaigns/campaign-1", (route) =>
    route.fulfill({ json: value }),
  );
}

test("Research landing switches between Campaigns and All Runs", async ({
  page,
}) => {
  await page.route("**/api/backend/api/v1/campaigns", (route) =>
    route.fulfill({ json: [campaign] }),
  );
  await mockRunList(page);
  await page.goto("/research");

  await expect(page.getByRole("heading", { name: "Campaigns" })).toBeVisible();
  await expect(
    page.getByRole("link", { name: campaign.name, exact: true }),
  ).toHaveAttribute("href", `/campaigns/${campaign.id}`);
  await page.getByRole("link", { name: "All Runs" }).click();
  await expect(page).toHaveURL(/\/research\/runs$/);
  await expect(
    page.getByRole("heading", { name: "Research Runs" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "All Runs" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("Campaign workspace shows sealed criteria and links to an active Run", async ({
  page,
}) => {
  const activeRun = { ...run, status: "RUNNING", completed_at: null };
  await mockCampaignDetail(page);
  await mockRunList(page, activeRun);
  await page.goto(`/campaigns/${campaign.id}`);

  await expect(
    page.getByText("Research criteria are locked after the first execution."),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Open active Run" }),
  ).toHaveAttribute("href", `/research/${run.run_id}`);
  await expect(
    page.getByRole("button", { name: "Research in progress" }),
  ).toBeDisabled();
  await expect(page.getByRole("link", { name: "Edit Campaign" })).toHaveCount(
    0,
  );
});

test("Run Results preserve Campaign context, filtering, evidence disclosure, and mobile layout", async ({
  page,
}) => {
  await page.route(
    "**/api/backend/api/v1/research-runs/run-1/results",
    (route) => route.fulfill({ json: runResults }),
  );
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/research/${run.run_id}`);

  const breadcrumbs = page.getByRole("navigation", {
    name: "Research breadcrumbs",
  });
  await expect(
    breadcrumbs.getByRole("link", { name: "Research", exact: true }),
  ).toHaveAttribute("href", "/research");
  await expect(
    breadcrumbs.getByRole("link", { name: campaign.name, exact: true }),
  ).toHaveAttribute("href", `/campaigns/${campaign.id}`);
  await expect(breadcrumbs.getByText("Research Run")).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(page.getByText("Run duration").locator("..")).toContainText(
    "10m 0s",
  );

  await page.getByRole("button", { name: "Insufficient evidence" }).click();
  await expect(
    page.getByRole("heading", { name: "Southern Ledger" }),
  ).toBeVisible();
  await expect(page.getByText("Showing 1 of 3 companies")).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();

  await page.getByText("Australia", { exact: true }).last().click();
  await expect(
    page.getByText("Alpine Payments operates from Sydney, Australia."),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Company profile" }),
  ).toHaveAttribute("href", "https://source.example/about");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(breadcrumbs).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Alpine Payments" }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});

test("deleting a Run returns to its Campaign workspace", async ({ page }) => {
  await page.route(
    "**/api/backend/api/v1/research-runs/run-1/results",
    (route) => route.fulfill({ json: runResults }),
  );
  await mockCampaignDetail(page);
  await mockRunList(page);
  await page.route("**/api/backend/api/v1/research-runs/run-1", (route) =>
    route.fulfill({ status: 204 }),
  );
  await page.goto(`/research/${run.run_id}`);

  await page.getByRole("button", { name: "Delete run run-1" }).click();
  await page.getByRole("button", { name: "Delete Run", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/campaigns/${campaign.id}$`));
  await expect(
    page.getByRole("heading", { name: campaign.name }),
  ).toBeVisible();
});
