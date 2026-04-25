#!/usr/bin/env python3
"""
Extract structured job-post data from a supported board URL.
"""

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

DEFAULT_TIMEOUT = (10, 60)

RESPONSIBILITY_KEYWORDS_RAW = {
    "responsibilities",
    "responsibility",
    "what youll do",
    "what you'll do",
    "the impact youll have",
    "the impact you'll have",
    "a day in the life",
    "day in the life",
    "what you will do",
    "role",
}

REQUIREMENT_KEYWORDS_RAW = {
    "requirements",
    "requirement",
    "qualifications",
    "qualification",
    "who you are",
    "what youll have",
    "what you'll have",
    "about you",
    "nice to haves",
    "nice to have",
    "what you bring",
    "skills",
}

STOPWORDS = {
    "a", "about", "across", "after", "all", "also", "an", "and", "any", "are", "as", "at", "be", "because",
    "been", "but", "by", "can", "company", "customers", "data", "do", "for", "from", "get", "have", "help",
    "if", "in", "into", "is", "it", "its", "join", "key", "more", "most", "need", "of", "on", "or", "our",
    "role", "team", "that", "the", "their", "them", "this", "to", "us", "using", "we", "what", "who", "will",
    "with", "work", "working", "you", "your",
}


def fetch_json(url, *, method="GET", headers=None, body=None):
    response = requests.request(method, url, headers=headers, json=body, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch_text(url, *, headers=None):
    response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.text


def detect_provider(url):
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path

    if "greenhouse.io" in host:
        return "greenhouse"
    if host == "jobs.ashbyhq.com":
        return "ashby"
    if host.endswith(".bamboohr.com"):
        return "bamboohr"
    if host == "jobs.lever.co":
        return "lever"
    if host.endswith(".teamtailor.com"):
        return "teamtailor"
    if ".myworkdayjobs.com" in host:
        return "workday"

    raise ValueError(f"Unsupported provider for URL: {url}")


def detect_provider_from_page(raw_html):
    lowered = raw_html.lower()
    if "teamtailor" in lowered or "teamtailor-cdn.com" in lowered:
        return "teamtailor"
    if "jobs.ashbyhq.com" in lowered:
        return "ashby"
    return None


def normalize_heading(value):
    value = re.sub(r"[^a-z0-9 ]+", " ", value.lower())
    return " ".join(value.split())


RESPONSIBILITY_KEYWORDS = {normalize_heading(value) for value in RESPONSIBILITY_KEYWORDS_RAW}
REQUIREMENT_KEYWORDS = {normalize_heading(value) for value in REQUIREMENT_KEYWORDS_RAW}


def is_heading(line):
    normalized = normalize_heading(line.rstrip(":"))
    if heading_matches(normalized, RESPONSIBILITY_KEYWORDS) or heading_matches(normalized, REQUIREMENT_KEYWORDS):
        return True
    if line.endswith(":") and len(line.split()) <= 8:
        return True
    return False


def heading_matches(normalized_heading, keywords):
    if normalized_heading in keywords:
        return True
    return any(keyword in normalized_heading for keyword in keywords if len(keyword) >= 6)


def html_to_lines(html_text):
    text = html.unescape(html_text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|ul|ol|h1|h2|h3|h4|h5|h6)>", "\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.I)
    text = re.sub(r"</li>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\xa0", " ")
    lines = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split()).strip()
        if line:
            lines.append(line)
    return lines


def extract_sections_from_html(html_text):
    sections = {}
    current = "general"
    sections[current] = []

    for line in html_to_lines(html_text):
        if is_heading(line):
            current = line.rstrip(":").strip()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)

    return sections


