"""TeamTailor provider. Ported from crawler/src/providers/teamtailor.ts.

TeamTailor exposes jobs as an RSS feed at https://{slug}.teamtailor.com/jobs.rss.
The TS version parses XML with fast-xml-parser configured to keep namespace
prefixes literal (removeNSPrefix: false), so "teamtailor:department" and
"teamtailor:location" become dict keys exactly as written. xml.etree's
ElementTree resolves namespaces instead (Clark notation, {uri}localname) --
an idiomatic substitute for the XML library itself (I/O/tooling boundary),
not the extraction logic. We match on the stripped localname
("department"/"location") rather than the literal prefixed string.
"""

import xml.etree.ElementTree as ET
from datetime import UTC

from dateutil import parser as date_parser

from models import CrawlContext, NormalizedJob, SourceEntry
from normalizers import first_string, join_strings

provider = "teamtailor"


async def crawl(source: SourceEntry, context: CrawlContext) -> list[NormalizedJob]:
    identifier = source.identifier
    xml_text = await context.http.get_text(f"https://{identifier}.teamtailor.com/jobs.rss")
    items = _parse_items(xml_text)
    return [normalize_teamtailor_job(identifier, item, context.fetched_at) for item in items]


def normalize_teamtailor_job(source_key: str, item: dict, fetched_at: str) -> NormalizedJob:
    link = first_string(item.get("link"))
    job_id = first_string(item.get("guid"), link, item.get("title")) or "unknown"
    parsed_date = _parse_date(first_string(item.get("pubDate")))
    return NormalizedJob(
        provider="teamtailor",
        source_key=source_key,
        job_id=job_id,
        title=first_string(item.get("title")),
        location=first_string(item.get("location")),
        employment_type=None,
        compensation=None,
        department=first_string(item.get("department"), join_strings(item.get("category"))),
        office=None,
        language=None,
        updated_at=parsed_date,
        posted_at=parsed_date,
        job_url=link,
        fetched_at=fetched_at,
    )


def _localname(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _parse_items(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for element in root.iter():
        if _localname(element.tag) != "item":
            continue
        item: dict[str, list[str] | str] = {}
        for child in element:
            key = _localname(child.tag)
            text = (child.text or "").strip()
            if key in item:
                existing = item[key]
                if isinstance(existing, list):
                    existing.append(text)
                else:
                    item[key] = [existing, text]
            else:
                item[key] = text
        items.append(item)
    return items


def _parse_date(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        dt = date_parser.parse(value)
    except (ValueError, OverflowError):
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
