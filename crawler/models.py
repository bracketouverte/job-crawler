"""Core data shapes shared across the crawler.

Ported from crawler/src/types.ts — field names and shapes are kept
identical since NormalizedJob's fields map 1:1 onto catalog_store.py's
upsert column list.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from http_client import HttpClient

Provider = Literal[
    "ashby",
    "bamboohr",
    "greenhouse",
    "icims",
    "lever",
    "smartrecruiters",
    "teamtailor",
    "workable",
    "workday",
]

PROVIDERS: tuple[Provider, ...] = (
    "ashby",
    "bamboohr",
    "greenhouse",
    "icims",
    "lever",
    "smartrecruiters",
    "teamtailor",
    "workable",
    "workday",
)


@dataclass
class SourceEntry:
    """Identifier-based for 8 providers; tenant/shard/site for Workday."""

    identifier: str | None = None
    tenant: str | None = None
    shard: str | None = None
    site: str | None = None

    @property
    def is_workday(self) -> bool:
        return self.tenant is not None


@dataclass
class SourceFile:
    provider: Provider
    url_template: str | None = None
    jobid_template: str | None = None
    companies: list[SourceEntry] = field(default_factory=list)


@dataclass
class NormalizedJob:
    provider: Provider
    source_key: str
    job_id: str
    fetched_at: str
    title: str | None = None
    location: str | None = None
    employment_type: str | None = None
    compensation: str | None = None
    department: str | None = None
    office: str | None = None
    language: str | None = None
    updated_at: str | None = None
    posted_at: str | None = None
    job_url: str | None = None
    skill_tier: str | None = None


@dataclass
class CrawlFailure:
    provider: Provider
    source_key: str
    message: str
    status: int | None = None


@dataclass
class SourceExclusion:
    provider: Provider
    source_key: str
    reason: str | None = None
    last_http_status: int | None = None
    last_seen_at: str | None = None


@dataclass
class ProviderStats:
    sources: int = 0
    skipped: int = 0
    succeeded: int = 0
    failed: int = 0
    jobs: int = 0


@dataclass
class CrawlReport:
    started_at: str
    ended_at: str
    source_counts: dict[str, int]
    skipped_sources: int
    skipped_by_provider: dict[str, int]
    providers: dict[str, ProviderStats]
    total_jobs: int
    failures: list[CrawlFailure]


@dataclass
class CrawlContext:
    http: "HttpClient"
    fetched_at: str
    max_jobs_per_source: int | None = None
    url_template: str | None = None
    jobid_template: str | None = None


class ProviderCrawler(Protocol):
    provider: Provider

    async def crawl(self, source: SourceEntry, context: CrawlContext) -> list[NormalizedJob]: ...
