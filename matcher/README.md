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

## Fit Analysis

Run the analyzer on a prepared job description file:

```bash
docker compose run --rm matcher \
  -j /app/some-job.txt \
  -p /app \
  -o /app/job_fit_report.json
```

Dry run:

```bash
docker compose run --rm matcher --dry-run --model meta/llama-3.1-70b-instruct -p /app
```

## Environment

- `NVIDIA_API_KEY`
- `NVIDIA_MODEL` default: `meta/llama-3.1-70b-instruct`

These are forwarded by `docker-compose.yml`.

- `CAREER_OPS_DIR` default: `career-ops`
