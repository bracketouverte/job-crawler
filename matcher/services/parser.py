"""Job-post URL parser.

Ported from matcher/job_post_parser.py per the matcher rewrite plan's "Keep
all HTML-parsing, JSON-LD extraction, compensation inference, and
build_result logic verbatim" instruction — every pure-Python function below
is unchanged. Only the two network-calling functions (fetch_json, fetch_text)
and everything that awaits them are now async (httpx instead of requests).
"""

import html
import json
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx

from lib.matching_intelligence import extract_tools

DEFAULT_TIMEOUT = httpx.Timeout(60, connect=10)

_client: httpx.AsyncClient | None = None


def start_client() -> None:
    global _client
    _client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True)


async def stop_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("parser client not started — call start_client() in app lifespan")
    return _client


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

NICE_TO_HAVE_KEYWORDS_RAW = {
    "nice to haves",
    "nice to have",
    "nice-to-haves",
    "nice-to-have",
    "preferred qualifications",
    "preferred requirements",
    "preferred skills",
    "bonus points",
    "bonus",
    "extra credit",
    "would be a plus",
    "a plus",
}

STOPWORDS = {
    "a",
    "about",
    "across",
    "after",
    "all",
    "also",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "because",
    "been",
    "but",
    "by",
    "can",
    "company",
    "customers",
    "data",
    "do",
    "for",
    "from",
    "get",
    "have",
    "help",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "join",
    "key",
    "more",
    "most",
    "need",
    "of",
    "on",
    "or",
    "our",
    "role",
    "team",
    "that",
    "the",
    "their",
    "them",
    "this",
    "to",
    "us",
    "using",
    "we",
    "what",
    "who",
    "will",
    "with",
    "work",
    "working",
    "you",
    "your",
}


async def fetch_json(url, *, method="GET", headers=None, body=None):
    client = _get_client()
    response = await client.request(method, url, headers=headers, json=body)
    response.raise_for_status()
    return response.json()


async def fetch_text(url, *, headers=None):
    client = _get_client()
    response = await client.get(url, headers=headers)
    response.raise_for_status()
    return response.text


def slugify_token(value):
    lowered = str(value or "").strip().lower()
    lowered = lowered.replace("&", "and")
    lowered = re.sub(r"[^a-z0-9]+", "", lowered)
    return lowered


def detect_provider(url):
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path

    if "gh_jid=" in parsed.query.lower():
        return "greenhouse"
    if "grnhse" in host or "greenhouse" in host:
        return "greenhouse"
    if re.search(r"/jobs?/\d+/?$", path):
        return "greenhouse"

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
    if (
        "boards.greenhouse.io/embed/job_board/js?for=" in lowered
        or 'id="grnhse_app"' in lowered
        or "gh_jid=" in lowered
    ):
        return "greenhouse"
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
NICE_TO_HAVE_KEYWORDS = {normalize_heading(value) for value in NICE_TO_HAVE_KEYWORDS_RAW}


def is_heading(line):
    normalized = normalize_heading(line.rstrip(":"))
    if heading_matches(normalized, RESPONSIBILITY_KEYWORDS) or heading_matches(
        normalized, REQUIREMENT_KEYWORDS
    ):
        return True
    if line.endswith(":") and len(line.split()) <= 8:
        return True
    return False


def heading_matches(normalized_heading, keywords):
    if normalized_heading in keywords:
        return True
    return any(keyword in normalized_heading for keyword in keywords if len(keyword) >= 6)


def is_nice_to_have_heading(heading):
    return heading_matches(normalize_heading(heading), NICE_TO_HAVE_KEYWORDS)


def is_requirement_heading(heading):
    return heading_matches(normalize_heading(heading), REQUIREMENT_KEYWORDS) and not is_nice_to_have_heading(
        heading
    )


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
        cleaned = re.sub(r"^[\-\*•]+\s*", "", line).strip()
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


def select_sections(sections, predicate):
    selected = []
    for heading, lines in sections.items():
        if predicate(heading) and lines:
            selected.extend(lines)
    return selected


def split_requirement_sections(sections):
    must_have = bulletize(select_sections(sections, is_requirement_heading), limit=12)
    nice_to_have = bulletize(select_sections(sections, is_nice_to_have_heading), limit=10)
    return must_have, nice_to_have


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


_FX = {"EUR": 1.08, "GBP": 1.27, "CAD": 0.74, "AUD": 0.65, "USD": 1.0, "€": 1.08, "£": 1.27, "$": 1.0}


