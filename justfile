# Task runner for the Python viewer backend (viewer/backend/) and matcher
# service (matcher/). Everything runs in Docker per this repo's "never run
# npm/python directly" policy.
#
# Usage: just <recipe>   (install https://github.com/casey/just)

set shell := ["bash", "-uc"]

viewer_backend := "viewer/backend"
viewer_image := "job-crawler-viewer-dev"
matcher_dir := "matcher"
matcher_image := "job-crawler-matcher-dev"
scheduler_dir := "scheduler"
scheduler_image := "job-crawler-scheduler-dev"
crawler_dir := "crawler"
crawler_image := "job-crawler-crawler-dev"
uid := `id -u`
gid := `id -g`

# Build (or reuse the cached) viewer backend dev image — deps + lint/test tooling
_viewer-image:
    docker build -q -t {{viewer_image}} -f {{viewer_backend}}/Dockerfile.dev {{viewer_backend}} > /dev/null

# Lint the viewer backend (ruff + black --check); fails on any violation
lint: _viewer-image
    docker run --rm -u {{uid}}:{{gid}} -v "$(pwd)/{{viewer_backend}}:/app" -w /app {{viewer_image}} \
        sh -c "ruff check . && black --check ."

# Auto-fix formatting/lint issues in the viewer backend (ruff --fix + black)
fmt: _viewer-image
    docker run --rm -u {{uid}}:{{gid}} -v "$(pwd)/{{viewer_backend}}:/app" -w /app {{viewer_image}} \
        sh -c "ruff check --fix . && black ."

# Run the viewer backend test suite with coverage (fails under 70%)
test: _viewer-image
    docker run --rm -u {{uid}}:{{gid}} -v "$(pwd)/{{viewer_backend}}:/app" -w /app {{viewer_image}} \
        python -m pytest --cov=. --cov-report=term-missing

# Run the viewer backend dev server with live reload, against real crawler state
dev: _viewer-image
    docker run --rm -it \
        -v "$(pwd)/{{viewer_backend}}:/app" \
        -v "$(pwd)/crawler/state:/app/state" \
        -v "$(pwd)/matcher:/matcher:ro" \
        -p 3000:3000 \
        -e CATALOG_DB=/app/state/catalog.sqlite \
        -e CAREER_OPS_DIR="${CAREER_OPS_DIR:-career-ops}" \
        -e LOGO_DEV_PUBLISHABLE_KEY="${LOGO_DEV_PUBLISHABLE_KEY:-}" \
        -e LOGO_DEV_SECRET_KEY="${LOGO_DEV_SECRET_KEY:-}" \
        -e DISCORD_WEBHOOK_URL="${DISCORD_WEBHOOK_URL:-}" \
        -e SCORE_NOTIFY_MIN_SCORE="${SCORE_NOTIFY_MIN_SCORE:-4}" \
        -e NVIDIA_API_KEY="${NVIDIA_API_KEY:-}" \
        -e NVIDIA_MODEL="${NVIDIA_MODEL:-meta/llama-4-maverick-17b-128e-instruct}" \
        -e NVIDIA_ENSEMBLE_SCORERS="${NVIDIA_ENSEMBLE_SCORERS:-}" \
        -e NVIDIA_ENSEMBLE_SYNTHESIZER="${NVIDIA_ENSEMBLE_SYNTHESIZER:-}" \
        {{viewer_image}}

# Build (or reuse the cached) matcher dev image — deps + lint/test tooling
_matcher-image:
    docker build -q -t {{matcher_image}} -f {{matcher_dir}}/Dockerfile.dev {{matcher_dir}} > /dev/null

# Lint the matcher service (ruff + black --check); fails on any violation
matcher-lint: _matcher-image
    docker run --rm -u {{uid}}:{{gid}} -v "$(pwd)/{{matcher_dir}}:/app" -w /app {{matcher_image}} \
        sh -c "ruff check . && black --check ."

# Auto-fix formatting/lint issues in the matcher service (ruff --fix + black)
matcher-fmt: _matcher-image
    docker run --rm -u {{uid}}:{{gid}} -v "$(pwd)/{{matcher_dir}}:/app" -w /app {{matcher_image}} \
        sh -c "ruff check --fix . && black ."

