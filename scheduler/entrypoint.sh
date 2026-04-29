#!/bin/sh
set -e

RUNS_FILE="/state/scheduler-runs.json"

record_run() {
  now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  if [ -f "$RUNS_FILE" ]; then
    runs=$(cat "$RUNS_FILE")
  else
    runs="[]"
  fi
  printf '%s' "$runs" | jq --arg ts "$now" '. + [$ts] | .[-10:]' > "$RUNS_FILE"
}

# Returns how many minutes ago the last run was (99999 if never)
last_run_minutes_ago() {
  if [ ! -f "$RUNS_FILE" ]; then
    echo "99999"
    return
  fi
  last=$(jq -r '.[-1] // empty' "$RUNS_FILE")
  if [ -z "$last" ]; then
    echo "99999"
    return
  fi
  now_epoch=$(date -u +%s)
  last_epoch=$(jq -n --arg ts "$last" '$ts | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime')
  echo $(( (now_epoch - last_epoch) / 60 ))
}

run_crawler() {
  echo "[SCHEDULER] Triggering crawler..."
  record_run
  docker compose -f /project/docker-compose.yml --project-directory "${PROJECT_DIR}" run --rm crawler || true
  echo "[SCHEDULER] Crawler done."
}

maybe_run() {
  minutes=$(last_run_minutes_ago)
  if [ "$minutes" -lt 110 ]; then
    echo "[SCHEDULER] Last run was ${minutes}m ago, skipping."
    return
  fi
  run_crawler
}

# Called from cron
if [ "${1:-}" = "cron" ]; then
  maybe_run
  exit 0
fi

# Write crontab with resolved PROJECT_DIR (crond doesn't expand env vars)
cat > /etc/crontabs/root <<EOF
0 8,10,12,14,16,18,20 * * * PROJECT_DIR="${PROJECT_DIR}" /entrypoint.sh cron >> /var/log/scheduler.log 2>&1
EOF

# On container start: run immediately if in 8-20 window, then start crond
hour=$(date +%H | sed 's/^0*//' | grep . || echo 0)
if [ "$hour" -ge 8 ] && [ "$hour" -le 20 ]; then
  echo "[SCHEDULER] In window (hour=$hour), checking last run..."
  maybe_run
else
  echo "[SCHEDULER] Outside window (hour=$hour), skipping startup run."
fi

echo "[SCHEDULER] Starting crond..."
exec crond -f -l 6
