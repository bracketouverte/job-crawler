"""
Generic candidate/JD extraction and deterministic guardrails.

This module intentionally avoids applicant-specific rules. It extracts a small
set of facts from the active profile files and from the JD text, then compares
those facts conservatively before the LLM scorer reasons about fit.
"""

import json
import re


US_STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
US_STATE_CODES = set(US_STATE_NAMES.values())
AMBIGUOUS_STATE_CODES = {"ID", "IN", "ME", "OR"}

COUNTRY_ALIASES = {
    "US": ["united states of america", "united states", "u.s.a.", "u.s.", "usa", "us"],
    "UK": ["united kingdom", "u.k.", "uk", "great britain", "britain"],
    "DE": ["germany", "deutschland"],
    "AT": ["austria"],
    "NL": ["netherlands", "holland"],
    "PT": ["portugal"],
    "ES": ["spain"],
    "CA": ["canada"],
    "FR": ["france"],
    "IE": ["ireland"],
    "PL": ["poland"],
    "RO": ["romania"],
    "IN": ["india"],
    "AU": ["australia"],
}
EU_COUNTRY_CODES = {"DE", "AT", "NL", "PT", "ES", "FR", "IE", "PL", "RO"}

TECH_TOOL_PATTERNS = [
    r"\b(?:SQL|Python|JavaScript|TypeScript|Java|C#|C\+\+|Go|Golang|Ruby|PHP|Scala|Kotlin|Swift|R)\b",
    r"\b(?:React|Vue|Angular|Node\.?js|Next\.?js|Django|Flask|FastAPI|Rails|Spring|GraphQL|REST|gRPC)\b",
    r"\b(?:AWS|Azure|GCP|Kubernetes|Docker|Terraform|Datadog|New Relic|Prometheus|Grafana|ELK|ElasticSearch|OpenSearch)\b",
    r"\b(?:PostgreSQL|Postgres|MySQL|MongoDB|Redis|Snowflake|BigQuery|Redshift|Kafka|Spark|dbt|Looker|Tableau|Power BI)\b",
    r"\b(?:Salesforce|HubSpot|Zendesk|Jira|Confluence|Figma|Amplitude|Mixpanel|Segment|GA4|Google Analytics)\b",
    r"\b(?:OpenAI|Anthropic|Claude|GPT-?\d*|LLM|LLMOps|LangChain|LlamaIndex|RAG|vector database|Pinecone|Weaviate)\b",
    r"\b(?:SAP|Workday|NetSuite|Oracle|Stripe|Twilio|SendGrid|Snowplow|ATS|CRM|CMS)\b",
]

NICE_HEADING_RE = re.compile(
    r"^(?:nice[- ]to[- ]have|preferred|bonus|plus|extra credit|would be great)s?(?: qualifications| requirements| skills)?$",
    re.I,
)
MUST_HEADING_RE = re.compile(
    r"^(?:requirements?|qualifications?|minimum qualifications|what you(?:'|’)ll need|what you need|what you bring|you have|about you|skills)$",
    re.I,
)
SECTION_STOP_RE = re.compile(
    r"^(?:title|company|provider|location|employment type|workplace type|compensation|posted datetime|jd concepts|responsibilities|job description)$",
    re.I,
)