# Run the matcher test suite with coverage (fails under 70%)
matcher-test: _matcher-image
    docker run --rm -u {{uid}}:{{gid}} -v "$(pwd)/{{matcher_dir}}:/app" -w /app {{matcher_image}} \
        python -m pytest --cov=. --cov-report=term-missing

# Run the matcher dev server with live reload
matcher-dev: _matcher-image
    docker run --rm -it \
        -v "$(pwd)/{{matcher_dir}}:/app" \
        -p 8001:8001 \
        -e CAREER_OPS_DIR="${CAREER_OPS_DIR:-career-ops}" \
        -e STATE_DIR="${STATE_DIR:-/app/state}" \
        -e NVIDIA_API_KEY="${NVIDIA_API_KEY:-}" \
        -e NVIDIA_MODEL="${NVIDIA_MODEL:-meta/llama-4-maverick-17b-128e-instruct}" \
        -e NVIDIA_ENSEMBLE_SCORERS="${NVIDIA_ENSEMBLE_SCORERS:-}" \
        -e NVIDIA_ENSEMBLE_SYNTHESIZER="${NVIDIA_ENSEMBLE_SYNTHESIZER:-}" \
        -e ENSEMBLE_JOB_CONCURRENCY="${ENSEMBLE_JOB_CONCURRENCY:-1}" \
        {{matcher_image}}

# Build (or reuse the cached) scheduler dev image — deps + lint/test tooling
_scheduler-image:
    docker build -q -t {{scheduler_image}} -f {{scheduler_dir}}/Dockerfile.dev {{scheduler_dir}} > /dev/null

# Lint the scheduler service (ruff + black --check); fails on any violation
scheduler-lint: _scheduler-image
    docker run --rm -u {{uid}}:{{gid}} -v "$(pwd)/{{scheduler_dir}}:/app" -w /app {{scheduler_image}} \
        sh -c "ruff check . && black --check ."

# Auto-fix formatting/lint issues in the scheduler service (ruff --fix + black)
scheduler-fmt: _scheduler-image
    docker run --rm -u {{uid}}:{{gid}} -v "$(pwd)/{{scheduler_dir}}:/app" -w /app {{scheduler_image}} \
        sh -c "ruff check --fix . && black ."

# Run the scheduler test suite with coverage (fails under 70%)
scheduler-test: _scheduler-image
    docker run --rm -u {{uid}}:{{gid}} -v "$(pwd)/{{scheduler_dir}}:/app" -w /app {{scheduler_image}} \
        python -m pytest --cov=. --cov-report=term-missing

# Build (or reuse the cached) crawler dev image — deps + lint/test tooling
_crawler-image:
    docker build -q -t {{crawler_image}} -f {{crawler_dir}}/Dockerfile.dev {{crawler_dir}} > /dev/null

# Lint the crawler service (ruff + black --check); fails on any violation
crawler-lint: _crawler-image
    docker run --rm -u {{uid}}:{{gid}} -v "$(pwd)/{{crawler_dir}}:/app" -w /app {{crawler_image}} \
        sh -c "ruff check . && black --check ."

# Auto-fix formatting/lint issues in the crawler service (ruff --fix + black)
crawler-fmt: _crawler-image
    docker run --rm -u {{uid}}:{{gid}} -v "$(pwd)/{{crawler_dir}}:/app" -w /app {{crawler_image}} \
        sh -c "ruff check --fix . && black ."

# Run the crawler test suite with coverage (fails under 70%)
crawler-test: _crawler-image
    docker run --rm -u {{uid}}:{{gid}} -v "$(pwd)/{{crawler_dir}}:/app" -w /app {{crawler_image}} \
        python -m pytest --cov=. --cov-report=term-missing

# Lint the viewer backend, the matcher service, the scheduler service, and the crawler
lint-all: lint matcher-lint scheduler-lint crawler-lint

# Run the viewer backend, matcher, scheduler, and crawler test suites
test-all: test matcher-test scheduler-test crawler-test
