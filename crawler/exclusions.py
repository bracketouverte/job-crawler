"""--exclude-sources JSONL loader.

Ported from the loadExcludedSources/exclusionKey functions inline in
runner.ts. A source is excluded if it appears in this list OR in
dead_slugs's TTL cache -- the two mechanisms are separate and both
stay separate here (porting discipline: do not merge them).

Unlike source_loader's missing-source-file soft-fail, a missing
--exclude-sources file *raises* here if a path was actually given (only
omitting the flag entirely is a no-op) -- matching runner.ts exactly.
"""

import json

from models import Provider
from source_loader import is_provider


def exclusion_key(provider: str, key: str) -> str:
    return f"{provider}:{key}"


def load_excluded_sources(file_path: str | None) -> set[str]:
    if file_path is None:
        return set()

    with open(file_path, encoding="utf-8") as f:
        raw = f.read()

    excluded: set[str] = set()
    lines = raw.splitlines()

    for index, line in enumerate(lines):
        if line.strip() == "":
            continue

        try:
            parsed = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"{file_path}:{index + 1} is not valid JSON: {exc}") from exc

        if not isinstance(parsed, dict):
            raise ValueError(f"{file_path}:{index + 1} must be a JSON object")

        provider = parsed.get("provider") if parsed.get("provider") is not None else parsed.get("ats")
        source_key_value = (
            parsed.get("source_key") if parsed.get("source_key") is not None else parsed.get("identifier")
        )

        if not isinstance(provider, str) or not is_provider(provider):
            raise ValueError(f'{file_path}:{index + 1} has unsupported provider "{provider}"')
        if not isinstance(source_key_value, str) or source_key_value == "":
            raise ValueError(f"{file_path}:{index + 1} must contain a non-empty source_key")

        excluded.add(exclusion_key(provider, source_key_value))

    return excluded


def is_excluded(excluded: set[str], provider: Provider, key: str) -> bool:
    return exclusion_key(provider, key) in excluded
