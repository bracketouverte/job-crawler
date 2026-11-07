"""Daily trend snapshot. Ported from crawler/src/trend-log.ts.

Opens catalog.sqlite read-only and appends one JSON line to
{state_dir}/trends.jsonl. Called non-fatally from main.py -- a failure
here (e.g. catalog.sqlite not yet created) must not fail the crawl.
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def append_trend_entry(db_path: str, state_dir: str) -> None:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        total = db.execute("SELECT COUNT(*) FROM catalog_jobs").fetchone()[0]

        by_provider = {
            row[0]: row[1]
            for row in db.execute("SELECT provider, COUNT(*) FROM catalog_jobs GROUP BY provider").fetchall()
        }
        by_tier = {
            row[0]: row[1]
            for row in db.execute(
                "SELECT skill_tier, COUNT(*) FROM catalog_jobs "
                "WHERE skill_tier IS NOT NULL GROUP BY skill_tier"
            ).fetchall()
        }

        entry = {
            "date": datetime.now(UTC).date().isoformat(),
            "total": total,
            "by_provider": by_provider,
            "by_tier": by_tier,
        }

        with open(Path(state_dir) / "trends.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    finally:
        db.close()
