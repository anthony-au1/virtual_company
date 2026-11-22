import { expect, test } from "@playwright/test";

test("Save & Execute creates the Run, queues it, and opens its details", async ({
  page,
}) => {
  const sequence: string[] = [];
  await page.route("**/api/backend/api/v1/research-runs", (route) =>
    route.fulfill({
      json: [
        {
          run_id: "source-run",
          status: "COMPLETED",
          created_at: "2026-11-01T10:00:00Z",
          started_at: "2026-11-01T10:00:00Z",
          completed_at: "2026-11-01T10:10:00Z",
          campaign: {
            id: "campaign-1",
            name: "Australian Fintech",
            target_count: 1,
            max_companies_to_research: 5,
          },
          summary: {
            researched: 1,
            qualified: 1,
            not_qualified: 0,
            insufficient_evidence: 0,
          },
        },
      ],
    }),
  );
  await page.route(
    "**/api/backend/api/v1/research-runs/source-run/results",
    (route) =>
      route.fulfill({
        json: {
          research_run: {
            id: "source-run",
            campaign_id: "campaign-1",
            status: "COMPLETED",
            started_at: "2026-11-01T10:00:00Z",
            completed_at: "2026-11-01T10:10:00Z",
            error: null,
            companies_found: 1,
            created_at: "2026-11-01T10:00:00Z",
          },
          campaign: {
            id: "campaign-1",
            name: "Australian Fintech",
            description: null,
            target_count: 1,
            max_companies_to_research: 5,
            criteria: {
              target_market: "Australia",
              industry: null,
              keywords: [],
              company_size: null,
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
              company_id: "company-1",
              name: "Alpine Payments",
              website: "https://alpine.example",
              qualification_status: "QUALIFIED",
              summary: { matched: 1, mismatched: 0, unknown: 0 },
              criteria: [],
            },
          ],
        },
      }),
  );
  await page.route(
    "**/api/backend/api/v1/explorations/exploration-1/runs",
    async (route) => {
      if (route.request().method() === "POST") {
        sequence.push("create");
        expect(route.request().postDataJSON()).toEqual({
          research_run_id: "source-run",
          company_ids: ["company-1"],
        });
        await route.fulfill({
          status: 201,
          json: {
            id: "exploration-run-1",
            exploration_id: "exploration-1",
            research_run_id: "source-run",
            status: "READY",
            started_at: "2026-11-01T10:11:00Z",
            completed_at: null,
            company_ids: ["company-1"],
          },
        });
        return;
      }
      await route.fulfill({
        json: [
          {
            id: "exploration-run-1",
            research_run_id: "source-run",
            status: "QUEUED",
            started_at: "2026-11-01T10:11:00Z",
            completed_at: null,
            campaign_name: "Australian Fintech",
            selected_company_count: 1,
          },
        ],
      });
    },
  );
  await page.route(
    "**/api/backend/api/v1/explorations/exploration-1/runs/exploration-run-1/execute",
    async (route) => {
      sequence.push("execute");
      await route.fulfill({
        status: 202,
        json: { exploration_run_id: "exploration-run-1", status: "QUEUED" },
      });
    },
  );
  await page.route(
    "**/api/backend/api/v1/explorations/exploration-1/runs/exploration-run-1",
    (route) =>
      route.fulfill({
        json: {
          id: "exploration-run-1",
          exploration_id: "exploration-1",
          status: "QUEUED",
          started_at: "2026-11-01T10:11:00Z",
          completed_at: null,
        },
      }),
  );
  await page.route(
    "**/api/backend/api/v1/explorations/exploration-1/runs/exploration-run-1/companies",
    (route) =>
      route.fulfill({
        json: [
          {
            id: "exploration-company-1",
            company_id: "company-1",
            name: "Alpine Payments",
            website: "https://alpine.example",
            domain: "alpine.example",
          },
        ],
      }),
  );
  await page.route(
    "**/api/backend/api/v1/explorations/exploration-1/companies/exploration-company-1/evidence",
    (route) => route.fulfill({ json: [] }),
  );
  await page.route(
    "**/api/backend/api/v1/explorations/exploration-1/obligations",
    (route) => route.fulfill({ json: [] }),
  );

  await page.goto("/explorations/exploration-1/runs/new");
  await page.getByRole("radio", { name: /Australian Fintech/ }).check();
  await page.getByRole("checkbox", { name: "Select Alpine Payments" }).check();
  await page.getByRole("button", { name: "Save & Execute" }).click();

  await expect(page).toHaveURL(
    "/explorations/exploration-1/runs/exploration-run-1",
  );
  await expect(
    page.getByText("This run is queued and waiting to start."),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Source Research Run" }),
  ).toHaveAttribute("href", "/research/source-run");
  expect(sequence).toEqual(["create", "execute"]);
});