def _parse_amount(s: str) -> float | None:
    """Parse a numeric string with optional K/M suffix and EU-style thousands (130.000)."""
    s = s.strip().replace(",", "").replace(" ", "")
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([kKmM]?)$", s)
    if not m:
        return None
    val = float(m.group(1))
    suffix = m.group(2).upper()
    if "." in s and suffix == "" and re.search(r"\.\d{3}$", s):
        val = float(s.replace(".", ""))
    elif suffix == "K":
        val *= 1_000
    elif suffix == "M":
        val *= 1_000_000
    return val


def _detect_currency(text: str) -> str:
    for sym in ("GBP", "£", "EUR", "€", "CAD", "AUD", "USD", "$"):
        if sym in text:
            return sym
    return "$"


_NUM_PART = re.compile(r"(\d[\d,. ]*(?:\.\d+)?)\s*([kKmM]?)", re.IGNORECASE)


def infer_compensation(explicit, text):
    """Return {"min": int|null, "max": int|null} from an explicit value or JD text."""
    null_result = {"min": None, "max": None}

    candidate = explicit or ""
    if not candidate and text:
        for line in html_to_lines(text):
            if re.search(
                r"([$€£]|USD|EUR|GBP|CAD|AUD)\s?\d{2,3}|" r"\b\d{2,3}[kK]\b|\b\d{2,3}[,. ]\d{3}",
                line,
                re.IGNORECASE,
            ):
                candidate = line
                break

    if not candidate:
        return null_result

    currency = _detect_currency(candidate.upper())
    fx = _FX.get(currency, 1.0)

    multiplier = 1
    if re.search(r"/\s*h(r|our)?|per\s+hour", candidate, re.IGNORECASE):
        multiplier = 2080
    elif re.search(r"/\s*month|per\s+month", candidate, re.IGNORECASE):
        multiplier = 12

    clean = re.sub(r"(USD|EUR|GBP|CAD|AUD|[$€£])", "", candidate, flags=re.IGNORECASE)
    nums = _NUM_PART.findall(clean)
    values = []
    for num_str, suffix in nums:
        parsed = _parse_amount(num_str + suffix)
        if parsed is not None and parsed >= 10:
            values.append(int(round(parsed * fx * multiplier)))

    plausible = [v for v in values if v >= (10_000 if multiplier == 1 else 10)]
    if not plausible:
        return null_result

    plausible = sorted(set(plausible))
    return {"min": plausible[0], "max": plausible[1] if len(plausible) > 1 else None}


