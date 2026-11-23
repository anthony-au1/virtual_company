# Frontend Architecture and Journeys

## Stack and instructions

The frontend uses Next.js 16.3.8 App Router, React 19.3.0, TypeScript,
Tailwind CSS 4.3.3, and TanStack Query 5.104.x (as pinned/ranged in
`frontend/package.json`), plus the component libraries/configuration listed
there. Preserve [`frontend/AGENTS.md`](../frontend/AGENTS.md):
this installed Next version may differ from general training knowledge, so
consult the installed framework guide before frontend code changes.
`frontend/CLAUDE.md` aliases `@AGENTS.md`.

## Routes and feature structure

App Router files in `frontend/src/app/` are thin route entry points:

| Route | Purpose |
|---|---|
| `/` | Application home. |
| `/campaigns` | Research campaign list. |
| `/campaigns/new` | Campaign creation. |
| `/campaigns/[campaignId]` | Campaign details and Research Run history/start. |
| `/research` | Research navigation/section. |
| `/research/runs` | Research Run listing. |
| `/research/[runId]` | Research results. |
| `/explorations` | Exploration definitions and run history. |
| `/explorations/new` | New Exploration definition. |
| `/explorations/[explorationId]` | Exploration definition and run history. |
| `/explorations/[explorationId]/edit` | Edit an Exploration definition. |
| `/explorations/[explorationId]/runs/new` | Select a ResearchRun and companies for a new run. |
| `/explorations/[explorationId]/runs/[runId]` | Run status and results. |

Feature-owned code is in `frontend/src/features/research/` and
`frontend/src/features/exploration/`, each with API clients, query keys, and
components. Shared shell/providers and UI primitives are under
`frontend/src/components/`; transport and environment parsing are under
`frontend/src/lib/`.

## API communication and state

Browser requests go through the same-origin `/api/backend` proxy configured by
the frontend; server-only `BACKEND_API_URL` points to FastAPI. Shared
`apiFetch<T>` handles transport, while feature API modules map typed response
shapes. Backend Pydantic DTO/OpenAPI contracts are the source of truth; avoid
manually diverging large result types. TanStack Query stores result/status
queries, polls active runs, and invalidates relevant state after mutations.
Transient form inputs remain component state where appropriate.

## Research journey

Campaign pages create/edit configuration and start a run. Campaign/run lists
refresh while any run is nonterminal. Research result page retrieves a run's
result response, presents qualification and criterion details with evidence
references, and exposes status/error/empty states. See
`frontend/src/features/research/components/campaigns/`, `runs/`, `results/`,
`frontend/src/features/research/api/`, and backend
`src/virtual_company/api/campaigns.py` and `research_runs.py`.

## Exploration journey and result presentation

Exploration pages create/edit named definitions and show runs. New Run UI
selects a ResearchRun and its eligible companies, saves the run READY, and can
call execute for Save & Execute. Run details poll status at a 2.5-second
interval while nonterminal (see
`exploration-run-details-page.tsx`), present Evidence/Facts/Hypotheses tabs,
and preserve nested supporting Evidence/Facts under their parent rows.

The result component applies client-side pagination with a page size of 50
top-level Evidence, Facts, or Hypotheses. Each tab has independent page state;
company changes reset it. Nested support records remain nested and are not
counted as independent top-level page items. Check current component tests when
changing these behaviors. Result arrays are fetched as API responses and then
paginated in the browser; this is not server-side pagination.

Status/query loading, initial errors, execution handoff uncertainty, terminal
status, and manual refresh are handled in the detail component. Results can be
empty for a completed run because graph branches may skip unavailable search,
fetch, or extraction outputs. Consult the component rather than assuming an
empty result is necessarily a transport failure.

## Testing

- Vitest unit/component tests live alongside source as `*.test.ts`/`*.test.tsx`
  under `frontend/src/`.
- Playwright E2E tests are in `frontend/tests/e2e/` and configuration is in the
  frontend root.
- Route tests include `frontend/src/app/routes.test.ts`.
- `frontend/AGENTS.md` and [Development and operations](development-and-operations.md)
  describe project-specific verification commands.

