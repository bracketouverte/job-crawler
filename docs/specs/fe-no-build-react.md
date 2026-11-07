# Migrate feed frontend to plain React with no build step

Status: ready-for-agent

## Problem Statement

The feed UI is a React 19 + Vite + TypeScript app that depends on zustand, TanStack Query, TanStack Virtual, and axios. The build step adds Node tooling to the viewer image and makes the frontend hard to reason about for agents and for the owner. The owner wants plain React with no build step, using native ES modules served directly by the existing FastAPI backend.

## Solution

From the user's perspective, the feed page looks and behaves the same as today: feed, filters, saved searches, the queue drawer, analysis panel, hidden and favourite jobs, and the paste-JD dialog all work. Under the hood there is no bundler, no TypeScript build, and no third-party state or data libraries. The new frontend lives in `viewer/frontend-next/` and replaces `viewer/frontend/` at cutover.

## User Stories

1. As the owner, I want the feed to load without any build step, so that I can edit the UI and refresh the browser.
2. As a job seeker, I want the feed to show the same jobs, count and pagination as today, so that nothing regresses.
3. As a job seeker, I want every filter in the filter bar to work as it does today, so that my searches keep their meaning.
4. As a job seeker, I want the title, location and company text inputs to keep my typing while the page updates, so that input is never overwritten.
5. As a job seeker, I want my filters reflected in the URL and restored on reload, so that I can share and bookmark searches.
6. As a job seeker, I want to save a search and recall it from the saved-search strip, so that I can rerun common queries.
7. As a job seeker, I want to hide a job, and have it stay hidden after reload, so that I can clear irrelevant results.
8. As a job seeker, I want to mark a job as visited, so that I can tell which listings I have opened.
9. As a job seeker, I want to favourite a company, and filter by favourite companies, so that I can follow employers I care about.
10. As a job seeker, I want to see each job's score, scorecard and verdict in the analysis panel, so that I can decide what to apply to.
11. As a job seeker, I want to paste a job description and have it queued for scoring, so that I can analyse jobs from outside the feed.
12. As a job seeker, I want the queue drawer to show each run's status and reason, so that I can monitor scoring.
13. As a job seeker, I want a toast for every action that succeeds or fails, so that I know the outcome.
14. As a job seeker, I want pagination that moves between pages without flashing an empty list, so that browsing feels smooth.
15. As a job seeker, I want the page to work on a phone-width screen, so that I can search on the go.
16. As the owner, I want the viewer container to run without Node, so that the image is smaller and simpler.
17. As the owner, I want the new frontend to be a drop-in replacement at cutover, so that no backend API changes are needed.
18. As the owner, I want a manual checklist that proves parity before cutover, so that I know the migration is complete.

## Implementation Decisions

- **Stack:** React loaded as vendored ES modules, `htm` tagged templates instead of JSX, JSDoc for types. No bundler, no TypeScript compile step, no Node in the viewer image. Recorded in `docs/adr/0001-frontend-no-build-esm.md`.
- **State:** React built-in state and context. No zustand. Local-only state (hidden jobs, visited jobs, favourite companies) persists to browser storage with the same keys as today, so existing user data carries over.
- **Data fetching:** `fetch` with a small wrapper that returns parsed JSON or throws a typed error. No TanStack Query. Refetch-on-interval is replaced by an explicit polling helper for the queue and run status.
- **Lists:** pagination only, reusing the server's `limit`/`offset` and `total`. No virtualisation.
- **Routing and URL state:** the filter state is serialised to the query string using the same parameter names the backend already accepts.
- **Module layout:** a `src/` tree of plain ES modules with one component per file. Exact file paths are an implementation detail.
- **Backend:** no API changes. The viewer backend serves `viewer/frontend-next/` from its static directory after cutover.
- **Terminology:** UI labels follow the project glossary (`GLOSSARY.md`): "Provider" for ATS, "Source" for a company board, "Pipeline" for quick or ensemble, "Run", "Queue item", "Saved search". API parameter names are unchanged.
- **Cutover:** the old `viewer/frontend/` is deleted in the same change that switches the Dockerfile and compose config to the new directory, after the parity checklist passes.
- **Prerequisite:** search and scoring bugs from the companion spec are fixed first, so regressions in this migration are attributable.

## Testing Decisions

- Test external behaviour only. There is no frontend test harness in this spec.
- **Manual parity checklist** (committed under `docs/`): feed load, each filter, URL round-trip, saved searches, hide/visit/favourite persistence across reload, analysis panel, paste-JD flow, queue drawer, pagination, phone-width layout, and each toast.
- **Backend contract:** the existing viewer backend tests are the regression net for API shape; they must stay green unchanged.
- **Build check:** the viewer image builds and starts without Node after cutover.
- Prior art for backend tests: `viewer/backend/tests/test_http_roundtrip.py`.

## Out of Scope

- Playwright or browser-level automated tests.
- Virtualised lists.
- New features beyond the current feature set.
- Changes to backend APIs, the crawler, or the matcher.
- Progress UI for the paste dialog (handled in the companion spec if at all).

## Further Notes

- Depends on the companion search-and-scoring spec being merged first.
- Ship as a single PR at cutover; the no-build stack is the reason the new directory exists until then.
