"""CLI argument parsing.

Ported from crawler/src/cli.ts's hand-rolled parser, using argparse (an
idiomatic Python substitute -- not required to hand-roll a parser to
match). Flag names, defaults, and validation semantics (positive vs.
non-negative integer) are kept identical.

--catalog-file is dropped (resolved migration-plan decision: unused by
anything in this repo) and is not a recognized flag here.
"""

import argparse
from dataclasses import dataclass, field

from models import PROVIDERS, Provider

DEFAULT_PROVIDER_CONCURRENCY: dict[Provider, int] = {
    "ashby": 2,
    "bamboohr": 10,
    "workday": 5,
    "teamtailor": 10,
    "workable": 10,
    "icims": 5,
}


@dataclass
class CliOptions:
    sources: str = "/data/sources"
    providers: str = "all"
    concurrency: int = 50
    out: str = "/app/output/jobs.jsonl"
    report: str = "/app/output/report.json"
    catalog_db: str = "/app/state/catalog.sqlite"
    exclude_sources: str | None = None
    sample: int | None = None
    max_jobs_per_source: int | None = None
    max_age_hours: int | None = None
    progress_every_ms: int = 10000
    provider_concurrency: dict[Provider, int] = field(
        default_factory=lambda: dict(DEFAULT_PROVIDER_CONCURRENCY)
    )
    timeout_ms: int = 15000
    retries: int = 2
    progress_file: str = "/app/state/crawler-progress.json"


def _positive_int(flag: str):
    def parse(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{flag} must be a positive integer") from None
        if parsed <= 0:
            raise argparse.ArgumentTypeError(f"{flag} must be a positive integer")
        return parsed

    return parse


def _non_negative_int(flag: str):
    def parse(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{flag} must be a non-negative integer") from None
        if parsed < 0:
            raise argparse.ArgumentTypeError(f"{flag} must be a non-negative integer")
        return parsed

    return parse


def parse_provider_concurrency(value: str) -> dict[Provider, int]:
    if value.strip() == "":
        raise ValueError("--provider-concurrency must not be empty")

    limits: dict[Provider, int] = {}
    for entry in value.split(","):
        parts = entry.split("=")
        if len(parts) != 2:
            raise ValueError(f'Invalid provider concurrency entry "{entry}". Expected provider=limit')
        provider_name, limit = parts
        if provider_name not in PROVIDERS:
            raise ValueError(f'Invalid provider concurrency entry "{entry}". Expected provider=limit')
        try:
            parsed_limit = int(limit)
        except ValueError:
            raise ValueError(f"--provider-concurrency {provider_name} must be a positive integer") from None
        if parsed_limit <= 0:
            raise ValueError(f"--provider-concurrency {provider_name} must be a positive integer")
        limits[provider_name] = parsed_limit

    return limits


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crawl", description="Crawl ATS boards into catalog.sqlite")
    parser.add_argument("--sources", default="/data/sources", help="Source JSON directory")
    parser.add_argument("--providers", default="all", help="Providers to crawl")
    parser.add_argument(
        "--concurrency", type=_positive_int("--concurrency"), default=50, help="Global source concurrency"
    )
    parser.add_argument("--out", default="/app/output/jobs.jsonl", help="JSONL output path")
    parser.add_argument("--report", default="/app/output/report.json", help="Report JSON path")
    parser.add_argument(
        "--catalog-db",
        dest="catalog_db",
        default="/app/state/catalog.sqlite",
        help="SQLite catalog state file",
    )
    parser.add_argument(
        "--exclude-sources", dest="exclude_sources", default=None, help="JSONL source quarantine file"
    )
    parser.add_argument(
        "--sample",
        type=_positive_int("--sample"),
        default=None,
        help="Crawl only first n sources per provider",
    )
    parser.add_argument(
        "--max-jobs-per-source",
        dest="max_jobs_per_source",
        type=_positive_int("--max-jobs-per-source"),
        default=None,
        help="Emit at most n jobs per source",
    )
    parser.add_argument(
        "--max-age-hours",
        dest="max_age_hours",
        type=_positive_int("--max-age-hours"),
        default=None,
        help="Keep only jobs where updated_at is within last n hours",
    )
    parser.add_argument(
        "--progress-every-ms",
        dest="progress_every_ms",
        type=_non_negative_int("--progress-every-ms"),
        default=10000,
        help="Progress log interval, 0 disables it",
    )
    parser.add_argument(
        "--provider-concurrency",
        dest="provider_concurrency",
        default=None,
        help="Per-provider limits, e.g. ashby=2,workday=10",
    )
    parser.add_argument(
        "--timeout-ms",
        dest="timeout_ms",
        type=_positive_int("--timeout-ms"),
        default=15000,
        help="Per-request timeout",
    )
    parser.add_argument(
        "--retries", type=_non_negative_int("--retries"), default=2, help="Transient retry count"
    )
    parser.add_argument(
        "--progress-file",
        dest="progress_file",
        default="/app/state/crawler-progress.json",
        help="Progress JSON file path",
    )
    return parser


def parse_args(argv: list[str]) -> CliOptions:
    parser = build_parser()
    namespace = parser.parse_args(argv)

    options = CliOptions(
        sources=namespace.sources,
        providers=namespace.providers,
        concurrency=namespace.concurrency,
        out=namespace.out,
        report=namespace.report,
        catalog_db=namespace.catalog_db,
        exclude_sources=namespace.exclude_sources,
        sample=namespace.sample,
        max_jobs_per_source=namespace.max_jobs_per_source,
        max_age_hours=namespace.max_age_hours,
        progress_every_ms=namespace.progress_every_ms,
        timeout_ms=namespace.timeout_ms,
        retries=namespace.retries,
        progress_file=namespace.progress_file,
    )
    if namespace.provider_concurrency is not None:
        options.provider_concurrency = parse_provider_concurrency(namespace.provider_concurrency)
    return options