def bulletize(lines, limit=8):
    bullets = []
    for line in lines:
        cleaned = re.sub(r"^[\-\*\u2022]+\s*", "", line).strip()
        if cleaned != line:
            item = cleaned
            if item:
                bullets.append(item)
        else:
            parts = re.split(r"(?<=[.!?])\s+", line)
            for part in parts:
                part = part.strip(" -")
                if len(part) >= 25:
                    bullets.append(part)
        if len(bullets) >= limit:
            break

    seen = set()
    result = []
    for bullet in bullets:
        key = bullet.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(bullet)
        if len(result) >= limit:
            break
    return result


def select_section(sections, keywords):
    for heading, lines in sections.items():
        if heading_matches(normalize_heading(heading), keywords) and lines:
            return lines
    return []


def infer_workplace_type(*values):
    joined = " ".join(value for value in values if value)
    lowered = joined.lower()
    if "hybrid" in lowered:
        return "hybrid"
    if "remote" in lowered or "telecommute" in lowered:
        return "remote"
    if "on-site" in lowered or "onsite" in lowered or "in office" in lowered or "office" in lowered:
        return "on-site"
    return None


def infer_employment_type(*values):
    joined = " ".join(value for value in values if value)
    lowered = joined.lower()
    if re.search(r"\b(full[\s-]?time|permanent)\b", lowered):
        return "full-time"
    if re.search(r"\bpart[\s-]?time\b", lowered):
        return "part-time"
    if re.search(r"\bcontract\b", lowered):
        return "contract"
    if re.search(r"\bintern(ship)?\b", lowered):
        return "internship"
    return None


def infer_compensation(explicit, text):
    if explicit:
        return explicit

    for line in html_to_lines(text):
        lowered = line.lower()
        if re.search(r"[$€£]\s?\d", line) or re.search(r"\b(salary|compensation|ote|hourly|base pay|pay range)\b", lowered):
            return line
    return None


