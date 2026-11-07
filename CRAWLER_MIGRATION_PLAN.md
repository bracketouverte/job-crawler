# Crawler Migration Plan — Node/TypeScript → Python

## Overview

Port `crawler/` (the ATS-scraping service — 3,104 lines of TypeScript across 24 files) to Python 3.12, matching the async-service pattern already established for `matcher/` and `scheduler/` in this session's rewrite. `viewer/` (already Python) and `viewer/frontend/` (React/TypeScript — browser UI, not a migration candidate, out of scope) are unaffected.

**Why:** after the viewer/matcher/scheduler rewrite, the crawler is the only remaining non-Python backend service — a real architectural inconsistency, not just a stylistic one. Concretely:
- One language across the whole backend (crawler, matcher, viewer API, scheduler) instead of two toolchains, two dependency-update cadences, two sets of CI tooling.
- Eliminates the native-toolchain build dependency entirely: the current `Dockerfile` installs `python3 make g++` in **both** build stages just to compile `better-sqlite3`'s native bindings. Python's stdlib `sqlite3` needs zero compilation.
- Provider-parsing patterns (async HTTP fetch, HTML/JSON-LD extraction, guardrail-style regex logic) already exist in `matcher/services/parser.py` from this session — direct precedent to reuse, not a cold start.
- The scheduler's `subprocess.run(["docker", "compose", "run", "--rm", "crawler"])` call doesn't care what language the crawler is written in — no cross-service contract changes needed anywhere else.

