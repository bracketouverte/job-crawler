"""Loads and validates sources/*.json.

Ported from crawler/src/source-loader.ts. A missing file soft-fails (warns,
returns an empty company list) — every other validation failure raises,
matching the TS version exactly.
"""

import json
from pathlib import Path

from models import PROVIDERS, Provider, SourceEntry, SourceFile

_PROVIDER_SET = set(PROVIDERS)


def source_key(source: SourceEntry) -> str:
    if source.identifier is not None:
        return source.identifier
    return f"{source.tenant}/{source.shard}/{source.site}"


def is_provider(value: str) -> bool:
    return value in _PROVIDER_SET


def parse_provider_list(value: str) -> list[Provider]:
    if value == "all":
        return list(PROVIDERS)

    selected = [item.strip() for item in value.split(",") if item.strip()]
    if not selected:
        raise ValueError("--providers must not be empty")

    for item in selected:
        if not is_provider(item):
            raise ValueError(f"Unsupported provider \"{item}\". Expected one of: {', '.join(PROVIDERS)}, all")

    return selected  # type: ignore[return-value]


def _validate_source(provider: Provider, source: object, label: str) -> None:
    if not isinstance(source, dict):
        raise ValueError(f"{label} must be an object")

    if provider == "workday":
        for key in ("tenant", "shard", "site"):
            if not isinstance(source.get(key), str) or source.get(key) == "":
                raise ValueError(f"{label}.{key} must be a non-empty string")
        return

    if not isinstance(source.get("identifier"), str) or source.get("identifier") == "":
        raise ValueError(f"{label}.identifier must be a non-empty string")


def load_source_file(sources_dir: str, provider: Provider) -> SourceFile:
    file_path = Path(sources_dir) / f"{provider}.json"
    if not file_path.exists():
        print(f'[source-loader] {file_path} not found, skipping provider "{provider}"')
        return SourceFile(provider=provider, companies=[])

    with open(file_path, encoding="utf-8") as f:
        parsed = json.load(f)

    if parsed.get("provider") != provider:
        raise ValueError(f'{file_path} declares provider "{parsed.get("provider")}", expected "{provider}"')
    companies_raw = parsed.get("companies")
    if not isinstance(companies_raw, list):
        raise ValueError(f"{file_path} must contain a companies array")
    for key in ("url_template", "jobid_template"):
        if key in parsed and parsed[key] is not None and not isinstance(parsed[key], str):
            raise ValueError(f"{file_path}.{key} must be a string when present")

    for index, source in enumerate(companies_raw):
        _validate_source(provider, source, f"{file_path} companies[{index}]")

    companies = [
        SourceEntry(
            identifier=source.get("identifier"),
            tenant=source.get("tenant"),
            shard=source.get("shard"),
            site=source.get("site"),
        )
        for source in companies_raw
    ]

    return SourceFile(
        provider=provider,
        url_template=parsed.get("url_template"),
        jobid_template=parsed.get("jobid_template"),
        companies=companies,
    )