def to_iso_datetime(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value > 1_000_000_000_000:
            value /= 1000.0
        return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")
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
            phrase = " ".join(filtered[index : index + size])
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


def build_result(
    url,
    provider,
    title,
    posted_datetime,
    location,
    compensation,
    workplace_type,
    employment_type,
    responsibilities,
    requirements_summary,
    concept_text,
    nice_to_have_requirements=None,
):
    nice_to_have_requirements = nice_to_have_requirements or []
    return {
        "url": url,
        "provider": provider,
        "title": title,
        "jd_concepts": extract_concepts(
            title, concept_text, "\n".join(responsibilities), "\n".join(requirements_summary)
        ),
        "posted_datetime": posted_datetime,
        "location": location,
        "compensation": compensation,
        "workplace_type": workplace_type,
        "employment_type": employment_type,
        "responsibilities": responsibilities,
        "requirements_summary": requirements_summary,
        "must_have_requirements": requirements_summary,
        "nice_to_have_requirements": nice_to_have_requirements,
        "technical_tools_mentioned": extract_tools(
            "\n".join(
                [
                    str(title or ""),
                    str(location or ""),
                    str(concept_text or ""),
                    "\n".join(responsibilities),
                    "\n".join(requirements_summary),
                    "\n".join(nice_to_have_requirements),
                ]
            )
        ),
    }


def extract_greenhouse_identifiers(url, raw_html=None):
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    path_match = re.search(r"/([^/]+)/jobs/(\d+)", parsed.path)
    if path_match and "greenhouse.io" in host:
        return path_match.groups()

    query = parse_qs(parsed.query)
    job_id = None
    for key in ("gh_jid", "gh_src"):
        values = query.get(key) or []
        for value in values:
            value = str(value).strip()
            if value.isdigit():
                job_id = value
                break
        if job_id:
            break

    if job_id is None:
        tail_match = re.search(r"/jobs?/(\d+)/?$", parsed.path)
        if tail_match:
            job_id = tail_match.group(1)
        else:
            digit_runs = re.findall(r"\b(\d{7,})\b", parsed.path)
            if digit_runs:
                job_id = digit_runs[-1]

    company = None
    if raw_html:
        embed_match = re.search(
            r"boards\.greenhouse\.io/embed/job_board/js\?for=([A-Za-z0-9_-]+)", raw_html, flags=re.I
        )
        if embed_match:
            company = embed_match.group(1)
        else:
            board_match = re.search(
                r'["\']board(?:Token|Name)?["\']\s*[:=]\s*["\']([A-Za-z0-9_-]+)["\']', raw_html, flags=re.I
            )
            if board_match:
                company = board_match.group(1)

    if company and job_id:
        return company, job_id
    raise ValueError(f"Unsupported Greenhouse URL: {url}")


def greenhouse_page_data_url(url):
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path:
        path = "/"
    return f"{parsed.scheme}://{parsed.netloc}/page-data{path}/page-data.json"


async def extract_greenhouse_identifiers_from_page_data(url):
    payload = await fetch_json(greenhouse_page_data_url(url))
    page_context = (payload.get("result") or {}).get("pageContext") or {}
    job = page_context.get("job") or {}

    job_id = job.get("id")
    company_name = job.get("company_name")
    company = slugify_token(company_name)

    if isinstance(job_id, int):
        job_id = str(job_id)
    elif isinstance(job_id, str):
        job_id = job_id.strip()
    else:
        job_id = None

    if company and job_id and job_id.isdigit():
        return company, job_id
    raise ValueError(f"Could not extract Greenhouse identifiers from page-data for URL: {url}")


async def parse_greenhouse(url):
    raw_html = None
    parsed = urlparse(url)
    is_canonical_greenhouse = "greenhouse.io" in parsed.netloc.lower()
    if not is_canonical_greenhouse:
        raw_html = await fetch_text(url)
    try:
        company, job_id = extract_greenhouse_identifiers(url, raw_html=raw_html)
    except Exception:
        if not raw_html:
            raise
        company, job_id = await extract_greenhouse_identifiers_from_page_data(url)

    payload = await fetch_json(
        f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}?content=true"
    )
    content = html.unescape(html.unescape(payload.get("content", "")))
    sections = extract_sections_from_html(content)
    responsibilities = bulletize(select_section(sections, RESPONSIBILITY_KEYWORDS))
    requirements, nice_to_have = split_requirement_sections(sections)
    location = (
        (payload.get("location") or {}).get("name") if isinstance(payload.get("location"), dict) else None
    )

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
        nice_to_have_requirements=nice_to_have,
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
        if any(
            keyword in name.lower() for keyword in ("salary", "compensation", "ote", "equity")
        ) and value not in (None, ""):
            values.append(f"{name}: {value}")
    return "; ".join(values) if values else None


async def parse_lever(url):
    parsed = urlparse(url)
    match = re.search(r"^/([^/]+)/([^/]+)$", parsed.path)
    if not match:
        raise ValueError(f"Unsupported Lever URL: {url}")
    company, job_id = match.groups()
    jobs = await fetch_json(f"https://api.lever.co/v0/postings/{company}?mode=json")
    job = next((item for item in jobs if item.get("id") == job_id), None)
    if job is None:
        raise ValueError(f"Lever job not found for URL: {url}")

    responsibilities = []
    requirements = []
    nice_to_have = []
    for section in job.get("lists") or []:
        heading = normalize_heading(str(section.get("text", "")))
        content = str(section.get("content", ""))
        lines = html_to_lines(content)
        if heading in RESPONSIBILITY_KEYWORDS:
            responsibilities = bulletize(lines, limit=12)
        elif heading in NICE_TO_HAVE_KEYWORDS:
            nice_to_have = bulletize(lines, limit=10)
        elif heading in REQUIREMENT_KEYWORDS:
            requirements = bulletize(lines, limit=12)

    description_text = "\n\n".join(
        part
        for part in (
            job.get("openingPlain"),
            job.get("descriptionPlain"),
            job.get("descriptionBodyPlain"),
            job.get("additionalPlain"),
        )
        if part
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
        nice_to_have_requirements=nice_to_have,
        concept_text=description_text,
    )


