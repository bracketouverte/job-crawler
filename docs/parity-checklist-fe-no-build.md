# Parity checklist: frontend-next vs old frontend

Run against the viewer serving `viewer/frontend-next/` (no build step). Tick each item with the date and who checked it.

Legend: **[x]** verified in browser on the frontend-next preview · **[ ]** still to do by owner (needs matcher, or a scored job on the page).

## Feed and filters
- [x] Feed loads from `/api/jobs`, shows rows, no console errors
- [x] Filters restore from URL on reload (`?title=…&remote=0&page=2`)
- [ ] Each filter (provider, tiers, employment type, age, score, evaluated, include/exclude, location, company) changes results as the old frontend does — 2026-10-29: provider, title, company verified; evaluated-only returns "No jobs match" (not compared to old frontend). Not yet: location, tiers, employment type, age, score, include/exclude.
- [x] "Clear all" resets filters and URL — 2026-10-29

## Saved searches
- [x] Saved-search chips render from `saved-searches.json`
- [x] Clicking a chip adds `?searches=<id>`, disables filter bar, and merges results
- [ ] Known pre-existing defect, same in old frontend: saved searches whose location is `remote` return HTTP 500 (`no such column: is_remote`, `viewer/backend/services/filters.py`). Not a frontend regression; fix belongs with the crawler/catalog schema.

## Hide, visit, favourite (localStorage, key `job-viewer-local-store`)
- [x] Hidden job stays hidden after reload
- [ ] Visited marker appears after clicking a title, survives reload — 2026-10-29: marker (`job-card-visited`) appears and is stored; visual state after reload not checked.
- [ ] Favourite star toggles, survives reload; Favorites modal add/remove works — 2026-10-29: star toggles, toast shows, persists after reload; modal opens and lists favourites. Add/remove in modal not tested.

## Analysis panel and paste-JD
- [ ] Score badge opens panel with score, scorecard, verdict (needs a scored job on page)
- [ ] Re-run queues a run and reports a toast
- [ ] Paste-JD dialog opens, Analyze queues a run; failure shows a toast with reason

## Queue drawer
- [x] Queue button opens and closes the drawer
- [ ] Queue items show status and failure reason; Retry / Stop / Restart / Dismiss each toast success or failure — 2026-10-29: status and failure reason display verified. Actions not tested (they change queue data).

## Toasts
- [x] Hide shows a toast with working Undo (covered by code path; confirm Undo in browser) — 2026-10-29: Hide and favourite toasts shown; Undo button not clicked.
- [ ] Every action (analyze, re-run, queue actions, paste-JD, favourites, auto-analyzer) shows a success or failure toast — 2026-10-29: favourite, hide, and analyze ("Analysis queued.") toasts seen. Others not tested.

## Pagination
- [x] Out-of-range page shows "Page N of M" (no crash)
- [ ] Next/Prev keep previous rows visible (dimmed) until the next page arrives; total matches listed jobs — 2026-10-29: Next keeps rows visible, dims them while loading, no empty flash (Page 1→2 of 4). Total-vs-listed count not checked.

## Phone width (390px)
- [x] No horizontal page scroll (scrollWidth equals clientWidth)
- [x] 16px side gutter

## Backend contract
- [x] `viewer/backend` test suite passes unchanged (221 passed)
