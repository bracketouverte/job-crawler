# 07: Company filter matches name or slug

**What to build:** The company filter finds a company by its ATS slug, matched at a word start. Display-name matching is out of scope (no display-name column exists).

**Blocked by:** None (can start immediately)

**Status:** done (option 1, slug-only, confirmed by owner)

- [x] "Meta" finds a job whose slug is "metacareers"

## Findings (2026-10-26)

- The catalog has no display-name column. `company_name()` returns the slug for every provider except Workday, where it is the part before `/`. So "display name" is not available today.
- The company filter is `LOWER(source_key) LIKE %term%` (`viewer/backend/services/filters.py`). "Meta" already matches "metacareers" under the current code, so the first acceptance criterion already passes.
- The real defect is over-matching: substring LIKE also matches unrelated slugs, for example "meta" inside "metaplex".

## Decision needed

1. Match on slug word-prefix only (keeps today's data; "meta" finds "metacareers" and not "metaplex"), or
2. Add a display-name column populated by the crawler (cross-service change to the shared SQLite contract, larger scope).

Recommendation: option 1 now. Option 2 only if the owner needs names like "Meta" to match slugs that do not start with the name.

## Outcome

- Company filter now matches a slug at a word start only: start of slug, or after `-`, `_`, `.`, `/`, or space. `ramp` finds `ramp-labs` and not `trampoline`.
- Wildcards in the term are escaped, so `%` and `_` match literally.
- Tests: `viewer/backend/tests/test_filters.py` (real in-memory SQLite, not string checks). Red before the change, green after.
- Full viewer suite: 213 passed. Lint clean. Viewer image rebuilt and restarted.

**Correction to the decision above.** Option 1 cannot stop "meta" from matching "metaplex": it starts with "meta", so word-prefix still matches. It only stops mid-word matches such as "trampoline" for "ramp". Stopping "metaplex" would need display names (option 2).
