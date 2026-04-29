#!/bin/sh
# Post-crawl hook: Update exclude.jsonl with new 404/410 failures
# Runs inside the container after crawl completes

EXCLUDE_FILE="/app/state/exclude.jsonl"
REPORT_FILE="/app/output/report.json"

echo "[POST-CRAWL] Updating exclude.jsonl with new failures..."

if [ ! -f "$REPORT_FILE" ]; then
  echo "[POST-CRAWL] ERROR: Report file not found at $REPORT_FILE"
  exit 1
fi

if [ ! -f "$EXCLUDE_FILE" ]; then
  echo "[POST-CRAWL] Creating new exclude.jsonl"
  touch "$EXCLUDE_FILE"
fi

# Count new exclusions added
added=0
total_before=$(wc -l < "$EXCLUDE_FILE")

# Extract 404/410 failures and add to exclude.jsonl
jq -r '.failures[] | select(.status == 404 or .status == 410) | @json' "$REPORT_FILE" 2>/dev/null | while read failure; do
  if [ -z "$failure" ]; then continue; fi
  
  provider=$(echo "$failure" | jq -r '.provider')
  source_key=$(echo "$failure" | jq -r '.source_key')
  
  # Check if already excluded (basic dedup)
  if ! grep -q "\"provider\":\"$provider\".*\"source_key\":\"$source_key\"" "$EXCLUDE_FILE" 2>/dev/null; then
    echo "$failure" | jq -c '{provider, source_key, reason: "http_404", last_http_status: .status, last_seen_at: now | todate}' >> "$EXCLUDE_FILE"
  fi
done

total_after=$(wc -l < "$EXCLUDE_FILE")
added=$((total_after - total_before))

echo "[POST-CRAWL] ✅ Exclude.jsonl updated"
echo "[POST-CRAWL] 📊 Added $added new exclusions (total: $total_after sources excluded)"
echo "[POST-CRAWL] Done!"
