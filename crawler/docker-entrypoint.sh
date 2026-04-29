#!/bin/sh
# Docker entrypoint: Run crawler, then post-crawl hook

set -e

echo "[ENTRYPOINT] Starting crawler..."
node /app/dist/cli.js "$@"
CRAWLER_EXIT=$?

if [ $CRAWLER_EXIT -eq 0 ]; then
  echo "[ENTRYPOINT] ✅ Crawler completed successfully"
  echo "[ENTRYPOINT] Running post-crawl hook..."
  /app/post-crawl.sh
  POST_EXIT=$?
  
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