def to_iso_datetime(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value > 1_000_000_000_000:
            value /= 1000.0
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def extract_concepts(title, *blocks, limit=10):
    text = " ".join(block for block in blocks if block)
    words = re.findall(r"[A-Za-z][A-Za-z0-9+/.-]*", f"{title or ''} {text}".lower())
    filtered = [word for word in words if len(word) > 2 and word not in STOPWORDS and not word.isdigit()]
    if not filtered:
        return []

    scores = {}
    for size in (3, 2, 1):
        for index in range(len(filtered) - size + 1):
            phrase = " ".join(filtered[index:index + size])
            if any(word in STOPWORDS for word in phrase.split()):
                continue
            score = size
            if title and phrase in title.lower():
                score += 4
            score += text.lower().count(phrase)
            scores[phrase] = scores.get(phrase, 0) + score

    ranked = sorted(scores.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
    selected = []
    for phrase, _score in ranked:
        if any(phrase in existing or existing in phrase for existing in selected):
            continue
        selected.append(phrase)
        if len(selected) >= limit:
            break
    return selected


def build_result(url, provider, title, posted_datetime, location, compensation, workplace_type, employment_type, responsibilities, requirements_summary, concept_text):
    return {
        "url": url,
        "provider": provider,
        "title": title,
        "jd_concepts": extract_concepts(title, concept_text, "\n".join(responsibilities), "\n".join(requirements_summary)),
        "posted_datetime": posted_datetime,
        "location": location,
        "compensation": compensation,
        "workplace_type": workplace_type,
        "employment_type": employment_type,
        "responsibilities": responsibilities,
        "requirements_summary": requirements_summary,
    }


def parse_greenhouse(url):
    parsed = urlparse(url)
    match = re.search(r"/([^/]+)/jobs/(\d+)", parsed.path)
    if not match:
        raise ValueError(f"Unsupported Greenhouse URL: {url}")
    company, job_id = match.groups()
    payload = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}?content=true")
    content = html.unescape(html.unescape(payload.get("content", "")))
    sections = extract_sections_from_html(content)
    responsibilities = bulletize(select_section(sections, RESPONSIBILITY_KEYWORDS))
    requirements = bulletize(select_section(sections, REQUIREMENT_KEYWORDS))
    location = ((payload.get("location") or {}).get("name") if isinstance(payload.get("location"), dict) else None)

    return build_result(
        url=url,
        provider="greenhouse",
        title=payload.get("title"),
        posted_datetime=payload.get("first_published") or payload.get("updated_at"),
        location=location,
        compensation=infer_compensation(extract_greenhouse_compensation(payload.get("metadata")), content),
        workplace_type=infer_workplace_type(location, content),
        employment_type=infer_employment_type(content),
        responsibilities=responsibilities,
        requirements_summary=requirements,
        concept_text="\n".join(html_to_lines(content)),
    )


def extract_greenhouse_compensation(metadata):
    if not isinstance(metadata, list):
        return None
    values = []
    for item in metadata:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", ""))
        value = item.get("value")
        if any(keyword in name.lower() for keyword in ("salary", "compensation", "ote", "equity")) and value not in (None, ""):
            values.append(f"{name}: {value}")
    return "; ".join(values) if values else None


def parse_lever(url):
    parsed = urlparse(url)
    match = re.search(r"^/([^/]+)/([^/]+)$", parsed.path)
    if not match:
        raise ValueError(f"Unsupported Lever URL: {url}")
    company, job_id = match.groups()
    jobs = fetch_json(f"https://api.lever.co/v0/postings/{company}?mode=json")
    job = next((item for item in jobs if item.get("id") == job_id), None)
    if job is None:
        raise ValueError(f"Lever job not found for URL: {url}")

    responsibilities = []
    requirements = []
    for section in job.get("lists") or []:
        heading = normalize_heading(str(section.get("text", "")))
        content = str(section.get("content", ""))
        lines = html_to_lines(content)
        if heading in RESPONSIBILITY_KEYWORDS:
            responsibilities = bulletize(lines, limit=12)
        elif heading in REQUIREMENT_KEYWORDS:
            requirements = bulletize(lines, limit=12)

    description_text = "\n\n".join(
        part for part in (
            job.get("openingPlain"),
            job.get("descriptionPlain"),
            job.get("descriptionBodyPlain"),
            job.get("additionalPlain"),
        ) if part
    )
    categories = job.get("categories") or {}
    workplace_type = job.get("workplaceType")

    return build_result(
        url=url,
        provider="lever",
        title=job.get("text"),
        posted_datetime=to_iso_datetime(job.get("createdAt")),
        location=categories.get("location"),
        compensation=infer_compensation(None, description_text),
        workplace_type=infer_workplace_type(workplace_type, categories.get("location"), description_text),
        employment_type=infer_employment_type(categories.get("commitment"), description_text),
        responsibilities=responsibilities,
        requirements_summary=requirements,
        concept_text=description_text,
    )


def parse_bamboohr(url):
    parsed = urlparse(url)
    host_parts = parsed.netloc.split(".")
    if len(host_parts) < 3:
        raise ValueError(f"Unsupported BambooHR URL: {url}")
    company = host_parts[0]
    payload = fetch_json(url, headers={"Accept": "application/json"})
    job = (payload.get("result") or {}).get("jobOpening") or {}
    location_data = job.get("location") or {}
    location = ", ".join(part for part in (
        location_data.get("city"),
        location_data.get("state"),
        location_data.get("addressCountry"),
    ) if part) or None
    description = str(job.get("description", ""))
    sections = extract_sections_from_html(description)

    return build_result(
        url=url,
        provider="bamboohr",
        title=job.get("jobOpeningName"),
        posted_datetime=job.get("datePosted"),
        location=location,
        compensation=job.get("compensation"),
        workplace_type=infer_workplace_type(location, description),
        employment_type=infer_employment_type(job.get("employmentStatusLabel"), description),
        responsibilities=bulletize(select_section(sections, RESPONSIBILITY_KEYWORDS)),
        requirements_summary=bulletize(select_section(sections, REQUIREMENT_KEYWORDS)),
        concept_text="\n".join(html_to_lines(description)),
    )


def parse_generic_jobposting(url):
    raw = fetch_text(url)
    provider = detect_provider_from_page(raw) or detect_provider(url)
    jobposting = extract_jobposting_ld_json(raw)
    if jobposting is None:
        raise ValueError(f"Could not find JobPosting structured data for URL: {url}")

    description = str(jobposting.get("description", ""))
    sections = extract_sections_from_html(description)
    location = extract_ld_json_location(jobposting)
    workplace_type = infer_workplace_type(
        str(jobposting.get("jobLocationType", "")),
        location,
        description,
    )

    return build_result(
        url=url,
        provider=provider,
        title=jobposting.get("title"),
        posted_datetime=jobposting.get("datePosted"),
        location=location,
        compensation=extract_ld_json_compensation(jobposting) or infer_compensation(None, description),
        workplace_type=workplace_type,
        employment_type=infer_employment_type(jobposting.get("employmentType"), description),
        responsibilities=bulletize(select_section(sections, RESPONSIBILITY_KEYWORDS)),
        requirements_summary=bulletize(select_section(sections, REQUIREMENT_KEYWORDS)),
        concept_text="\n".join(html_to_lines(description)),
    )


def extract_jobposting_ld_json(raw_html):
    scripts = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw_html, flags=re.I | re.S)
    for script in scripts:
        payload = None
        for candidate in (script.strip(), html.unescape(script.strip())):
            try:
                payload = json.loads(candidate)
                break
            except json.JSONDecodeError:
                continue
        if payload is None:
            continue
        for item in flatten_ld_json(payload):
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if "JobPosting" in types:
                return item
    return None


