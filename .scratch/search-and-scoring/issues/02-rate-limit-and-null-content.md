# 02: Rate-limited and null model responses are handled

**What to build:** A rate-limited model call is retried with backoff instead of failing at once. A null model response fails with a clear "empty content" error. The viewer waits long enough for the matcher's full retry budget.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] A 429 followed by a 200 scores the job
- [x] A null message content fails with an error naming empty content
- [x] The viewer-to-matcher timeout exceeds the matcher's worst-case retry time

## Notes

- 429 retry and null-content tests: `matcher/tests/test_llm_client.py`. Both were red before the fix.
- Timeout guard: `viewer/backend/tests/test_matcher_client.py`. It checks the read timeout covers one job's worst case (3 × 180s + 3s backoff = 543s). Written after the change, so it guards rather than drove it.
- Open: the matcher scores a batch sequentially, so a batch of N jobs can take up to N × 543s. The viewer's 600s read timeout covers one job only. Batches of two or more can still time out. Fixing that means parallel scoring or a per-job call from the viewer; not in this ticket.
