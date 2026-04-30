#!/bin/sh
# Docker entrypoint: Run crawler, then post-crawl hook

set -e

LOCK_FILE="${CRAWLER_ACTIVE_LOCK_PATH:-/app/state/crawler-active.lock}"
mkdir -p "$(dirname "$LOCK_FILE")"
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$LOCK_FILE"
cleanup() {
  rm -f "$LOCK_FILE"
}
trap cleanup EXIT INT TERM

echo "[ENTRYPOINT] Starting crawler..."
set +e
node /app/dist/cli.js "$@"
CRAWLER_EXIT=$?
set -e

if [ $CRAWLER_EXIT -eq 0 ]; then
  echo "[ENTRYPOINT] ✅ Crawler completed successfully"
  echo "[ENTRYPOINT] Running post-crawl hook..."
  set +e
  /app/post-crawl.sh
  POST_EXIT=$?
  set -e
  
  if [ $POST_EXIT -eq 0 ]; then
    echo "[ENTRYPOINT] ✅ Post-crawl hook completed"
    exit 0
  else
    echo "[ENTRYPOINT] ❌ Post-crawl hook failed with exit code $POST_EXIT"
    exit $POST_EXIT
  fi
else
  echo "[ENTRYPOINT] ❌ Crawler failed with exit code $CRAWLER_EXIT"
  exit $CRAWLER_EXIT
fi
