# Fix job search accuracy and JD scoring failures

Status: ready-for-agent

## Problem Statement

The job feed search returns inaccurate results. Simple title searches miss jobs that contain the word in a different form, searches using `-exclude` or `(a,b)` OR groups switch to a different matching rule and return different jobs, the company filter matches the ATS slug instead of the company name, the location filter matches substrings (so "or" matches "Toronto"), and jobs crawled after the first index build never appear in simple searches.

Separately, scoring a pasted job description with the free NVIDIA model fails with no useful feedback. The paste dialog closes immediately, the job card spins, and the failure reason is empty or missing. In the current environment the configured model returns 410 Gone, and a missing profile produces an opaque 500.

## Solution

From the user's perspective:

- Typing words in the title search finds jobs whose titles contain those words as prefixes, regardless of whether `-exclude` or `(a,b)` is used. One consistent rule applies.
- Company search finds a company by its ATS slug, matched at a word start.
- Location search matches whole words only.
- Newly crawled jobs appear in search results without a manual rebuild.
- When a scoring run fails, the job card shows a readable reason (for example, "Model returned 410 Gone" or "Profile not loaded: check CAREER_OPS_DIR") and the spinner stops.
- Transient rate-limit responses are retried before the run fails.

## User Stories

1. As a job seeker, I want to type `engineer` in the title search and see jobs titled "Engineering Manager", so that I find related roles without knowing the exact word form.
2. As a job seeker, I want `senior -principal` to exclude principal-level titles using the same matching rule as my plain search, so that I can trust the exclusion.
3. As a job seeker, I want `(react,vue)` to return jobs matching either term under the same rule as a single term, so that OR groups are predictable.
4. As a job seeker, I want the title search to match the start of words, so that `data eng` finds "Data Engineer".
5. As a job seeker, I want a job the crawler added five minutes ago to appear in my search, so that I don't see stale results.
6. As a job seeker, I want the company filter to find "Meta" when the ATS slug is "metacareers", so that I can search by the name I know.
7. As a job seeker, I want the company filter to match a company's slug at a word start, so that `ramp` finds `ramp-labs` but not `trampoline`. (Display-name matching was dropped: the catalog has no display-name column. Revisit only if the owner needs it.)
8. As a job seeker, I want the location filter `or` to not match "Toronto" or "Florence", so that location results are relevant.
9. As a job seeker, I want the days filter to include jobs posted exactly N days ago, so that date filtering is correct across timestamp formats.
10. As a job seeker, I want the total count shown with the results to match the jobs listed, so that pagination is accurate.
11. As a job seeker, I want my typed search text to remain in the box while I type, even if the URL or a saved search changes, so that input is not overwritten.
12. As a job seeker, I want a pasted job description to show a spinner until it is scored or fails, so that I know something is happening.
13. As a job seeker, I want a failed scoring run to show the reason on the job card, so that I know whether to fix my key, model, or profile.
14. As a job seeker, I want a rate-limited model call to be retried with backoff, so that free-tier limits do not fail a run immediately.
15. As a job seeker, I want a null model response reported as "empty content" rather than an unexplained parse error, so that I can tell model problems from parsing problems.
16. As a job seeker, I want a missing profile to return a 503 with an actionable message, so that I can fix the configuration.
17. As a job seeker, I want a timeout to show the exception type when the message is empty, so that the failure reason is never blank.
18. As a job seeker, I want a run that crashes during setup to be marked failed rather than running forever, so that the UI reaches a terminal state.
19. As a job seeker, I want the viewer to wait long enough for the matcher's retry budget before giving up, so that slow but working scoring is not reported as failed.
20. As an operator, I want the search index to stay correct without a manual rebuild, so that I can trust the catalog after each crawl.
21. As an operator, I want a clear error when the profile directory is unset or wrong, so that I don't debug a bare 500.
22. As an operator, I want the configured model checked against the provider's live model list, so that EOL models are caught early.

## Implementation Decisions

- **Search matching:** one rule for simple, excluded and OR-group title terms. Each term matches as a word prefix on title, combined with AND, `-x` excludes, `(a,b)` is OR. The filter module returns a SQL fragment. The FTS index is kept only if the catalog is large (decided by row count at implementation time); otherwise use a LIKE-based word-prefix match and drop FTS.
- **Index sync:** if FTS is kept, the index is kept current by triggers on the catalog table, created in the viewer's migrations. Triggers are a change to the crawler/viewer shared SQLite contract and must be coordinated with the crawler. The full-rebuild-if-empty behaviour is removed.
- **Company filter:** matches the `source_key` at a word start, with `-`, `_`, `.`, `/` or space as word boundaries. Wildcards in the term match literally.
- **Location filter:** whole-word match on the location text.
- **Days filter:** compares timestamps in a single normalised format on both sides.
- **Scoring errors:** the matcher's LLM client retries 429 with the existing backoff, treats a null message content as a named error, and includes the HTTP status in the error text.
- **Profile:** a missing profile raises a dedicated error type, mapped to 503 with a message naming the `CAREER_OPS_DIR` setting.
- **Viewer-to-matcher timeout:** raised to cover the matcher's worst-case retry budget.
- **Run lifecycle:** every exception in the run task, including setup failures, sets the manifest to failed with a non-empty message (falling back to the exception type).
- **Frontend:** the job card displays the run's error text and stops polling on failure or lookup error. The paste dialog keeps its current behaviour in this spec; progress UI is a follow-up.
- **Model check:** a pre-flight probe against the provider's model list is a diagnostic, not a gate. It is out of scope for the first slice.

## Testing Decisions

- Test external behaviour only: the request-to-results behaviour of the viewer's jobs endpoint and the matcher's analyze endpoints, and the SQL result set returned by the filter module.
- **Search:** table-driven tests in `viewer/backend/tests/test_filters.py` (existing prior art) covering prefix, exclude, OR, company slug vs name, location whole-word, days boundary, and a new-row-after-build case against a real in-memory SQLite catalog.
- **Scoring:** `matcher/tests/test_llm_client.py` (prior art: retry-then-succeed on 500) for 429 retry and null content; `matcher/tests/test_routers_analyze.py` for the 503 response.
- **Run lifecycle:** `viewer/backend/tests/test_match_run.py` (prior art: `test_run_scorer_phase_*`) for empty-message errors and setup-failure manifests.
- **Frontend:** no new test harness in this spec.
- Each fix begins with a failing test.

## Out of Scope

- Frontend migration to plain React (separate spec).
- Progress UI for the paste dialog and re-run button.
- Ensemble model selection and model deprecation tooling.
- Changes to crawler provider code.

## Further Notes

- Current environment: `.env` sets `NVIDIA_MODEL=openai/gpt-oss-20b` (verified working). Ensemble scorer and synthesizer entries in `.env` still reference EOL models and must be updated separately.
- Profile files live in `matcher/career-ops/` (gitignored, user-owned, never edited by this work).
