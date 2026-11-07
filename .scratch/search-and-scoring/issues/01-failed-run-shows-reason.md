# 01: Failed run shows its reason on the job card

**What to build:** When a scoring run fails for any reason, the job card shows a readable reason and stops spinning. Empty-message errors show the exception type. Setup crashes mark the run failed instead of leaving it running.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] A timeout with an empty message shows the exception name on the card
- [x] A crash during run setup leaves the manifest failed with a non-empty message
- [x] The card stops polling on failed or on lookup error, and shows a toast with the reason

## Notes

- Covered by `viewer/backend/tests/test_match_run.py` (empty-message error, setup-failure manifest).
- Card toast/stop-polling is in `viewer/frontend/src/components/JobCard.tsx`; no frontend test harness, verified by viewer image build (tsc + Vite).
- Also fixed: manifest writes were non-atomic, so a poll during a write returned 404 and showed "Lost track". Now written via temp file + replace. Test: `test_write_manifest_failure_keeps_previous_manifest_readable`.
