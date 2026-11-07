"""Per-provider TTL quarantine cache for 404/410 sources.

Ported from crawler/src/dead-slugs.ts. TTL is randomized 3-10 days
inclusive *per mark*, not a fixed value; expired entries are pruned at
read time on every load() call, not via a background job.

Note (porting discipline, preserved not fixed): mark_dead() does a
read-modify-write of the whole per-provider JSON file with no locking,
so two concurrent workers marking different sources dead for the same
provider can clobber each other's writes. This race is pre-existing in
the TypeScript version and accepted as-is.
"""

import json
import random
from datetime import UTC, datetime
from pathlib import Path

DEAD_STATUSES = {404, 410}


def _random_ttl_days() -> int:
    return 3 + random.randint(0, 7)  # 3-10 days inclusive


def _file_path(state_dir: str, provider: str) -> Path:
    return Path(state_dir) / f"dead_slugs_{provider}.json"


def _is_expired(entry: dict) -> bool:
    dead_at = datetime.fromisoformat(entry["deadAt"].replace("Z", "+00:00"))
    age_days = (datetime.now(UTC) - dead_at).total_seconds() / 86_400
    return age_days > entry["ttlDays"]


def _load(state_dir: str, provider: str) -> dict:
    path = _file_path(state_dir, provider)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}

    pruned = False
    for slug in list(data.keys()):
        if _is_expired(data[slug]):
            del data[slug]
            pruned = True
    if pruned:
        _save(state_dir, provider, data)
    return data


def _save(state_dir: str, provider: str, data: dict) -> None:
    try:
        path = _file_path(state_dir, provider)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass  # non-fatal -- state dir may not exist yet


def load_dead_slugs(state_dir: str, provider: str) -> set[str]:
    return set(_load(state_dir, provider).keys())


def mark_dead(state_dir: str, provider: str, slug: str, code: int) -> None:
    if code not in DEAD_STATUSES:
        return
    data = _load(state_dir, provider)
    data[slug] = {
        "deadAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "code": code,
        "ttlDays": _random_ttl_days(),
    }
    _save(state_dir, provider, data)
