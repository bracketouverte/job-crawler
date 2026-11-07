# 11: Async job scoring

**What to build:** Score jobs in a batch concurrently, or send one job per call from the viewer, so a batch of N jobs no longer takes N × the per-job worst case and cannot exceed the viewer's read timeout.

**Blocked by:** 02 (its open problem is the reason for this ticket)

**Status:** ready-for-agent

- [ ] A batch of several jobs completes within the viewer's read timeout when each job succeeds in normal time
- [ ] A batch with one failing job still returns results for the others
- [ ] Per-job progress reaches the run status (matcher `runs/{id}/status`)
