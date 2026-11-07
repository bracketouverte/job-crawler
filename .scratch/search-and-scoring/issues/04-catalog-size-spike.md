# 04: Measure catalog size, then choose FTS or LIKE

**What to build:** Count rows in the catalog and record the FTS-or-LIKE decision for title search, with the number behind it. This is a spike with no code change.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent (done: LIKE)

## Measurement (2026-10-26)

- Crawl: greenhouse (stripe, airbnb), lever (palantir, spotify), ashby (ramp, notion). Sample slugs from the repo are fake and 404, so these were used instead. Real source lists are not in the repo.
- `catalog_jobs`: 1617 rows (greenhouse 910, lever 399, ashby 308). FTS mirror: 1617 rows.
- Caveat: real source lists are gitignored and absent here. Production catalog size is unknown and likely larger.

## Recommendation

LIKE. At this size a word-prefix LIKE scan is cheap, and dropping FTS removes the stale-index defect (ticket 06 becomes not applicable). Confirmed by owner: LIKE. Reverse only if production row count is far larger.

- [x] Row count recorded from `crawler/state/catalog.sqlite`
- [x] Decision recorded here: LIKE (drop FTS).