def normalize_key(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def unique(items):
    seen = set()
    result = []
    for item in items:
        text = str(item or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def country_codes_in_text(text):
    lowered = str(text or "").lower()
    codes = []
    for code, aliases in COUNTRY_ALIASES.items():
        if any(re.search(rf"\b{re.escape(alias)}\b", lowered) for alias in aliases):
            codes.append(code)
    if re.search(r"\b(?:europe|european union|eu)\b", lowered):
        codes.extend(sorted(EU_COUNTRY_CODES))
    return sorted(set(codes))


def us_regions_in_text(text, include_ambiguous_codes=True):
    source = str(text or "")
    lowered = source.lower()
    regions = set()
    for name, code in US_STATE_NAMES.items():
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            regions.add(code)
    for code in US_STATE_CODES:
        if not include_ambiguous_codes and code in AMBIGUOUS_STATE_CODES:
            continue
        if re.search(rf"\b{code}\b", source):
            regions.add(code)
    return sorted(regions)


def profile_sections(profile_text):
    sections = {}
    current = "general"
    sections[current] = []
    for line in str(profile_text or "").splitlines():
        match = re.match(r"^===\s*(.+?)\s*===$", line.strip())
        if match:
            current = match.group(1).strip().lower()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {key: "\n".join(value) for key, value in sections.items()}


def build_profile_text(profile_data):
    return (
        f"=== IDENTITY (profile.yml) ===\n{profile_data.get('profile.yml', '')}\n\n"
        f"=== TARGET KEYWORDS (portals.yml) ===\n{profile_data.get('portals.yml', '')}\n\n"
        f"=== EXPERIENCE (cv.md) ===\n{profile_data.get('cv.md', '')}\n\n"
        f"=== APPLICATION STRATEGY (_profile.md) ===\n{profile_data.get('_profile.md', '')}"
    )


def extract_tools(text, limit=40):
    found = []
    seen = set()
    for pattern in TECH_TOOL_PATTERNS:
        for match in re.finditer(pattern, str(text or ""), flags=re.I):
            tool = " ".join(match.group(0).split()).strip(" .,;:()[]")
            key = normalize_key(tool)
            if key and key not in seen:
                seen.add(key)
                found.append(tool)
                if len(found) >= limit:
                    return found
    return found


def extract_candidate_facts(profile_text):
    text = str(profile_text or "")
    sections = profile_sections(text)
    location_source = "\n".join(
        body for name, body in sections.items()
        if ("identity" in name or "strategy" in name or "general" in name)
        and "experience" not in name
        and "cv" not in name
        and "portal" not in name
        and "target" not in name
    ).strip() or text[:2500]

    countries = country_codes_in_text(location_source)
    regions = us_regions_in_text(location_source, include_ambiguous_codes=False)
    if regions and "US" not in countries:
        countries.append("US")

    return {
        "countries": sorted(set(countries)),
        "regions": regions,
        "remote_preference": "remote" if "remote" in location_source.lower() else None,
        "tools": extract_tools(text),
    }


def location_lines(text):
    lines = []
    for raw in str(text or "").splitlines():
        line = " ".join(raw.split()).strip()
        lowered = line.lower()
        if line and any(term in lowered for term in ("location", "remote", "hybrid", "on-site", "onsite", "eligible", "not available", "not eligible")):
            lines.append(line)
    return lines[:20]


def excluded_regions(text):
    regions = set()
    for window in re.findall(r"(?:not eligible|not available|cannot be hired|excluded?|except)\b[^.\n;]*", str(text or ""), re.I):
        regions.update(us_regions_in_text(window))
    return sorted(regions)


def extract_location_policy(jd_text):
    lines = location_lines(jd_text)
    source = "\n".join(lines) or str(jd_text or "")[:1500]
    lowered = source.lower()
    workplace_type = None
    if "hybrid" in lowered:
        workplace_type = "hybrid"
    elif "remote" in lowered or "telecommute" in lowered:
        workplace_type = "remote"
    elif any(term in lowered for term in ("on-site", "onsite", "in office")):
        workplace_type = "on-site"
    return {
        "workplace_type": workplace_type,
        "eligible_countries": country_codes_in_text(source),
        "eligible_regions": us_regions_in_text(source),
        "excluded_regions": excluded_regions(jd_text),
        "raw_signals": lines,
    }


def classify_requirement(line, current):
    if current in {"must_have", "nice_to_have"}:
        return current
    lowered = str(line or "").lower()
    if any(term in lowered for term in ("nice to have", "preferred", "bonus", "plus", "extra credit")):
        return "nice_to_have"
    if any(term in lowered for term in ("must have", "required", "minimum", "need to have")):
        return "must_have"
    if re.search(r"\b\d+\+?\s+years?\b", lowered):
        return "must_have"
    return "important"


def extract_requirement_groups(jd_text):
    groups = {"must_have": [], "important": [], "nice_to_have": []}
    current = None
    for raw in str(jd_text or "").splitlines():
        stripped = raw.strip()
        line = stripped.strip(" -\t")
        if not line:
            continue
        heading = line.rstrip(":").strip()
        if NICE_HEADING_RE.match(heading):
            current = "nice_to_have"
            continue
        if MUST_HEADING_RE.match(heading):
            current = "must_have"
            continue
        if SECTION_STOP_RE.match(heading):
            current = None
            continue
        if stripped.startswith(("-", "*", "•")) or current:
            kind = classify_requirement(line, current)
            if len(line) >= 3 and len(groups[kind]) < 16:
                groups[kind].append(line)
    return {key: unique(value) for key, value in groups.items()}


def match_tools(jd_tools, candidate_tools):
    candidate = {normalize_key(tool): tool for tool in candidate_tools}
    return [
        {
            "tool": tool,
            "status": "direct" if normalize_key(tool) in candidate else "missing",
            "profile_evidence": candidate.get(normalize_key(tool), ""),
        }
        for tool in jd_tools
    ]


def evaluate_location(candidate_facts, job_policy):
    candidate_countries = set(candidate_facts.get("countries") or [])
    candidate_regions = set(candidate_facts.get("regions") or [])
    eligible_countries = set(job_policy.get("eligible_countries") or [])
    eligible_regions = set(job_policy.get("eligible_regions") or [])
    blocked_regions = set(job_policy.get("excluded_regions") or [])

    blocked = sorted(candidate_regions.intersection(blocked_regions))
    if blocked:
        return {"status": "incompatible", "reason": f"Candidate region is explicitly excluded: {', '.join(blocked)}."}

    if eligible_countries and candidate_countries:
        overlap = sorted(candidate_countries.intersection(eligible_countries))
        if overlap:
            return {"status": "compatible", "reason": f"Candidate country matches eligible job country scope: {', '.join(overlap)}."}
        return {
            "status": "incompatible",
            "reason": f"Candidate country does not match eligible job country scope ({', '.join(sorted(eligible_countries))}).",
        }

    if eligible_regions and candidate_regions:
        overlap = sorted(candidate_regions.intersection(eligible_regions))
        if overlap:
            return {"status": "compatible", "reason": f"Candidate region matches eligible job region scope: {', '.join(overlap)}."}
        if job_policy.get("workplace_type") != "remote":
            return {
                "status": "incompatible",
                "reason": f"Candidate region does not match listed on-site/hybrid region scope ({', '.join(sorted(eligible_regions))}).",
            }

    if job_policy.get("workplace_type") == "remote":
        return {"status": "unknown", "reason": "Remote role, but eligible geography is not explicit."}
    return {"status": "unknown", "reason": "No deterministic location compatibility signal."}


def build_match_context(jd_text, profile_text):
    candidate = extract_candidate_facts(profile_text)
    location_policy = extract_location_policy(jd_text)
    tools = extract_tools(jd_text)
    return {
        "candidate_facts": candidate,
        "job_facts": {
            "location_policy": location_policy,
            "requirement_groups": extract_requirement_groups(jd_text),
            "technical_tools": tools,
        },
        "matches": {
            "location": evaluate_location(candidate, location_policy),
            "technical_tools": match_tools(tools, candidate.get("tools") or []),
        },
    }


def format_match_context(match_context):
    return json.dumps(match_context, ensure_ascii=False, indent=2)
