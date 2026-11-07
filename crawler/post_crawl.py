"""Post-crawl hook. Ported from post-crawl.sh (previously shell + jq + grep).

Appends new 404/410 failures from report.json to exclude.jsonl.
Deduplication against existing entries is done structurally
(provider, source_key) via exclusions.py's loader (Story 4.2), replacing
the shell version's grep-on-JSON-text pattern that relied on jq's stable
key ordering -- a correctness improvement, not a "must match textually"
requirement; the intent (don't double-append the same exclusion) is what
needs preserving, not the specific grep mechanism.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from exclusions import exclusion_key, load_excluded_sources

_EXCLUDABLE_STATUSES = {404, 410}


def run(report_path: str, exclude_path: str) -> int:
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    Path(exclude_path).parent.mkdir(parents=True, exist_ok=True)
    if not Path(exclude_path).exists():
        Path(exclude_path).touch()

    existing = load_excluded_sources(exclude_path)

    added = 0
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(exclude_path, "a", encoding="utf-8") as f:
        for failure in report.get("failures", []):
            status = failure.get("status")
            if status not in _EXCLUDABLE_STATUSES:
                continue

            provider = failure.get("provider")
            source = failure.get("source_key")
            key = exclusion_key(provider, source)
            if key in existing:
                continue

            existing.add(key)
            f.write(
                json.dumps(
                    {
                        "provider": provider,
                        "source_key": source,
                        "reason": "http_404",
                        "last_http_status": status,
                        "last_seen_at": now,
                    }
                )
                + "\n"
            )
            added += 1

    return added