async def parse_bamboohr(url):
    parsed = urlparse(url)
    host_parts = parsed.netloc.split(".")
    if len(host_parts) < 3:
        raise ValueError(f"Unsupported BambooHR URL: {url}")
    payload = await fetch_json(url, headers={"Accept": "application/json"})
    job = (payload.get("result") or {}).get("jobOpening") or {}
    location_data = job.get("location") or {}
    location = (
        ", ".join(
            part
            for part in (
                location_data.get("city"),
                location_data.get("state"),
                location_data.get("addressCountry"),
            )
            if part
        )
        or None
    )
    description = str(job.get("description", ""))
    sections = extract_sections_from_html(description)
    requirements, nice_to_have = split_requirement_sections(sections)

    return build_result(
        url=url,
        provider="bamboohr",
        title=job.get("jobOpeningName"),
        posted_datetime=job.get("datePosted"),
        location=location,
        compensation=infer_compensation(job.get("compensation"), description),
        workplace_type=infer_workplace_type(location, description),
        employment_type=infer_employment_type(job.get("employmentStatusLabel"), description),
        responsibilities=bulletize(select_section(sections, RESPONSIBILITY_KEYWORDS)),
        requirements_summary=requirements,
        nice_to_have_requirements=nice_to_have,
        concept_text="\n".join(html_to_lines(description)),
    )


async def parse_generic_jobposting(url):
    raw = await fetch_text(url)
    provider = detect_provider_from_page(raw) or detect_provider(url)
    jobposting = extract_jobposting_ld_json(raw)
    if jobposting is None:
        raise ValueError(f"Could not find JobPosting structured data for URL: {url}")

    description = str(jobposting.get("description", ""))
    sections = extract_sections_from_html(description)
    requirements, nice_to_have = split_requirement_sections(sections)
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
        requirements_summary=requirements,
        nice_to_have_requirements=nice_to_have,
        concept_text="\n".join(html_to_lines(description)),
    )


def extract_jobposting_ld_json(raw_html):
    scripts = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw_html, flags=re.I | re.S
    )
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
    """Extract baseSalary from JSON-LD and return {"min": int|null, "max": int|null} or None."""
    salary = jobposting.get("baseSalary") or jobposting.get("estimatedSalary")
    if not isinstance(salary, dict):
        return None
    currency = (salary.get("currency") or "USD").upper()
    fx = _FX.get(currency, 1.0)
    value = salary.get("value")
    unit = ""
    if isinstance(value, dict):
        unit = str(value.get("unitText") or "")
        min_val = value.get("minValue")
        max_val = value.get("maxValue")
    elif isinstance(value, (int, float)):
        min_val, max_val = value, None
    else:
        return None
    if not min_val and not max_val:
        return None
    multiplier = 2080 if "HOUR" in unit.upper() else 12 if "MONTH" in unit.upper() else 1

    def to_int(v):
        return int(round(float(v) * fx * multiplier)) if v is not None else None

    return {"min": to_int(min_val), "max": to_int(max_val)}


def to_jsonld(record: dict, target_role: str = "") -> str:
    """Serialize a parsed job record to a compact schema.org/JobPosting JSON-LD string."""
    requirements = record.get("must_have_requirements") or record.get("requirements_summary") or []
    nice_to_have = record.get("nice_to_have_requirements") or []
    skills = requirements + nice_to_have
    tools = record.get("technical_tools_mentioned") or []

    description = record.get("jd_text") or ""
    if not description:
        parts = []
        if record.get("responsibilities"):
            parts.append("Responsibilities: " + "; ".join(record["responsibilities"]))
        if requirements:
            parts.append("Requirements: " + "; ".join(requirements))
        description = " | ".join(parts)
    description = description[:1000]

    obj = {"@context": "https://schema.org", "@type": "JobPosting"}
    if record.get("title"):
        obj["title"] = record["title"]
    if record.get("company"):
        obj["hiringOrganization"] = {"@type": "Organization", "name": record["company"]}
    if record.get("location"):
        obj["jobLocation"] = {"@type": "Place", "address": record["location"]}
    if target_role:
        obj["occupationalCategory"] = target_role
    if record.get("employment_type"):
        obj["employmentType"] = record["employment_type"]
    comp = record.get("compensation")
    if isinstance(comp, dict) and (comp.get("min") or comp.get("max")):
        parts = [f"${v // 1000}k" for v in (comp.get("min"), comp.get("max")) if v]
        obj["baseSalary"] = "–".join(parts)
    elif isinstance(comp, str) and comp:
        obj["baseSalary"] = comp
    if description:
        obj["description"] = description
    combined_skills = list(dict.fromkeys(skills + tools))
    if combined_skills:
        obj["skills"] = combined_skills[:30]
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


async def parse_url(url):
    try:
        provider = detect_provider(url)
    except ValueError:
        provider = None
    if provider == "greenhouse":
        return await parse_greenhouse(url)
    if provider == "lever":
        return await parse_lever(url)
    if provider == "bamboohr":
        return await parse_bamboohr(url)
    return await parse_generic_jobposting(url)