**Target stack:** Python 3.12, `httpx.AsyncClient` (async HTTP, matching `matcher/lib/llm_client.py`'s pattern), stdlib `sqlite3` (sync, run in a threadpool executor exactly like `viewer/backend/db.py` already does), stdlib `xml.etree.ElementTree` or a light XML lib for TeamTailor's RSS feed, `asyncio.Semaphore` for concurrency (matching `matcher/services/ensemble_scorer.py`'s pattern).

**What must NOT change:** the on-disk contract with `viewer/backend`. `catalog.sqlite`'s schema (composite primary key `provider, source_key, job_id`, no `id` column — already the reason for the `content_rowid=rowid` fix in the just-merged bugfix PR), `crawler-progress.json`'s exact JSON shape (`viewer/backend/routers/config_router.py`'s `/api/crawl-status` passes it through to the frontend essentially raw), and `crawler-active.lock`'s file-existence + mtime-freshness semantics (`viewer/backend/services/saved_search.py`'s `is_crawler_active()`) all need to keep working unmodified. This is a same-service internal rewrite, not a cross-service API change — no story in this plan touches `viewer/` or `matcher/`.

---

## Decision (resolved)

`current-jobs.jsonl` (the `--catalog-file` / `exportJsonl()` output) has zero consumers anywhere in `viewer/backend/` or `matcher/`. **Decision: drop it.** `catalog_store.py` does not get an `export_jsonl` method, `--catalog-file` is not a recognized flag in the Python CLI, and `docker-compose.yml`'s crawler `command:` needs `--catalog-file` removed in Story 8.1.

---

## Repository Layout (after migration)

```
crawler/
├── Dockerfile                  # python:3.12-slim, no more python3/make/g++/node toolchain
├── Dockerfile.dev              # + pytest/ruff/black, mirrors matcher/scheduler pattern
├── pyproject.toml              # ruff + black + pytest + coverage config (fail_under = 70)
├── requirements.txt            # httpx, (xml parser if not stdlib)
├── requirements-dev.txt        # + pytest, pytest-asyncio, pytest-cov, ruff, black
├── main.py                     # CLI entrypoint (replaces cli.ts) + lock-file lifecycle
│                                #   (replaces docker-entrypoint.sh's trap cleanup)
├── config.py                   # CLI arg parsing + defaults (replaces cli.ts's arg parser)
├── models.py                    # NormalizedJob, SourceEntry, ProviderCrawler protocol, etc.
├── http_client.py              # shared fetch layer: retry/backoff/timeout/jitter/UA rotation
├── normalizers.py               # classify_tier, canonicalize_employment_type
├── geo.py                      # resolve_coords — reuses data/locations.json unmodified
├── catalog_store.py            # SQLite upsert/finalize/export, ensure_column migrations
├── source_loader.py            # sources/*.json loading + validation
├── dead_slugs.py                # per-provider TTL quarantine cache
├── exclusions.py                # --exclude-sources JSONL loader (was inline in runner.ts)
├── trend_log.py                 # trends.jsonl appender (low priority, port last)
├── runner.py                    # orchestration: concurrency, progress, JSONL+report output
├── post_crawl.py                 # replaces post-crawl.sh — 404/410 → exclude.jsonl
├── providers/
│   ├── __init__.py               # provider registry (replaces providers/index.ts)
│   ├── ashby.py
│   ├── bamboohr.py
│   ├── greenhouse.py
│   ├── icims.py
│   ├── lever.py
│   ├── smartrecruiters.py
│   ├── teamtailor.py
│   ├── workable.py
│   └── workday.py
├── data/
│   └── locations.json          # unchanged, reused as-is (29MB geocoding dataset)
└── tests/
    ├── conftest.py
    ├── test_http_client.py
    ├── test_normalizers.py
    ├── test_geo.py
    ├── test_catalog_store.py
    ├── test_source_loader.py
    ├── test_dead_slugs.py
    ├── test_exclusions.py
    ├── test_runner.py
    ├── test_post_crawl.py
    └── test_providers/          # not tests/providers/ -- collides with the
        │                        # top-level providers/ package on sys.path
        ├── test_ashby.py
        ├── test_bamboohr.py
        ├── test_greenhouse.py
        ├── test_icims.py          # zero coverage in the TS version — new, not ported
        ├── test_lever.py
        ├── test_smartrecruiters.py
        ├── test_teamtailor.py
        ├── test_workable.py
        └── test_workday.py
```

---

## Porting Discipline

Same rule as the matcher rewrite this session: **pure logic ports verbatim, only the I/O boundary changes shape** (JS `fetch`/Promises → Python `httpx.AsyncClient`/`asyncio`; `better-sqlite3` sync calls → stdlib `sqlite3` sync calls, unchanged — no async wrapper needed there, same as `viewer/backend/db.py`). Specific traps identified during research — do not "fix" or simplify any of these while porting, they are intentional or at minimum load-bearing as-is:

1. **`raw_json` column is always the literal string `"null"`**, never populated with real API response data, despite the column existing in the schema. Preserve this — don't start populating it, that's a silent storage/behavior change.
2. **`first_seen_at` is deliberately excluded from the upsert's `UPDATE` clause** — it's set once on INSERT only, as `job.posted_at ?? job.fetched_at ?? now` (a misleading name: it defaults to the job's *posted* date if known, not literally "when this crawler first saw it").
3. **Two independent, differently-scoped quarantine systems coexist on purpose**: `dead_slugs.py`'s per-provider TTL cache (3–10 day random TTL, auto-expiring, checked before a crawl even starts) vs. `exclusions.py`'s `--exclude-sources` JSONL (permanent, externally maintained, appended to by `post_crawl.py`). Do not merge these into one mechanism.
4. **The dead-slugs read-modify-write race is pre-existing and accepted**: concurrent workers marking different sources dead in the same provider's JSON file can clobber each other's writes. Note it in the story; fixing it with a lock is optional and cheap, but don't silently change dead-slug semantics if you do.
5. **SmartRecruiters is the only provider that reads `url_template`/`jobid_template`** from the source file, even though every `SourceFile` has those fields available. Every other provider ignores them today — don't "generalize" this during the port.
6. **`workday.py`'s `infer_compensation` guard regex** (rejecting job-req-ID-shaped strings, requiring an actual salary/comp keyword or currency match before accepting a "pay" field as compensation) is exactly the kind of easy-to-subtly-break regex logic that needs a byte-for-byte port, same discipline as the matcher's scoring guardrails.
7. **`docker-entrypoint.sh`'s lock-file lifecycle must move into `main.py`**, not stay as a separate shell wrapper — otherwise the port leaves an orphaned Node-shaped gap where 8/9 of the service is Python but the process lifecycle is still owned by shell script. Story 7.2 covers this explicitly.
8. **JS `Date.parse` leniency has no exact Python equivalent** — used in TeamTailor's `pubDate` parsing, Workday's relative-date parsing, and Lever's epoch-ms `createdAt`. Use `dateutil.parser.parse` with a try/except fallback to the raw string (matching the TS fallback behavior of "keep the unparsed string rather than dropping the field"), and verify against real sample API responses per provider — don't assume 1:1 parsing behavior without checking.

---

## Effort Estimate

| Phase | Estimated Time |
|---|---|
| Epic 1 — Foundation (types, config skeleton, HTTP client) | 1 day |
| Epic 2 — Normalizers & Geo | 1–1.5 days |
| Epic 3 — Catalog Store | 1 day |
| Epic 4 — Source Loading & Quarantine | 1 day |
| Epic 5 — Provider Crawlers (9 providers) | 3–4 days |
| Epic 6 — Runner Orchestration | 1.5–2 days |
| Epic 7 — CLI, Entrypoint & Post-Crawl | 1 day |
| Epic 8 — Docker & Compose Wiring | 0.5 days |
| Epic 9 — Testing & Verification | 1.5–2 days |
| **Total** | **~12–15 days** |

The riskiest parts are Epic 5 (Workday's pagination + relative-date parsing + compensation guard regex, and TeamTailor's RSS/XML parsing) and Epic 6 (the concurrency model — global worker pool composed with per-provider semaphores — has to preserve exact throughput characteristics, not just "eventually crawl everything"). Build and validate those before Epic 8.

---

---

# Epics & Stories

---

## EPIC 1 — Foundation

> Core types, CLI config parsing, and the shared HTTP client. No provider logic, no persistence yet.

---

### STORY 1.1 — Core Types

**Goal:** Port `types.ts`'s data shapes as the shared vocabulary every other module imports.

**Instructions:**
1. `models.py`: use `dataclasses` or `TypedDict` (prefer `dataclasses` for parity with matcher's style) for:
   - `Provider` — a `Literal`/enum of the 9 provider strings: `ashby, bamboohr, greenhouse, icims, lever, smartrecruiters, teamtailor, workable, workday`.
   - `SourceEntry` — two shapes: identifier-based (`identifier: str`) for 8 providers, and Workday's `tenant/shard/site` triple. Model as a union or a single dataclass with optional fields matching the TS union.
   - `SourceFile` — `provider`, `url_template: str | None`, `jobid_template: str | None`, `companies: list[SourceEntry]`.
   - `NormalizedJob` — the universal output shape: `provider, source_key, job_id` (required) + `title, location, employment_type, compensation, department, office, language, updated_at, posted_at, job_url, fetched_at` (all `str | None`) + `skill_tier: str | None` (computed later, not set by providers themselves — verify against `normalizers.ts` call sites before assuming this).
   - A `ProviderCrawler` protocol (`typing.Protocol`): `provider: str`, `async def crawl(source: SourceEntry, context: CrawlContext) -> list[NormalizedJob]`.
   - `CrawlContext` — `http: HttpClient`, `fetched_at: str`, `max_jobs_per_source: int | None`, `url_template: str | None`, `jobid_template: str | None`.

**Acceptance Criteria:**
- [ ] Every provider module in Epic 5 can import from `models.py` without needing provider-specific type additions.
- [ ] `NormalizedJob` field names match `catalog_store.py`'s upsert column list exactly (this is the shape written straight into the DB).

---

### STORY 1.2 — Shared HTTP Client

**Goal:** Port `http.ts`'s retry/backoff/timeout/jitter logic verbatim — this is what every provider's `crawl()` calls through.

**Instructions:**
1. `http_client.py`, backed by a single shared `httpx.AsyncClient` (start/stop via module-level functions, exactly matching `matcher/lib/llm_client.py`'s `start_client()`/`stop_client()`/`_get_client()` pattern).
2. Transient HTTP statuses that trigger a retry: `{408, 425, 429, 500, 502, 503, 504}`. Anything else raises immediately (`HttpError(message, status, body)` — a custom exception carrying status + response body, matching the TS `HttpError` class).
3. Retry loop: `for attempt in range(retries + 1)`, backoff formula **`base = min(5000, 250 * 2**attempt)` milliseconds, then `base ± 20% jitter`** (i.e. `base + random.uniform(-0.2, 0.2) * base`), converted to seconds for `asyncio.sleep`.
4. Per-request timeout via `httpx.Timeout` (not `AbortController` — that's the JS-specific mechanism, httpx's own timeout param is the direct equivalent).
5. Optional **pre-request jitter** (`jitter_ms: tuple[int, int] | None`) — a random delay applied **once**, before the retry loop starts (not per-attempt) — used for HTML-scraping providers (see Epic 6's `HTML_SCRAPING_PROVIDERS` set).
6. Random User-Agent per request, chosen from the same 8-entry hardcoded list as the TS version (copy the exact strings — port `http.ts`'s UA array verbatim, don't regenerate a new list).
7. Three methods only, matching the TS `HttpClient` interface: `get_json`, `post_json`, `get_text`.

**Acceptance Criteria:**
- [ ] A 429 response is retried up to `retries` times with increasing (jittered) backoff; a 404 raises immediately without retrying.
- [ ] `jitter_ms` delays the request once, before any retry attempt, not on every retry.
- [ ] User-Agent header varies across repeated calls (confirms rotation is wired, not hardcoded to one string).
- [ ] `HttpError` carries the response status and body so provider code (and `dead_slugs.py`, `runner.py`'s 404/410 dead-marking) can inspect `exc.status`.

---

## EPIC 2 — Normalizers & Geo

> Pure-function classification and geocoding logic, no I/O. Port byte-for-byte — these are exactly the kind of regex/keyword-scoring logic where "simplifying while porting" silently changes behavior.

---

### STORY 2.1 — Employment Type & Skill Tier Classification

**Goal:** Port `normalizers.ts` verbatim.

**Instructions:**
1. `normalizers.py::canonicalize_employment_type(raw: str | None) -> str | None`:
   - First discard ATS-ID-shaped strings via the regex `^[A-Za-z]{0,4}[\d\-_/]{3,}$` (case-sensitive as in the original — verify).
   - Then lowercase-match in this exact priority order (first match wins): `intern(ship)` → `"Internship"`; `volunteer` → `"Volunteer"`; `temp(orar(y|ily))|casual` → `"Temporary"`; `part[-_ ]?time|p[-_ ]?t` → `"Part-time"`; `contract(or)?|freelance|independent contractor|ctr` → `"Contract"`; `full[-_ ]?time|f[-_ ]?t|permanent|regular|cdi|employee` → `"Full-time"`; else `None`.
2. `normalizers.py::classify_tier(title: str | None) -> str`:
   - Additive/subtractive keyword scoring on the lowercased title. Score contributions: `chief|cto|ceo|coo|cpo|ciso|\bvp\b|vice president|director` → **+50**; `principal|distinguished|fellow` → **+40**; `staff|\blead\b|head of` → **+30**; `senior|\bsr\b` → **+20**; `architect|manager` → **+15**; `L[4-9]|Level [4-9]` → **+15**; roman numeral IV or V → **+15**; roman numeral III → **+10**; `junior|\bjr\b` → **-20**; `trainee|graduate|new grad|entry-level|associate` → **-25**; `intern(ship)` → **-100**; roman numeral II → **-5**; standalone `"I"` (fixed-width lookbehind/lookahead so this is not a JS-only regex feature — `re` handles it directly) → **-10**.
   - Thresholds: score `<= -50` → `"intern"`; `<= -5` → `"entry"`; `>= 15` → `"senior"`; else `"mid"`. No title at all → `"mid"` (the default, not an error case).
   - Port the exact keyword list and point values above — do not consolidate or "clean up" overlapping patterns (e.g. `senior` and `sr` are separate alternatives in the same rule, keep them separate).

**Acceptance Criteria:**
- [ ] A table-driven test suite covering every keyword bucket (at minimum one title per scoring rule above) confirms identical tier output to the TS version — write these as literal title→tier assertions, not property-based tests, since exact parity is the goal.
- [ ] `classify_tier(None)` and `classify_tier("")` both return `"mid"`.
- [ ] `canonicalize_employment_type` correctly discards a string like `"REQ-2024-001"` (ATS-ID pattern) as `None` rather than misclassifying it.

---

### STORY 2.2 — Geo Resolution

**Goal:** Port `geo.ts`'s `resolveCoords` — the most intricate pure-logic file in the codebase.

**Instructions:**
1. `geo.py`, reusing `data/locations.json` **unmodified** — copy the file as-is, no regeneration.
2. Build the same 4 lookup `dict`s (city+admin+country → city+country → city+admin → city-only, decreasing specificity), loaded once at module import and cached module-level (matching the TS singleton-cache pattern).
3. Static tables to port verbatim: US state abbreviation/name → 2-letter code map, ~25 country aliases, city aliases (e.g. `"nyc"` → `"new york city"`), the NYC-borough set, remote/timezone/garbage-location keyword sets, work-arrangement prefix strippers (e.g. `"hybrid in "`), junk-suffix stripper for `area/metro/region/greater/metropolitan`.
4. Normalization pipeline order (must match exactly): Unicode NFD-normalize + strip combining marks (`unicodedata.normalize("NFD", s)` then filter `unicodedata.combining(c)` — this is the Python equivalent of JS's `.normalize("NFD")` + diacritic-strip regex, not a literal regex port) → strip non-alphanumerics → expand abbreviations (`ft→fort, mt→mount, st→saint, n→north, s→south`) → strip work-arrangement prefixes and parenthetical asides and trailing `"- remote"` → tokenize on commas → dedupe consecutive identical tokens → handle the single-token `"City ST"` space-separated case → extract trailing country/US-state tokens → normalize NYC boroughs → fall through the 4-tier lookup.
5. `resolve_coords(location: str | None) -> tuple[float, float] | tuple[None, None]`.

**Acceptance Criteria:**
- [ ] Test against a representative sample of real location strings pulled from actual crawled data (ASCII US city/state strings, at minimum) and confirm identical lat/lon to the TS version.
- [ ] At least one non-ASCII location string (accented city name) is tested explicitly and the diacritic-stripping is verified — flagged in the research as not a guaranteed byte-identical translation, confirm it empirically rather than assuming.
- [ ] An unresolvable location string returns `(None, None)`, not an exception.

---

## EPIC 3 — Catalog Store

> SQLite persistence. Synchronous by design (matching `viewer/backend/db.py`'s pattern) — no async wrapper needed for the DB layer itself.

---

### STORY 3.1 — Schema, Pragmas & Upsert

**Goal:** Port `catalog-store.ts`'s schema and write path exactly, preserving every quirk from the porting-discipline list above.

**Instructions:**
1. `catalog_store.py::CatalogStore` — a class wrapping a stdlib `sqlite3.Connection`.
2. On connect: `PRAGMA busy_timeout=30000`, `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `PRAGMA foreign_keys=ON`.
3. `CREATE TABLE IF NOT EXISTS catalog_jobs` with the composite primary key `(provider, source_key, job_id)` — **no `id` column** — plus `raw_json TEXT NOT NULL DEFAULT 'null'` (always literal `"null"`, never populated — see porting discipline #1). Full column list from the research: `provider, source_key, job_id, title, location, employment_type, compensation, department, office, language, updated_at, posted_at, job_url, fetched_at, first_seen_at, last_seen_at, seen_run_id, raw_json`.
4. Indexes: `catalog_jobs_seen_run_id_idx`, `catalog_jobs_last_seen_at_idx`.
5. `ensure_column(table, column, sql_type)` migration helper (PRAGMA `table_info` check + `ALTER TABLE ADD COLUMN`, matching `viewer/backend/db.py`'s `_add_column_if_missing` pattern already in this codebase) — run on every startup for `posted_at, skill_tier, employment_type_canonical, lat, lon`, added incrementally after the base `CREATE TABLE` so this must run against pre-existing databases too.
6. `upsert_one(job: NormalizedJob, run_id: str)`: `INSERT ... ON CONFLICT(provider, source_key, job_id) DO UPDATE SET <everything except first_seen_at>`. `first_seen_at` set only on INSERT as `job.posted_at or job.fetched_at or now`. `last_seen_at = job.fetched_at or now`. Compute `skill_tier`, `employment_type_canonical`, `lat`/`lon` inline at upsert time via `normalizers.classify_tier`, `normalizers.canonicalize_employment_type`, `geo.resolve_coords`.
7. `record_jobs(jobs: list[NormalizedJob], run_id: str)`: wrap each call in a transaction (per-source-completion granularity, not one giant transaction for the whole crawl — matches the TS version's incremental-commit behavior so a crash partway through a crawl doesn't lose already-completed sources).

**Acceptance Criteria:**
- [ ] Upserting the same `(provider, source_key, job_id)` twice with a different `title` updates the row without duplicating it, and does not change `first_seen_at`.
- [ ] `first_seen_at` on a fresh insert equals `posted_at` when present, else `fetched_at`.
- [ ] `raw_json` is always the string `"null"` after upsert — a test asserting this explicitly, to lock in porting discipline #1 and catch any future accidental "improvement."
- [ ] Running `ensure_column` against a database that already has all 5 incrementally-added columns is a no-op (doesn't raise "duplicate column").

---

### STORY 3.2 — Finalize, Export & Trend Log

**Goal:** Port the remaining `CatalogStore` methods plus `trend-log.ts`.

**Instructions:**
1. `finalize_run(run_id: str)`: `DELETE FROM catalog_jobs WHERE seen_run_id != ?` — called once at the very end of a crawl, using the crawl's start-timestamp string as `run_id`. This is the stale-job pruning step.
2. `export_jsonl` / `current-jobs.jsonl` / `--catalog-file` are **dropped** (resolved decision above) — no `CatalogStore` method for this.
3. `trend_log.py::append_trend_entry(db_path, state_dir)`: opens the catalog DB **read-only**, computes `{date (YYYY-MM-DD), total, by_provider: {...}, by_tier: {...}}`, appends one JSON line to `trends.jsonl`. Non-fatal — wrap the caller (in `main.py`, Epic 7) in try/except and log, don't let a trend-log failure fail the whole crawl. Low priority — nothing else in this repo reads `trends.jsonl`, per the research; port faithfully but don't over-invest here.

**Acceptance Criteria:**
- [ ] `finalize_run` deletes rows from a previous run (different `seen_run_id`) but keeps rows just written in the current run.
- [ ] `append_trend_entry` opens the DB read-only (verify no write-lock contention with a concurrent `record_jobs` call in a test).

---

## EPIC 4 — Source Loading & Quarantine

---

### STORY 4.1 — Source File Loading

**Goal:** Port `source-loader.ts`.

**Instructions:**
1. `source_loader.py::load_source_file(provider: str, sources_dir: str) -> SourceFile`: reads `{sources_dir}/{provider}.json` (not `.sample.json`). Missing file → warn to stderr, return `SourceFile(provider, companies=[])` (soft failure, does not raise).
2. Validation: `companies` must be a list; for `workday`, each entry needs non-empty `tenant`/`shard`/`site` strings; every other provider needs a non-empty `identifier`.
3. `source_key(entry: SourceEntry) -> str`: `entry.identifier` for 8 providers, `f"{tenant}/{shard}/{site}"` for Workday.
4. `parse_provider_list(spec: str) -> list[str]`: `"all"` expands to all 9 providers; otherwise comma-separated, raising on any unknown provider name.

**Acceptance Criteria:**
- [ ] A missing source file logs a warning and returns an empty company list rather than crashing the whole crawl.
- [ ] `parse_provider_list("all")` returns all 9 providers in a stable order; an unknown provider name in a comma-separated list raises.
- [ ] `source_key` for a Workday entry is `"{tenant}/{shard}/{site}"`; for every other provider it's the bare identifier.

---

### STORY 4.2 — Dead-Slug Quarantine & Exclusion List

**Goal:** Port `dead-slugs.ts` and the exclusion-list loading that currently lives inline in `runner.ts`.

**Instructions:**
1. `dead_slugs.py`: per-provider JSON file `dead_slugs_{provider}.json`, shape `{slug: {dead_at, code, ttl_days}}`. Only HTTP `404`/`410` mark a slug dead. TTL is **randomized 3–10 days inclusive per mark** (`3 + random.randint(0, 7)`, not a fixed value). Expired entries are pruned at **read time** on every `load()` call, not via a background job.
2. `exclusions.py::load_excluded_sources(file_path: str) -> set[str]`: reads a JSONL file (path from `--exclude-sources`), each line an object accepting either `provider`/`ats` and either `source_key`/`identifier` as key names (accept both — the TS version does), builds a set of `"{provider}:{key}"` strings.
3. Both mechanisms filter the pre-crawl work list identically but stay **separate** (porting discipline #3) — don't merge them.
4. Note the pre-existing read-modify-write race in `dead_slugs.py`'s mark-dead path (porting discipline #4) in a code comment; fixing it with a lock is optional.

**Acceptance Criteria:**
- [ ] A dead-marked slug with an expired TTL is excluded from the loaded set (pruned, not just ignored) on the next `load()`.
- [ ] A source is skipped if it appears in **either** the dead-slugs cache or the exclusion set — verify both paths independently with a test that only populates one.
- [ ] Only 404/410 responses call `mark_dead` — a 500 or a timeout must not quarantine a source.

---

## EPIC 5 — Provider Crawlers

> One story per provider (except a shared story for the 4 simple single-page JSON APIs). Every provider implements the `ProviderCrawler` protocol from Story 1.1. Reference implementation in `matcher/services/parser.py` for the HTML/JSON-LD extraction pattern already established this session.

---

### STORY 5.1 — Simple Single-Page JSON Providers (Ashby, Greenhouse, Lever, Bamboohr)

**Goal:** Port the 4 providers with no pagination.

**Instructions:**
1. `providers/greenhouse.py`: `GET boards-api.greenhouse.io/v1/boards/{identifier}/jobs?content=true`, single page. `job_id = first_string(id, internal_job_id, title) or "unknown"`. `compensation`: scan `job["metadata"]` (may be a list or a dict) for an entry whose `name`/`label` contains `"compensation"` or `"salary"` (case-insensitive substring), return its `value`/`name`.
2. `providers/lever.py`: `GET api.lever.co/v0/postings/{identifier}?mode=json`, single page (response is already the full array). `created_at` (epoch ms) is used for **both** `updated_at` and `posted_at` — Lever has no separate updated field, don't invent one.
3. `providers/ashby.py`: `GET api.ashbyhq.com/posting-api/job-board/{identifier}`, single page. `job_url` falls back to a constructed `https://jobs.ashbyhq.com/{source_key}/{id}` when the API response doesn't provide one.
4. `providers/bamboohr.py`: `GET {identifier}.bamboohr.com/careers/list` with header `Accept: application/json` — response is either a bare list or `{"result": [...]}`. Treated as an HTML-scraping provider (jitter applied, per Epic 6's `HTML_SCRAPING_PROVIDERS`) even though the endpoint itself returns JSON — preserve this classification, it's about the site's rate-limiting behavior, not the response format. `job_url` is **always** constructed as `https://{source_key}.bamboohr.com/careers/{id}/detail`, never taken from the API response.

**Acceptance Criteria:**
- [ ] Each provider's `normalize_*_job` pure function has a dedicated unit test ported from `providers/normalization.test.ts`'s existing 8 cases (Ashby, Bamboohr, Greenhouse, Lever, plus the 4 from later stories) — same fixture inputs, same expected `NormalizedJob` output.
- [ ] Greenhouse's compensation-extraction handles both a metadata list and a metadata dict without raising.
- [ ] Bamboohr's `job_url` is always the constructed form, never echoed from the API even if the response happens to include a URL field.

---

### STORY 5.2 — SmartRecruiters (Paginated JSON)

**Goal:** Port the first paginated provider.

**Instructions:**
1. `providers/smartrecruiters.py`: offset/limit pagination, `limit=100` per page. Response may be a bare list (single page, no more) or `{"content"|"jobs"|"postings": [...], "total_found": int | None}`. Continue while `offset + page_length < total_found` when `total_found` is present, else fall back to the heuristic `page_length == page_size` (i.e. a full page implies there might be more).
2. Support `url_template`/`jobid_template` overrides from the source file (`{identifier}`, `{job_id}`, `{id}` placeholder substitution) — **this is the only provider that reads these fields**, per porting discipline #5. `render_template()`: simple `{key}` regex substitution with URL-encoding of the substituted value.
3. `with_paging()`: inject `offset`/`limit` query params only if not already present in the (possibly templated) URL's query string — use `urllib.parse` (`urlsplit`/`parse_qs`/`urlencode`), the Python equivalent of the TS version's `URL`/`URLSearchParams` usage.

**Acceptance Criteria:**
- [ ] A response with `total_found` set stops pagination exactly when `offset + page_length >= total_found`, not one page early or late.
- [ ] A response without `total_found` (heuristic fallback) stops on the first non-full page.
- [ ] A source file with a custom `url_template` containing `{identifier}` is used verbatim (with substitution) instead of the default endpoint construction — and a source file *without* a template still works via the default path.

---

### STORY 5.3 — TeamTailor (RSS/XML)

**Goal:** Port the one provider that parses XML instead of JSON.

**Instructions:**
1. `providers/teamtailor.py`: `GET {identifier}.teamtailor.com/jobs.rss`. Parse with Python's stdlib `xml.etree.ElementTree` (or `defusedxml.ElementTree` if available — prefer the safer parser for untrusted external XML, this is a reasonable, justified improvement over the TS version's `fast-xml-parser`, not a "port everything literally including library choices" case, since we're not required to match the parsing library, only the resulting data).
2. RSS `<item>` elements, custom namespaced tags `teamtailor:department`/`teamtailor:location` — access via the full `{namespace}tag` form or a registered namespace prefix, whichever `ElementTree` idiom is cleaner; the *values* extracted must match the TS version exactly.
3. `parse_date(pub_date: str) -> str`: try `dateutil.parser.parse(pub_date)` first (the closest analog to JS's lenient `Date` parsing, per porting discipline #8); on failure, fall back to returning the raw string unparsed (matching the TS fallback behavior — never drop the field, never raise).

**Acceptance Criteria:**
- [ ] A real (or realistic sample) TeamTailor RSS feed parses into the same set of `NormalizedJob` fields as the TS version, including the namespaced `department`/`location` tags.
- [ ] A malformed or unusual `pubDate` string falls back to being stored as-is (not dropped, not an exception) — test this explicitly since it's the one behavior most likely to silently diverge between JS's `Date.parse` and `dateutil`.

---

### STORY 5.4 — Workable

**Goal:** Port the location-fallback-heavy provider.

**Instructions:**
1. `providers/workable.py`: `GET apply.workable.com/api/v1/widget/accounts/{identifier}`, single page.
2. Location resolution, 2-tier fallback: `format_locations(job["locations"])` — filter out entries with `hidden is True`, join the remaining visible ones with `" | "` — then if that's empty, `format_location(city, state, country)` as a flat single-location fallback.
3. `office = "Remote"` iff `job.get("telecommuting") is True`, else `None`.

**Acceptance Criteria:**
- [ ] A job with multiple visible locations joins them with `" | "`; a job with all-hidden locations falls through to the flat `city/state/country` fallback.
- [ ] `telecommuting: true` sets `office = "Remote"` exactly; any other value (including missing) leaves `office` as `None`.

---

### STORY 5.5 — Workday (Highest-Risk Provider)

**Goal:** Port the most complex provider — POST-based pagination, fiddly URL reconstruction, relative-date parsing, and a guarded compensation-extraction regex.

**Instructions:**
1. `providers/workday.py`: `POST https://{tenant}.{shard}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` with body `{"appliedFacets": {}, "limit": 20, "offset": <n>, "searchText": ""}`. Safety cap: `max_pages_per_source = 1000` (up to 20,000 jobs/source). Stop when `len(postings) < page_limit` or the reported `total` is reached.
2. `job_url` reconstruction: API returns `external_path` like `/job/DUNDEE-GBR/Product-Manager_R1151951`; extract everything after the second `/` via regex, rebuild as `https://{tenant}.{shard}.myworkdayjobs.com/en-US/{site}/job/{job_path}`. Port the exact regex, don't rewrite it as a `split("/")` even though that might look cleaner — verify against real sample paths first if you do consider simplifying.
3. `parse_workday_posted_at(raw, fetched_at)`: try an exact date parse first (`dateutil.parser.parse`); else regex-match `today`, `yesterday`, or `posted N day(s)/week(s)/month(s)/year(s) ago` (month ≈ 30 days, year ≈ 365 days — these are approximations in the original, keep them as approximations, don't switch to calendar-accurate month/year math) and compute the resulting date from `fetched_at`'s UTC start-of-day.
4. `infer_compensation(bullet_fields)`: find a bullet-field entry whose label contains `"pay"` (case-insensitive), then **validate** it actually looks like a real compensation string via a regex requiring a salary/compensation/pay-range/OTE/equity/bonus/hourly/annual keyword or a currency symbol with digit-grouping — reject and return `None` otherwise. Additionally reject anything matching a job-req-ID shape (`^(req|r|jr|job)[-_]?\d+`) even if it superficially passed the first check. Port both regexes verbatim (porting discipline #6) — this is the single highest-risk piece of logic in the whole provider set for a "helpful simplification" to silently break.

**Acceptance Criteria:**
- [ ] Pagination stops correctly both when `total` is known and reached, and when a short final page is returned without a `total`.
- [ ] `job_url` reconstruction matches the TS version's output for at least 3 real (or realistic sample) `external_path` values, including ones with unusual characters.
- [ ] `parse_workday_posted_at` correctly handles `"today"`, `"yesterday"`, `"posted 3 days ago"`, `"posted 2 months ago"`, and an ISO date string — 5 explicit test cases minimum.
- [ ] `infer_compensation` accepts a genuine `"$120,000 - $150,000"`-shaped pay field and rejects both a job-req-ID-shaped string and a "pay" field with no recognizable comp keyword.

---

### STORY 5.6 — iCIMS (XML Sitemap, Zero Existing Test Coverage)

**Goal:** Port the sitemap-scraping provider, and give it real test coverage for the first time (the TS version has none).

**Instructions:**
1. `providers/icims.py`: `GET https://careers-{slug}.icims.com/sitemap.xml`, parsed with a **plain regex** (`<loc>\s*(https?://...)\s*</loc>`), matching the TS version's choice — not a real XML parser, since the sitemap is simple enough that this was a deliberate simplification in the original, not an oversight.
2. Slug normalization: strip a leading `careers-` prefix from source-list identifiers (they're inconsistently pre/un-prefixed — per the original code comment, "harvested from Common Crawl full domain names").
3. Filter URLs to the `.../jobs/{id}/{title-slug}/job` pattern only — discard everything else in the sitemap.
4. **Title is reconstructed from the URL slug** (URL-decode, hyphens → spaces, then title-case each word) — there is no title field in the sitemap at all. This matches CLAUDE.md's already-documented iCIMS limitations: no location, no compensation, no employment_type, no posted_at — sitemap-only data.

**Acceptance Criteria:**
- [ ] A source identifier with and without the `careers-` prefix both resolve to the same normalized slug.
- [ ] Title reconstruction from a real iCIMS URL slug (e.g. `senior-product-manager` → `"Senior Product Manager"`) is tested explicitly — this is new coverage, not a port of an existing test.
- [ ] A sitemap URL that doesn't match the `.../jobs/{id}/{title-slug}/job` pattern is silently skipped, not included as a malformed job.

---

## EPIC 6 — Runner Orchestration

> The most architecturally involved port. Preserve the exact concurrency model — this directly affects real crawl throughput and the provider-concurrency compose overrides already tuned in `docker-compose.yml`.

---

### STORY 6.1 — Concurrency Model

**Goal:** Port the global-worker-pool + per-provider-semaphore composition from `runner.ts`.

**Instructions:**
1. `runner.py`: `worker_count = min(max(concurrency, 1), len(items) or 1)` async workers (`asyncio.create_task`), each looping on a **shared mutable cursor index** over the work list (the TS version's work-stealing pattern) — an `asyncio.Lock`-guarded index increment, not a queue, to match the exact scheduling behavior (a worker that finishes early immediately grabs the next unclaimed item, rather than pre-partitioned batches).
2. A per-provider `asyncio.Semaphore` (replacing the hand-rolled `Limiter` class) enforces `--provider-concurrency` caps (e.g. `ashby=1,workday=4,...`) **inside** each worker's per-item task — the global pool and per-provider limits compose (e.g. concurrency=50 total workers, but ashby capped to 1 in-flight regardless of how many workers are otherwise idle).
3. `HTML_SCRAPING_PROVIDERS = {"bamboohr", "workday", "teamtailor", "workable", "icims"}` — these get the jittered `HttpClient` (300–1200ms pre-request delay); the remaining 4 (`ashby, greenhouse, lever, smartrecruiters`) get the non-jittered client.
4. **Interleaving is optional, not correctness-critical** — the TS version round-robins work items across providers before dispatch purely for nicer-looking progress-log output (not provider-sequential). Port it only if you want byte-identical console output ordering; skip it if not, and note the decision in the story's implementation, since it's the one piece of `runner.ts` explicitly flagged in research as cosmetic rather than load-bearing.

**Acceptance Criteria:**
- [ ] With `concurrency=10` and `provider_concurrency={"workday": 2}`, no more than 2 Workday sources are ever in-flight simultaneously, even while up to 10 total sources across other providers run concurrently — a test using a fake slow crawler + a counter/lock to assert peak concurrency per provider.
- [ ] A worker that finishes a fast source immediately picks up the next unclaimed item rather than waiting for other workers — verify via ordering/timing in a test with artificially staggered fake crawl durations.

---

### STORY 6.2 — Dead-Slug Marking, Progress Reporting & Output Writers

**Goal:** Port the per-job flow: catalog write, dead-slug marking on 404/410, progress events, JSONL + report output.

**Instructions:**
1. On `HttpError` with `status in {404, 410}` during a source's crawl, call `dead_slugs.mark_dead(state_dir, provider, source_key, status)` synchronously (accepting the pre-existing race condition, porting discipline #4).
2. `catalog_store.record_jobs(jobs, run_id)` is called **unfiltered**, immediately after each source's crawl completes (including any cross-source duplicate keys — the DB's composite primary key handles de-duplication at the storage layer).
3. **Separately**, for the `jobs.jsonl` output only (not the DB write): apply `--max-age-hours` freshness filtering (`posted_at or updated_at` must fall within N hours; a job with no parseable date is dropped from the JSONL but still written to the DB) and in-run de-dup via a `set[str]` of `"{provider}:{source_key}:{job_id}"` keys already seen this run.
4. Progress payload — **preserve this exact shape and field names**, it's the live contract with `viewer/backend/routers/config_router.py`'s `/api/crawl-status`:
   ```python
   {
     "event": str, "elapsed_seconds": float,
     "completed_sources": int, "total_sources": int, "percent": float,
     "succeeded_sources": int, "failed_sources": int,
     "total_jobs": int, "failures_recorded": int,
     "by_provider": {
       "<provider>": {"done": int, "total": int, "skipped": int, "jobs": int, "failed": int}
     }
   }
   ```
   Emitted on start, on a periodic interval (`--progress-every-ms`, default 10000, `0` disables), and on completion — both to stdout as one JSON line per event, and written to `--progress-file` (best-effort; a write failure here must not fail the crawl — matches the TS version's swallowed-write-error behavior).
5. JSONL writer: a simple buffered/locked synchronous or `aiofiles`-based writer is sufficient — the TS version's hand-rolled stream-backpressure-drain-event class (~50 lines) is Node-stream-specific complexity that should **not** be ported as-is; this is an explicitly approved simplification, not a "verbatim port" violation, since the research flagged this exact class as not worth replicating.
6. Final `CrawlReport`: `{started_at, ended_at, source_counts, skipped_sources, skipped_by_provider, providers: {<provider>: ProviderStats}, total_jobs, failures: [...]}`, written to `--report`.

**Acceptance Criteria:**
- [ ] A source that 404s has its slug marked dead and does not appear as a "failure" in the crawl report the same way an unexpected 500 does (verify the report distinguishes expected-dead-marked skips from real failures, matching whatever distinction the TS version makes — check `runner.ts`'s failure-recording logic if ambiguous).
- [ ] The `crawler-progress.json` file's JSON shape is byte-comparable (same keys, same nesting) to a captured real run of the TS version, not just "close enough" — this is a live contract with the viewer, verify it explicitly.
- [ ] `--max-age-hours` filtering affects only `jobs.jsonl` output, not what gets written to `catalog.sqlite` — a job older than the cutoff is still upserted to the DB (so its `last_seen_at` stays current) but excluded from the JSONL export.

---

## EPIC 7 — CLI, Entrypoint & Post-Crawl

---

### STORY 7.1 — CLI Argument Parsing

**Goal:** Port `cli.ts`'s hand-rolled arg parser.

**Instructions:**
1. `config.py` (or inline in `main.py` via `argparse`, which is a reasonable and idiomatic Python substitute for the TS version's hand-rolled parser — not required to hand-roll a parser to match, `argparse` is the correct tool here).
2. Full flag list with defaults, ported exactly: `--sources` (`/data/sources`), `--providers` (`all`), `--concurrency` (50), `--out` (`/app/output/jobs.jsonl`), `--report` (`/app/output/report.json`), `--catalog-db` (`/app/state/catalog.sqlite`), `--exclude-sources` (none), `--sample` (debug: crawl only first N sources per provider), `--max-jobs-per-source`, `--max-age-hours`, `--progress-every-ms` (10000), `--provider-concurrency` (parsed as `k=v,k=v` pairs; embedded defaults `{ashby: 2, bamboohr: 10, workday: 5, teamtailor: 10, workable: 10, icims: 5}` — note **`docker-compose.yml`'s command always overrides these** in the real deployment, so this default is only exercised in CLI-standalone/local use, per porting discipline #5's sibling note), `--timeout-ms` (15000), `--retries` (2), `--progress-file` (`/app/state/crawler-progress.json`). `--catalog-file` is **not** ported (dropped per the resolved decision above).

**Acceptance Criteria:**
- [ ] `--provider-concurrency ashby=1,workday=4` parses into the same dict shape `runner.py` expects, overriding the embedded defaults only for the providers mentioned.
- [ ] Running with no arguments at all produces the same defaults as the TS version, field for field.

---

### STORY 7.2 — Entrypoint & Lock-File Lifecycle

**Goal:** Absorb `docker-entrypoint.sh`'s responsibilities directly into Python — this is explicitly called out in porting discipline #7 as easy to accidentally leave behind.

**Instructions:**
1. `main.py`'s `main()`: before invoking the crawl, write a UTC timestamp to the lock file path (`CRAWLER_ACTIVE_LOCK_PATH` env var, default `/app/state/crawler-active.lock`). Wrap the entire crawl invocation in `try/finally`, removing the lock file in `finally` — this must fire on success, on any exception, and (as best-effort as Python signal handling allows) on SIGTERM/SIGINT, matching the shell version's `trap cleanup EXIT INT TERM`.
2. After a successful crawl (exit code 0 equivalent — no unhandled exception), invoke `post_crawl.py`'s logic (Story 7.3) in-process — no more separate `post-crawl.sh` shell step.
3. After the crawl completes (success or failure): delete the progress file (best-effort, matching the TS `unlink().catch(() => undefined)` swallow-on-failure behavior), call `trend_log.append_trend_entry` (non-fatal, catch and log), print a summary JSON to stdout.
4. Exit code propagation: non-zero if the crawl itself failed; the lock-file cleanup and progress-file cleanup must still run regardless (this is exactly what the `finally`/`trap` semantics guarantee — don't let an exception in cleanup mask the crawl's own real exit status, and don't let a cleanup failure prevent reporting the crawl's actual outcome).

**Acceptance Criteria:**
- [ ] The lock file exists for the full duration of a crawl and is removed immediately after, including when the crawl raises an exception partway through — a test that forces a mid-crawl exception and asserts the lock file is gone afterward.
- [ ] `viewer/backend/services/saved_search.py`'s `is_crawler_active()` (file existence + mtime freshness against `CRAWLER_ACTIVE_LOCK_STALE_MS`) needs zero code changes — verify by running it against the new Python crawler's lock-file behavior directly, not just by inspection.
- [ ] A crawl that itself fails (non-zero equivalent) does **not** run `post_crawl.py`'s logic — matches the shell version's `&& post-crawl.sh` short-circuit.

---

### STORY 7.3 — Post-Crawl Exclusion Appending

**Goal:** Port `post-crawl.sh` (currently shell + `jq` + `grep`) into pure Python, removing the `jq`/fragile-grep-on-JSON-key-order dependency entirely.

**Instructions:**
1. `post_crawl.py::run(report_path: str, exclude_path: str)`: read `report.json`'s `failures[]`, filter to entries with `status in {404, 410}`.
2. De-duplicate against existing `exclude.jsonl` entries — the shell version does this via a `grep` pattern relying on `jq`'s stable key ordering; in Python, just parse `exclude.jsonl` into a `set[tuple[provider, source_key]]` (or reuse `exclusions.py`'s loader from Story 4.2) and compare structurally instead of textually. This is a correctness improvement over the shell version's implicit-key-order fragility, and is explicitly approved — not a "must match exactly" case, since the *intent* (don't double-append the same exclusion) is what needs preserving, not the specific grep mechanism.
3. Append new exclusions as `{"provider": ..., "source_key": ..., "reason": "http_404", "last_http_status": ..., "last_seen_at": <now>}` — one JSON object per line, appended (not rewriting the whole file).

**Acceptance Criteria:**
- [ ] Running post-crawl twice against the same report does not duplicate exclusion entries the second time.
- [ ] A 500-status failure in the report is not added to the exclusion list — only 404/410.
- [ ] `exclude.jsonl` remains valid JSONL (one object per line) after multiple appends across multiple crawl runs.

---

## EPIC 8 — Docker & Compose Wiring

---

### STORY 8.1 — Dockerfile

**Goal:** Replace the multi-stage Node build with a single-stage Python image, dropping the native-toolchain dependency entirely.

**Instructions:**
1. New `crawler/Dockerfile`:
   ```dockerfile
   FROM python:3.12-slim
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY . .
   CMD ["python", "main.py"]
   ```
   No `python3 make g++` toolchain needed (that was solely for compiling `better-sqlite3`'s native bindings) — this is a genuine, concrete simplification worth calling out when this story lands.
2. `requirements.txt`: `httpx`, `python-dateutil` (for the relative/lenient date parsing needed in Workday/TeamTailor per porting discipline #8) — no XML library needed if using stdlib `xml.etree.ElementTree`.
3. `Dockerfile.dev`, `requirements-dev.txt`, `pyproject.toml` (ruff + black + pytest + `fail_under = 70` coverage), mirroring `matcher/`'s and `scheduler/`'s already-established pattern exactly.
4. Update `docker-compose.yml`'s `crawler` service: the `command:` array's flags (`--concurrency`, `--provider-concurrency`, `--timeout-ms`, `--retries`, `--exclude-sources`, `--catalog-db`) need **no changes** — same CLI flags, now parsed by Python's `argparse` instead of the TS parser. **Remove** the `--catalog-file` line and its value — that flag is dropped (resolved decision above), and the Python CLI doesn't recognize it.
5. Delete `crawler/tsconfig.json`, `crawler/package.json`, `crawler/package-lock.json` (or whichever lockfile exists) once the Python version is verified working end-to-end — not before, matching this session's established pattern of deleting the old implementation only after the replacement is proven (see the scheduler rewrite's `entrypoint.sh`/`crontab` deletion timing in the just-merged Epic 16-17 PR).

**Acceptance Criteria:**
- [ ] `docker compose build crawler` succeeds with no `make`/`g++`/`node`/`npm` anywhere in the build log.
- [ ] `docker compose run --rm crawler --help` (or equivalent) prints the same flag list as the TS version did.
- [ ] Image size is meaningfully smaller than the current multi-stage Node build (a concrete, checkable side benefit of dropping the native-compile toolchain — verify with `docker images`, don't just assume).

---

## EPIC 9 — Testing & Verification

---

### STORY 9.1 — Unit Test Suite

**Goal:** Real coverage, not just parity with the TS version's thin 19-test suite (which had zero direct coverage of `catalog-store.ts`, `dead-slugs.ts`, `geo.ts`, `trend-log.ts`, or `cli.ts`'s parser, and zero coverage at all of iCIMS).

**Instructions:**
1. Mirror the matcher rewrite's testing methodology exactly: mock only the network boundary (`httpx.AsyncClient` responses), exercise real parsing/classification/persistence logic against realistic fixture data per provider.
2. Explicit new coverage beyond what existed in TS: `catalog_store.py` (upsert/finalize/ensure_column — Story 3.1/3.2's acceptance criteria), `dead_slugs.py` (TTL expiry, race-condition-adjacent behavior), `geo.py` (non-ASCII location strings), `cli.py`/`config.py`'s argument parsing, and `providers/icims.py` (zero coverage previously).
3. `pyproject.toml`: `fail_under = 70`, matching every other service's threshold this session — but given the higher-risk provider logic (Workday, TeamTailor), target real coverage well above that floor for `providers/workday.py` and `providers/teamtailor.py` specifically, same spirit as the matcher's guardrail-function coverage.

**Acceptance Criteria:**
- [ ] `just crawler-test` (new `justfile` recipe, mirroring `matcher-test`/`scheduler-test`) passes with coverage `>= 70%` project-wide.
- [ ] Every provider has a dedicated test file exercising both success and at least one realistic failure/edge case (empty response, missing optional field, HTTP error).
- [ ] The full acceptance-criteria list from every story in Epics 1–7 above is captured as an actual passing test, not just prose.

---

### STORY 9.2 — Docker Verification

**Goal:** Confirm the ported crawler actually works against the real `docker-compose.yml`, following this session's established verification methodology (build the real image, run it, check real logs — not just mocked unit tests) that caught 3 real bugs during the viewer/matcher/scheduler rewrite (the `profile.yml` key mismatch, the scheduler's missing `docker` CLI binary, and the FTS5 `content_rowid` mismatch).

**Instructions:**
1. Build the real `crawler/Dockerfile` image standalone.
2. Run it against a **small, safe subset** of real or sample source data (not the full 9-provider, thousands-of-companies production source list) — verify it produces a valid `catalog.sqlite`, a valid `jobs.jsonl`, a valid `report.json`, and correctly-shaped `crawler-progress.json` updates during the run.
3. Verify the lock-file lifecycle end-to-end: confirm `crawler-active.lock` exists during the run and is gone immediately after, including in a forced-failure scenario.
4. Cross-check with `viewer/`: point a running viewer instance at the crawler-produced `catalog.sqlite` and confirm `/api/jobs`, `/api/stats`, and `/api/crawl-status` all work against real (Python-crawler-produced) data — this is the actual end-to-end contract check, not just "the crawler ran without crashing."
5. Same safety boundary as every other live-verification story this session (9.3, 15.2, 17.2, and the just-merged docker-compose-up bugfix pass): a full production run against real external ATS APIs and the real 9,937-slug iCIMS source list needs the user's explicit go-ahead before running, since it makes real external network requests at scale. Verify against sample/small data yourself; defer the full-scale run.

**Acceptance Criteria:**
- [ ] `docker compose build crawler && docker compose run --rm crawler` (against sample source data) completes and produces all three expected output artifacts.
- [ ] `crawler-active.lock` lifecycle verified directly (not just by code inspection) in both success and forced-failure runs.
- [ ] A viewer instance pointed at the resulting `catalog.sqlite` serves jobs correctly through `/api/jobs` — the real cross-service contract, exercised for real.
- [ ] Full-scale real-source-list run explicitly deferred pending user go-ahead, documented the same way Story 9.3/15.2/17.2 were.

---

## Story Dependency Graph (Execution Order)

### Critical Path (must be sequential)

1. `1.1` Core types
2. `1.2` HTTP client
3. `2.1` Normalizers
4. `2.2` Geo resolution
5. `3.1` Catalog store schema/upsert
6. `3.2` Finalize/export/trend-log
7. `4.1` Source loading
8. `4.2` Dead-slugs & exclusions
9. `5.1` Simple JSON providers
10. `5.2` SmartRecruiters
11. `5.3` TeamTailor
12. `5.4` Workable
13. `5.5` Workday
14. `5.6` iCIMS
15. `6.1` Concurrency model
16. `6.2` Progress/output writers
17. `7.1` CLI parsing
18. `7.2` Entrypoint & lock lifecycle
19. `7.3` Post-crawl
20. `8.1` Docker/compose wiring
21. `9.1` Unit tests
22. `9.2` Docker verification

### Dependency Matrix

| Story | Depends on | Notes |
|---|---|---|
| `1.1` | — | Foundation |
| `1.2` | — | Independent of 1.1, can run in parallel |
| `2.1` | — | Pure logic, independent |
| `2.2` | — | Pure logic, independent |
| `3.1` | `1.1`, `2.1`, `2.2` | Upsert calls classify_tier/canonicalize/resolve_coords inline |
| `3.2` | `3.1` | Same store class |
| `4.1` | `1.1` | Needs SourceEntry/SourceFile types |
| `4.2` | `1.2` | dead_slugs needs HttpError's status field |
| `5.1`-`5.6` | `1.1`, `1.2`, `2.1` | Every provider needs types + http client; classify_tier is applied at catalog-write time, not provider time, but providers should still be built against final NormalizedJob shape |
| `6.1` | `4.1`, `4.2`, `5.1`-`5.6` | Needs providers to orchestrate |
| `6.2` | `6.1`, `3.1` | Needs concurrency model + catalog store |
| `7.1` | — | Independent, can start early |
| `7.2` | `6.2`, `7.1` | Needs the runner + CLI to invoke |
| `7.3` | `4.2` | Reuses exclusion-list loading |
| `8.1` | `7.2`, `7.3` | Containerize completed service |
| `9.1` | All of Epics 1-7 | Comprehensive suite |
| `9.2` | `8.1` | Final live verification |

### Parallel Work Lanes

- Lane A (Foundation): `1.1` + `1.2` + `2.1` + `2.2` — all independent, can run fully in parallel.
- Lane B (Persistence): `3.1` → `3.2` (starts once Lane A's `1.1`/`2.1`/`2.2` land).
- Lane C (Sources): `4.1` → `4.2` (starts once `1.1`/`1.2` land).
- Lane D (Providers): `5.1` → `5.2` → `5.3` → `5.4` → `5.5` → `5.6`, or parallelize across providers once `1.1`/`1.2`/`2.1` land — providers don't depend on each other.
- Lane E (CLI): `7.1` — fully independent, can start on day 1.

### Suggested Sprint Plan (stacked-branch batches, ~5 stories each, matching this session's PR cadence)

- Batch 1: `1.1`, `1.2`, `2.1`, `2.2`, `4.1`
- Batch 2: `3.1`, `3.2`, `4.2`, `5.1`, `7.1`
- Batch 3: `5.2`, `5.3`, `5.4`, `5.5`, `5.6`
- Batch 4: `6.1`, `6.2`, `7.2`, `7.3`
- Batch 5: `8.1`, `9.1`, `9.2`

---

## Risk Table

| ID | Risk | Symptom | Mitigation | Fallback |
|---|---|---|---|---|
| R1 | Workday's relative-date parsing or compensation-guard regex silently diverges from the TS version | Jobs get wrong/missing `posted_at` or `compensation` for the highest-volume provider | Port both regexes verbatim (porting discipline #6/#8); test against real captured API responses, not synthetic examples | Keep the TS crawler running in parallel against a separate DB, diff output before cutover |
| R2 | Concurrency model doesn't compose global-pool + per-provider-semaphore correctly | Some provider gets crawled far slower/faster than the tuned `docker-compose.yml` overrides intend, or the whole crawl takes much longer wall-clock | Story 6.1's explicit peak-concurrency-per-provider test | Fall back to fully sequential per-provider crawling (slow but correct) while debugging |
| R3 | `content_rowid=rowid` / composite-PK schema assumptions get accidentally violated by a "cleaner" Python schema | Viewer's FTS5 search breaks again, same class of bug just fixed in the merged PR | Story 3.1 ports the schema byte-for-byte from `catalog-store.ts`, cross-checked against the already-fixed `viewer/backend/db.py` | Contract test (Story 9.2) that runs the real viewer against the new crawler's DB output |
| R4 | Progress-file JSON shape drifts from what `config_router.py` expects | `/api/crawl-status` returns malformed/incomplete data to the frontend, crawl-status UI breaks silently (no error, just wrong data) | Story 6.2's byte-comparable progress-shape acceptance criterion | Snapshot a real TS-version `crawler-progress.json` before starting the port, diff against it |
| R5 | Full-scale real-source-list crawl behaves differently under Python's asyncio vs Node's event loop (e.g. different effective concurrency under GIL contention with CPU-bound geo/classification work interleaved with I/O) | Crawl takes substantially longer wall-clock in production even though unit tests pass | `asyncio` + `httpx` is I/O-bound like the TS version (GIL isn't the bottleneck for network-wait-dominated work); if geo resolution's Unicode normalization proves CPU-heavy at scale, consider `run_in_executor` for that specific call | Reduce global concurrency default if real-world throughput regresses, tune from there |

---

## Release Gates

- **Gate A (Provider parity):** Epics 1–5 complete, every provider's normalize function has a passing test with output matching the TS version's fixtures. ✅ Passed (Batches 1–3).
- **Gate B (Orchestration parity):** Epic 6 complete, concurrency/progress/output-shape acceptance criteria all pass. ✅ Passed (Batch 4).
- **Gate C (Dockerized, contract-verified):** Epics 7–9 complete, Story 9.2's live viewer-against-real-crawler-output check passes. ✅ Passed (Batch 5) — verified via a real standalone Docker run against sample sources plus one real Greenhouse board (Asana, 126 real jobs), with a real viewer instance pointed at the resulting `catalog.sqlite` confirming `/api/jobs`, `/api/stats`, and `/api/crawl-status` all serve correctly. Lock-file lifecycle verified in both success and forced-failure runs.

`crawler/src/` (the TypeScript source), `docker-entrypoint.sh`, `post-crawl.sh`, `package.json`, `package-lock.json`, and `tsconfig.json` were deleted in Batch 5 now that Gate C has passed.