def flatten_ld_json(payload):
    if isinstance(payload, list):
        for item in payload:
            yield from flatten_ld_json(item)
        return
    if not isinstance(payload, dict):
        return
    if "@graph" in payload and isinstance(payload["@graph"], list):
        for item in payload["@graph"]:
            yield from flatten_ld_json(item)
    yield payload


def extract_ld_json_location(jobposting):
    locations = jobposting.get("jobLocation")
    if not locations:
        return None
    if not isinstance(locations, list):
        locations = [locations]

    rendered = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        address = location.get("address", {})
        if isinstance(address, dict):
            parts = [
                address.get("addressLocality"),
                address.get("addressRegion"),
                address.get("addressCountry"),
            ]
            value = ", ".join(str(part) for part in parts if part)
            if value:
                rendered.append(value)
    return "; ".join(rendered) if rendered else None


def extract_ld_json_compensation(jobposting):
    salary = jobposting.get("baseSalary") or jobposting.get("estimatedSalary")
    if not isinstance(salary, dict):
        return None
    currency = salary.get("currency")
    value = salary.get("value")
    if isinstance(value, dict):
        min_value = value.get("minValue")
        max_value = value.get("maxValue")
        unit = value.get("unitText")
        if min_value or max_value:
            bounds = f"{min_value} - {max_value}" if min_value and max_value else str(min_value or max_value)
            return " ".join(part for part in (str(currency) if currency else None, bounds, str(unit) if unit else None) if part)
    return None


def parse_url(url):
    try:
        provider = detect_provider(url)
    except ValueError:
        provider = None
    if provider == "greenhouse":
        return parse_greenhouse(url)
    if provider == "lever":
        return parse_lever(url)
    if provider == "bamboohr":
        return parse_bamboohr(url)
    return parse_generic_jobposting(url)


def main():
    parser = argparse.ArgumentParser(description="Extract structured job-post data from a URL")
    parser.add_argument("--url", required=True, help="Job posting URL")
    parser.add_argument("-o", "--output", help="Optional JSON output path")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    try:
        result = parse_url(args.url)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    indent = 2 if args.pretty or args.output else None
    rendered = json.dumps(result, ensure_ascii=False, indent=indent)
    print(rendered)

    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
