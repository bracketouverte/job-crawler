# Matcher

The `matcher` module handles two jobs:

- parse a public job-post URL into structured fields
- score job fit against the local profile using NVIDIA NIM

## Main Files

- `job_post_parser.py` parses supported ATS posting URLs into structured JSON
- `job_fit_analyzer.py` scores profile-to-job fit
- `$CAREER_OPS_DIR/profile.yml`, `$CAREER_OPS_DIR/portals.yml`, `$CAREER_OPS_DIR/cv.md`, `$CAREER_OPS_DIR/_profile.md` provide the profile context

Those files are generated local assets from:
https://github.com/santifer/career-ops

They are intentionally ignored by Git in this repo.

## URL Parsing

Extract normalized fields from a posting URL:

```bash
docker compose run --rm job-parser \
  --url 'https://job-boards.greenhouse.io/marqeta/jobs/7711098' \
  --pretty
```

Current output includes:

- `jd_concepts`
- `posted_datetime`
- `location`
- `compensation`
- `workplace_type`
- `employment_type`
- `responsibilities`
- `requirements_summary`

The parser now handles more Greenhouse URL variants, including embedded/custom-hosted job pages where the board token and job ID must be recovered from page metadata.

## Fit Analysis

Run the analyzer on a prepared job description file:

```bash
docker compose run --rm matcher \
  -j /app/some-job.txt \
  -p /app \
  -o /app/job_fit_report.json
```

Batch mode for structured job payloads:

```bash
docker compose run --rm matcher \
  --jobs-jsonl /app/jobs.jsonl \
  --results-jsonl /app/results.jsonl \
  -p /app
```

Dry run:

```bash
docker compose run --rm matcher --dry-run --model meta/llama-4-maverick-17b-128e-instruct -p /app
```

Full-fit ensemble pipeline:

```bash
docker compose run --rm matcher \
  python3 /app/ensemble_runner.py \
  --jobs-jsonl /app/jobs.jsonl \
  --results-jsonl /app/results.jsonl \
  --profile-dir /app/career-ops
```

`job_fit_analyzer.py` is the quick-fit pipeline backed by Maverick. `ensemble_runner.py` is the full-fit pipeline that runs multiple scorer models, then synthesizes them into a final assessment.

## Environment

- `NVIDIA_API_KEY`
- `NVIDIA_MODEL` default: `meta/llama-4-maverick-17b-128e-instruct`

These are forwarded by `docker-compose.yml`.

- `CAREER_OPS_DIR` default: `career-ops`

## Scoring Model

The analyzer now uses a structured scorecard inspired by `career-ops` instead of trusting a single raw LLM score.

Returned `analysis.score` stays on a 0-100 scale for compatibility, but it is recalculated locally from six 1-5 dimensions:

- `core_skills`
- `relevant_experience`
- `target_alignment`
- `seniority_fit`
- `workplace_fit`
- `requirements_coverage`

The output also includes:

- `analysis.scorecard` with dimension reasons
- `analysis.evidence` for explicit requirement-to-profile mapping
- `analysis.requirement_match` for structured gap analysis
- `analysis.blockers` for hard blockers
- `analysis.posting_legitimacy` as a separate signal that does not directly lower fit
- `analysis.pipeline` so quick and full-fit runs can be distinguished downstream
