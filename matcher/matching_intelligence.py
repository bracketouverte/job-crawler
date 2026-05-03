"""
Generic candidate/JD extraction and guardrails for fit scoring.

Architecture:
  1. CandidateModel — deterministic parse from profile files (no LLM, works for any profile)
  2. JobModel       — structured pre-extraction from JD text (regex + heuristics)
  3. Guardrails     — operate on those two models; produce deterministic verdicts before scoring
  4. build_match_context() — entry point for all callers

Design principle: extract facts first, then match facts, then score.
The LLM explains and arbitrates — it does not invent geographic or requirement facts.
"""

import json
import re
from pathlib import Path

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


# ---------------------------------------------------------------------------
# Geographic reference data
# ---------------------------------------------------------------------------

US_STATE_NAMES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
US_STATE_CODES: set[str] = set(US_STATE_NAMES.values())

COUNTRY_ALIASES: dict[str, list[str]] = {
    "US": ["united states of america", "united states", "u.s.a.", "u.s.", "usa", "us"],
    "UK": ["united kingdom", "u.k.", "uk", "great britain", "britain", "england"],
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
    "BR": ["brazil"],
    "MX": ["mexico"],
    "SG": ["singapore"],
    "JP": ["japan"],
    "IL": ["israel"],
}
COUNTRY_NAMES: dict[str, str] = {code: aliases[0].title() for code, aliases in COUNTRY_ALIASES.items()}
EU_COUNTRY_CODES: set[str] = {"DE", "AT", "NL", "PT", "ES", "FR", "IE", "PL", "RO"}

# Ambiguous two-letter codes that appear in non-geographic contexts
_AMBIGUOUS_STATE_CODES: set[str] = {"ID", "IN", "ME", "OR", "OK", "IL", "AL", "DE", "HI", "MS", "MT", "NE", "NH", "NM", "ND", "RI", "SD", "VT", "WV", "WY"}


# ---------------------------------------------------------------------------
# Technical tools registry
# ---------------------------------------------------------------------------

_TECH_TOOL_TERMS: list[str] = [
    # Languages
    "SQL", "Python", "JavaScript", "TypeScript", "Java", "C#", r"C\+\+", "Go", "Golang",
    "Ruby", "PHP", "Scala", "Kotlin", "Swift", "R",
    # Frameworks / APIs
    r"React", r"Vue", r"Angular", r"Node\.?js", r"Next\.?js", "Nuxt", "Django", "Flask",
    "FastAPI", "Rails", "Spring", "GraphQL", "REST", "gRPC", "tRPC",
    # Cloud / infra
    "AWS", "Azure", "GCP", "Google Cloud", "Kubernetes", "Docker", "Terraform",
    "Datadog", "New Relic", "Prometheus", "Grafana", "ELK", "ElasticSearch", "OpenSearch",
    # Data
    "PostgreSQL", "Postgres", "MySQL", "MongoDB", "Redis", "Snowflake", "BigQuery",
    "Redshift", "Kafka", "Spark", "dbt", "Looker", "Tableau", "Power BI", "Databricks",
    # Business tools
    "Salesforce", "HubSpot", "Zendesk", "Jira", "Confluence", "Figma", "Amplitude",
    "Mixpanel", "Segment", "GA4", "Google Analytics", "Intercom", "Pendo",
    # AI / ML
    r"OpenAI", "Anthropic", "Claude", r"GPT-?\d*", "LLM", "LLMOps", "LangChain",
    "LlamaIndex", "RAG", "vector database", "Pinecone", "Weaviate", "Chroma", "Qdrant",
    # Enterprise
    "SAP", "Workday", "NetSuite", "Oracle", "Stripe", "Twilio", "SendGrid", "Snowplow",
    "ATS", "CRM", "CMS", "ERP",
    # DevOps / VCS
    "GitHub Actions", "GitHub", "GitLab", "Bitbucket", "Jenkins", "CircleCI",
    "ArgoCD", "Helm", "Ansible",
    # Productivity
    r"Monday\.com", "Notion", "Slack", "Linear", "Asana", "ClickUp", "Miro",
    "Productboard", r"Aha!",
]

# Longer alternatives must come before shorter prefixes (e.g. "GitHub Actions" before "GitHub")
# so the first match wins and we don't split a two-word term. The list above is already ordered
# that way; we compile once at import time.
_TECH_TOOLS_RE = re.compile(
    r"\b(?:" + "|".join(_TECH_TOOL_TERMS) + r")\b",
    flags=re.I,
)

# Heading patterns for requirement classification
_NICE_TO_HAVE_HEADING_RE = re.compile(
    r"^(?:nice[- ]to[- ]have|preferred|bonus|plus|extra credit|would be great|advantage)s?"
    r"(?: qualifications?| requirements?| skills?)?$",
    flags=re.I,
)
_MUST_HAVE_HEADING_RE = re.compile(
    r"^(?:requirements?|qualifications?|minimum qualifications?|what you(?:'|')ll need"
    r"|what you need|what you bring|you(?:'re| are) |about you|skills required|must.have)$",
    flags=re.I,
)
_SECTION_STOP_RE = re.compile(
    r"^(?:title|company|provider|location|employment type|workplace type"
    r"|compensation|posted datetime|jd concepts|responsibilities|job description|benefits?|perks?)$",
    flags=re.I,
)

# Patterns that indicate a hard requirement in the line itself
_HARD_REQ_RE = re.compile(
    r"\b(\d+\+?\s+years?|must\s+have|required|mandatory|minimum of \d+|you must)\b",
    flags=re.I,
)

# State exclusion / ineligibility phrases
_EXCLUSION_PHRASE_RE = re.compile(
    r"(?:not eligible|not available|cannot be hired|excluded?|except|not open to|"
    r"excluding|does not include|not applicable)\b[^.\n;]{0,200}",
    flags=re.I,
)

# Compensation context clues — lines that talk about pay, NOT location
_COMP_CONTEXT_RE = re.compile(
    r"\b(?:salary|compensation|pay|ote|equity|bonus|wage|annual|hourly|per hour|"
    r"usd|eur|gbp|\$\d|\d{2,3}[,\s]?\d{3}|\d{2,3}k\b)",
    flags=re.I,
)


# ---------------------------------------------------------------------------
# Low-level text helpers
# ---------------------------------------------------------------------------

def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _unique_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _country_codes_in_text(text: str) -> list[str]:
    lowered = str(text or "").lower()
    codes: list[str] = []
    for code, aliases in COUNTRY_ALIASES.items():
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", lowered):
                codes.append(code)
                break
    if re.search(r"\b(?:europe|european union|eu)\b", lowered):
        codes.extend(sorted(EU_COUNTRY_CODES))
    return sorted(set(codes))


def _us_regions_in_text(text: str, include_ambiguous: bool = True) -> list[str]:
    regions: set[str] = set()
    lowered = str(text or "").lower()
    for name, code in US_STATE_NAMES.items():
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            regions.add(code)
    for code in US_STATE_CODES:
        if not include_ambiguous and code in _AMBIGUOUS_STATE_CODES:
            continue
        if re.search(rf"\b{re.escape(code)}\b", str(text or "")):
            regions.add(code)
    return sorted(regions)


def extract_tools(text: str, limit: int = 40) -> list[str]:
    """Extract technical tool names from arbitrary text using regex patterns."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _TECH_TOOLS_RE.finditer(str(text or "")):
        tool = " ".join(match.group(0).split()).strip(" .,;:()[]")
        key = _normalize_key(tool)
        if not key or key in seen:
            continue
        seen.add(key)
        found.append(tool)
        if len(found) >= limit:
            break
    return found


# ---------------------------------------------------------------------------
# CandidateModel — deterministic parse, no LLM
# ---------------------------------------------------------------------------

def _yaml_safe_load(text: str) -> dict:
    """Parse YAML with graceful fallback to empty dict."""
    if not _YAML_AVAILABLE:
        return {}
    try:
        result = yaml.safe_load(text)
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def _extract_location_from_yaml(data: dict) -> tuple[str | None, str | None]:
    """Return (city_region, country_code) from a parsed profile.yml dict."""
    candidate = data.get("candidate") or {}
    raw_location = str(candidate.get("location") or "").strip()
    if not raw_location:
        return None, None

    countries = _country_codes_in_text(raw_location)
    country = countries[0] if countries else None

    # US state detection
    regions = _us_regions_in_text(raw_location, include_ambiguous=False)
    if regions and not country:
        country = "US"

    city_region = regions[0] if regions else None

    # If no state found but we have free-form city, keep raw for display
    city_display = raw_location if not city_region else None

    return city_region or city_display, country


def _extract_work_authorization(data: dict, raw_text: str) -> dict:
    """Extract work authorization facts."""
    candidate = data.get("candidate") or {}
    compensation = data.get("compensation") or {}

    # Explicit sponsorship field
    raw_visa = str(candidate.get("visa_status") or candidate.get("work_authorization") or "").lower()
    if not raw_visa:
        # Try compensation section
        raw_visa = str(compensation.get("visa_status") or "").lower()
    if not raw_visa:
        # Fallback: scan raw text
        raw_visa = raw_text.lower()

    needs_sponsorship = None
    if any(phrase in raw_visa for phrase in ("no sponsorship", "does not require", "not require", "citizen", "green card", "permanent resident", "ead")):
        needs_sponsorship = False
    elif any(phrase in raw_visa for phrase in ("requires sponsorship", "need sponsorship", "h1b", "h-1b", "visa required")):
        needs_sponsorship = True

    return {"needs_sponsorship": needs_sponsorship, "raw": raw_visa[:120] if raw_visa != raw_text.lower() else ""}


def _extract_target_roles(data: dict) -> dict:
    """Extract target roles, archetypes, non-targets."""
    target = data.get("target_roles") or {}
    archetypes_raw = target.get("archetypes") or []
    primary_roles = target.get("primary") or []
    if isinstance(primary_roles, str):
        primary_roles = [primary_roles]

    archetypes: list[dict] = []
    for a in archetypes_raw:
        if not isinstance(a, dict):
            continue
        archetypes.append({
            "name": str(a.get("name") or ""),
            "level": str(a.get("level") or ""),
            "fit": str(a.get("fit") or "primary"),
        })

    # Non-target indicators
    filters = data.get("job_filters") or {}
    exclude_keywords = filters.get("exclude_title_keywords") or []

    return {
        "primary_titles": [str(r) for r in primary_roles],
        "archetypes": archetypes,
        "exclude_keywords": [str(k) for k in exclude_keywords],
    }


def _extract_compensation_preferences(data: dict) -> dict:
    comp = data.get("compensation") or {}
    return {
        "currency": str(comp.get("currency") or "USD"),
        "minimum": comp.get("minimum"),
        "target_min": comp.get("target_min"),
        "target_max": comp.get("target_max"),
    }


def _extract_workplace_preferences(data: dict, raw_text: str) -> dict:
    candidate = data.get("candidate") or {}
    raw_pref = str(candidate.get("location_flexibility") or candidate.get("workplace_preference") or "").lower()
    if not raw_pref:
        raw_pref = raw_text.lower()

    preferred: list[str] = []
    if "remote" in raw_pref:
        preferred.append("remote")
    if "hybrid" in raw_pref:
        preferred.append("hybrid")
    if "on-site" in raw_pref or "onsite" in raw_pref or "office" in raw_pref:
        preferred.append("on-site")
    if not preferred:
        preferred = ["remote", "hybrid"]  # safe default

    return {"preferred_types": preferred}


def _profile_sections(profile_text: str) -> dict[str, str]:
    """Split profile text on === SECTION === markers."""
    sections: dict[str, list[str]] = {}
    current = "general"
    sections[current] = []
    for line in str(profile_text or "").splitlines():
        m = re.match(r"^===\s*(.+?)\s*===$", line.strip())
        if m:
            current = m.group(1).strip().lower()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


def build_candidate_model(profile_data: dict[str, str]) -> dict:
    """
    Build a structured CandidateModel from raw profile file contents.

    profile_data keys: "profile.yml", "portals.yml", "cv.md", "_profile.md"

    This function is deterministic and uses no LLM. It reads YAML when available
    and falls back to regex scanning on raw text — making it work for any user's
    profile format without hardcoding applicant-specific assumptions.
    """
    profile_yml_text = str(profile_data.get("profile.yml") or "")
    cv_text = str(profile_data.get("cv.md") or "")
    portals_text = str(profile_data.get("portals.yml") or "")
    strategy_text = str(profile_data.get("_profile.md") or "")

    all_text = "\n\n".join([profile_yml_text, cv_text, portals_text, strategy_text])

    # Parse YAML if available; fall back gracefully
    yaml_data = _yaml_safe_load(profile_yml_text)
    if not yaml_data:
        # Try portals.yml as secondary YAML source
        yaml_data = _yaml_safe_load(portals_text) or {}

    # --- Location ---
    city_region, country_code = _extract_location_from_yaml(yaml_data)
    if not country_code:
        # Fallback: scan identity section of profile text
        identity_text = profile_yml_text[:3000]
        countries = _country_codes_in_text(identity_text)
        country_code = countries[0] if countries else None
        regions = _us_regions_in_text(identity_text, include_ambiguous=False)
        city_region = regions[0] if regions else city_region
        if regions and not country_code:
            country_code = "US"

    candidate_countries = [country_code] if country_code else []
    candidate_regions = [city_region] if city_region and len(city_region) == 2 and city_region in US_STATE_CODES else []

    # --- Work authorization ---
    work_auth = _extract_work_authorization(yaml_data, profile_yml_text)

    # --- Target roles ---
    target_roles = _extract_target_roles(yaml_data)

    # --- Seniority ---
    seniority_keywords = ["senior", "staff", "principal", "lead", "director", "vp", "head of"]
    all_lower = all_text.lower()
    detected_seniority: list[str] = [kw for kw in seniority_keywords if kw in all_lower]

    # --- Domains ---
    domain_patterns = [
        (r"\b(?:b2b|saas|software as a service)\b", "B2B SaaS"),
        (r"\b(?:fintech|financial technology|payments|banking)\b", "FinTech"),
        (r"\b(?:healthtech|health tech|healthcare|medical)\b", "HealthTech"),
        (r"\b(?:edtech|education technology|e-learning|elearning)\b", "EdTech"),
        (r"\b(?:ecommerce|e-commerce|retail|marketplace)\b", "eCommerce"),
        (r"\b(?:hrtech|hr tech|human resources|hr platform)\b", "HRTech"),
        (r"\b(?:legaltech|legal tech|legal)\b", "LegalTech"),
        (r"\b(?:logistics|supply chain|fleet)\b", "Logistics"),
        (r"\b(?:proptech|real estate|property)\b", "PropTech"),
        (r"\b(?:ai|artificial intelligence|machine learning|llm|nlp)\b", "AI/ML"),
        (r"\b(?:cybersecurity|security|infosec)\b", "Security"),
        (r"\b(?:devtools|developer tools|developer experience|dx)\b", "DevTools"),
        (r"\b(?:platform|infrastructure|api|data platform)\b", "Platform/Infra"),
    ]
    candidate_domains: list[str] = []
    for pattern, label in domain_patterns:
        if re.search(pattern, all_lower):
            candidate_domains.append(label)

    # --- Technical tools (from CV + strategy) ---
    tools = extract_tools(cv_text + "\n" + strategy_text)

    # --- Workplace preference ---
    workplace_prefs = _extract_workplace_preferences(yaml_data, profile_yml_text)

    # --- Compensation ---
    comp_prefs = _extract_compensation_preferences(yaml_data)

    return {
        "countries": candidate_countries,
        "regions": candidate_regions,
        "country_display": COUNTRY_NAMES.get(country_code, country_code) if country_code else None,
        "work_authorization": work_auth,
        "target_roles": target_roles,
        "seniority_signals": detected_seniority,
        "domains": _unique_preserve(candidate_domains),
        "tools": tools,
        "workplace_preferences": workplace_prefs,
        "compensation": comp_prefs,
    }


# ---------------------------------------------------------------------------
# JobModel — structured JD pre-extraction
# ---------------------------------------------------------------------------

def _is_comp_context_line(line: str) -> bool:
    """True if a line is primarily about compensation, not work location."""
    return bool(_COMP_CONTEXT_RE.search(line))


def _extract_location_lines(text: str) -> list[str]:
    """Extract lines that signal work location/remote policy, excluding compensation context."""
    lines = []
    for raw in str(text or "").splitlines():
        line = " ".join(raw.split()).strip()
        if not line:
            continue
        lowered = line.lower()
        # Must mention a location/remote signal
        if not any(t in lowered for t in ("location", "remote", "hybrid", "on-site", "onsite",
                                           "eligible", "not available", "not eligible", "country",
                                           "region", "office", "telecommute")):
            continue
        # Skip lines that are clearly about compensation ranges
        if _is_comp_context_line(line):
            continue
        lines.append(line)
    return lines[:30]


def _extract_excluded_regions(text: str) -> list[str]:
    """Extract US state codes that are explicitly excluded from eligibility."""
    regions: set[str] = set()
    for window in _EXCLUSION_PHRASE_RE.findall(str(text or "")):
        # Only extract regions from exclusion contexts, not compensation contexts
        if _is_comp_context_line(window):
            continue
        regions.update(_us_regions_in_text(window))
    return sorted(regions)


def extract_location_policy(jd_text: str) -> dict:
    """
    Extract structured location policy from JD text.

    Key insight: compensation notes listing state pay ranges are NOT location restrictions.
    Only explicit eligibility/exclusion statements count.
    """
    text = str(jd_text or "")
    location_lines = _extract_location_lines(text)
    location_text = "\n".join(location_lines) if location_lines else text[:2000]
    lowered = location_text.lower()

    # Workplace type
    workplace_type = None
    if "hybrid" in lowered:
        workplace_type = "hybrid"
    elif "remote" in lowered or "telecommute" in lowered:
        workplace_type = "remote"
    elif any(t in lowered for t in ("on-site", "onsite", "in office", "in-office")):
        workplace_type = "on-site"

    eligible_countries = _country_codes_in_text(location_text)

    # For eligible_regions: only count when the role is NOT fully remote, OR when
    # the context is clearly about work location (not pay transparency)
    eligible_regions: list[str] = []
    if workplace_type in ("on-site", "hybrid"):
        eligible_regions = _us_regions_in_text(location_text)
    elif workplace_type == "remote":
        # For remote, only count regions if stated in an eligibility context, not pay context
        for line in location_lines:
            if not _is_comp_context_line(line):
                eligible_regions.extend(_us_regions_in_text(line))
        eligible_regions = sorted(set(eligible_regions))

    excluded_regions = _extract_excluded_regions(text)

    # Confidence signal: do we have explicit country restrictions?
    has_explicit_geo = bool(eligible_countries or excluded_regions)

    return {
        "workplace_type": workplace_type,
        "eligible_countries": eligible_countries,
        "eligible_regions": eligible_regions,
        "excluded_regions": excluded_regions,
        "has_explicit_geo": has_explicit_geo,
        "raw_signals": location_lines,
    }


def _classify_requirement_line(line: str, current_section: str | None = None) -> str:
    """Classify a single requirement line as must_have, nice_to_have, or important."""
    if current_section in ("must_have", "nice_to_have"):
        return current_section
    lowered = str(line or "").lower()
    if any(t in lowered for t in ("nice to have", "preferred", "bonus", "plus", "extra credit", "ideally")):
        return "nice_to_have"
    if _HARD_REQ_RE.search(line):
        return "must_have"
    if any(t in lowered for t in ("must have", "required", "mandatory", "minimum")):
        return "must_have"
    return "important"


def extract_requirement_groups(jd_text: str) -> dict[str, list[str]]:
    """
    Split JD requirements into must_have / nice_to_have / important groups.
    Tracks section headings to inherit classification across bullet lists.
    """
    groups: dict[str, list[str]] = {"must_have": [], "important": [], "nice_to_have": []}
    current: str | None = None

    for raw_line in str(jd_text or "").splitlines():
        stripped = raw_line.strip()
        line = stripped.strip(" -\t•*")
        if not line:
            continue

        heading = line.rstrip(":").strip()
        if _NICE_TO_HAVE_HEADING_RE.match(heading):
            current = "nice_to_have"
            continue
        if _MUST_HAVE_HEADING_RE.match(heading):
            current = "must_have"
            continue
        if _SECTION_STOP_RE.match(heading):
            current = None
            continue

        is_bullet = stripped.startswith(("-", "*", "•", "–"))
        if is_bullet or current:
            kind = _classify_requirement_line(line, current)
            if len(line) >= 10 and len(groups[kind]) < 20:
                groups[kind].append(line)

    for key in groups:
        groups[key] = _unique_preserve(groups[key])
    return groups


def build_job_model(jd_text: str, parsed_metadata: dict | None = None) -> dict:
    """
    Build a structured JobModel from JD text and optional pre-parsed metadata.

    parsed_metadata may contain: title, location, workplace_type, compensation,
    requirements_summary, nice_to_have_requirements, technical_tools_mentioned.
    """
    meta = parsed_metadata or {}
    text = str(jd_text or "")

    # Location policy — prefer deterministic extraction over metadata strings
    # because metadata location strings can be ambiguous (e.g. "United States")
    location_policy = extract_location_policy(text)

    # If parser already extracted workplace_type and we have no signal, trust it
    if not location_policy["workplace_type"] and meta.get("workplace_type"):
        location_policy["workplace_type"] = meta["workplace_type"]

    # If the metadata location field contains country info not found in JD text, merge
    meta_location_str = str(meta.get("location") or "")
    if meta_location_str and not location_policy["eligible_countries"]:
        extra_countries = _country_codes_in_text(meta_location_str)
        if extra_countries:
            location_policy["eligible_countries"] = extra_countries
            location_policy["has_explicit_geo"] = True

    # Requirements
    req_groups = extract_requirement_groups(text)

    # Merge parser-extracted requirements if present
    parser_must = list(meta.get("must_have_requirements") or meta.get("requirements_summary") or [])
    parser_nice = list(meta.get("nice_to_have_requirements") or [])
    if parser_must:
        req_groups["must_have"] = _unique_preserve(req_groups["must_have"] + parser_must)[:20]
    if parser_nice:
        req_groups["nice_to_have"] = _unique_preserve(req_groups["nice_to_have"] + parser_nice)[:20]

    # Technical tools
    parser_tools = list(meta.get("technical_tools_mentioned") or [])
    jd_tools = extract_tools(text)
    all_tools = _unique_preserve(parser_tools + jd_tools)

    # Compensation — record raw text but flag it as separate from location
    comp_raw = str(meta.get("compensation") or "")

    return {
        "location_policy": location_policy,
        "requirement_groups": req_groups,
        "technical_tools": all_tools,
        "compensation_raw": comp_raw,
    }


# ---------------------------------------------------------------------------
# Matching guardrails — operate on CandidateModel + JobModel
# ---------------------------------------------------------------------------

def evaluate_location_compatibility(candidate: dict, job: dict) -> dict:
    """
    Deterministic location compatibility check.

    Rules (in priority order):
    1. Candidate's region is in the job's excluded_regions → incompatible
    2. Job has explicit eligible_countries and candidate's countries overlap → compatible
    3. Job has explicit eligible_countries and candidate's countries don't overlap → incompatible
    4. Job is remote-only with no geo constraint → unknown (assume compatible, flag uncertainty)
    5. On-site/hybrid with region mismatch → incompatible
    6. No deterministic signal → unknown
    """
    policy = job.get("location_policy") or {}
    candidate_countries = set(candidate.get("countries") or [])
    candidate_regions = set(candidate.get("regions") or [])
    eligible_countries = set(policy.get("eligible_countries") or [])
    eligible_regions = set(policy.get("eligible_regions") or [])
    excluded_regions = set(policy.get("excluded_regions") or [])
    workplace_type = policy.get("workplace_type")

    # Rule 1: explicit exclusion
    if candidate_regions and excluded_regions:
        overlap = sorted(candidate_regions & excluded_regions)
        if overlap:
            return {
                "status": "incompatible",
                "reason": f"Candidate's state ({', '.join(overlap)}) is explicitly excluded from eligibility.",
                "confidence": "high",
            }

    # Rule 2 & 3: country-level check
    if eligible_countries and candidate_countries:
        overlap = sorted(candidate_countries & eligible_countries)
        if overlap:
            return {
                "status": "compatible",
                "reason": f"Candidate's country ({', '.join(overlap)}) is within eligible job scope.",
                "confidence": "high",
            }
        return {
            "status": "incompatible",
            "reason": (
                f"Job is restricted to {', '.join(sorted(eligible_countries))}; "
                f"candidate is in {', '.join(sorted(candidate_countries))}."
            ),
            "confidence": "high",
        }

    # Rule 4: fully remote, no geo constraint
    if workplace_type == "remote" and not eligible_countries and not eligible_regions and not excluded_regions:
        return {
            "status": "unknown",
            "reason": "Remote role with no explicit geographic eligibility constraint.",
            "confidence": "low",
        }

    # Rule 5: on-site/hybrid region mismatch
    if workplace_type in ("on-site", "hybrid") and eligible_regions and candidate_regions:
        overlap = sorted(candidate_regions & eligible_regions)
        if overlap:
            return {
                "status": "compatible",
                "reason": f"Candidate's region ({', '.join(overlap)}) matches job location.",
                "confidence": "high",
            }
        return {
            "status": "incompatible",
            "reason": (
                f"On-site/hybrid role located in {', '.join(sorted(eligible_regions))}; "
                f"candidate is in {', '.join(sorted(candidate_regions))}."
            ),
            "confidence": "medium",
        }

    return {
        "status": "unknown",
        "reason": "No deterministic location compatibility signal found.",
        "confidence": "low",
    }


def match_tools(jd_tools: list[str], candidate_tools: list[str]) -> list[dict]:
    """Match JD tools against candidate tools list."""
    candidate_keys = {_normalize_key(t): t for t in candidate_tools}
    results = []
    for tool in jd_tools:
        key = _normalize_key(tool)
        if key in candidate_keys:
            results.append({"tool": tool, "status": "direct", "profile_evidence": candidate_keys[key]})
        else:
            results.append({"tool": tool, "status": "missing", "profile_evidence": ""})
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_match_context(jd_text: str, profile_text: str, parsed_metadata: dict | None = None) -> dict:
    """
    Main entry point. Accepts raw JD text + combined profile text.

    Returns a match_context dict consumed by both job_fit_analyzer and ensemble_runner.
    The context is injected into every LLM prompt so the model reasons from facts,
    not from re-reading the raw JD for geographic signals.
    """
    # Build models
    sections = _profile_sections(profile_text)
    # Reconstruct profile_data dict from section text for candidate model
    profile_data = {
        "profile.yml": sections.get("identity (profile.yml)", sections.get("identity", "")),
        "portals.yml": sections.get("target keywords (portals.yml)", sections.get("target keywords", "")),
        "cv.md": sections.get("experience (cv.md)", sections.get("experience", "")),
        "_profile.md": sections.get("application strategy (_profile.md)", sections.get("application strategy", "")),
    }
    # If sections are empty (profile_text passed as raw combined text), use the full text
    if not any(profile_data.values()):
        profile_data = {"profile.yml": profile_text, "portals.yml": "", "cv.md": profile_text, "_profile.md": ""}

    candidate = build_candidate_model(profile_data)
    job = build_job_model(jd_text, parsed_metadata)

    location_result = evaluate_location_compatibility(candidate, job)
    tools_result = match_tools(job["technical_tools"], candidate["tools"])

    return {
        "candidate": candidate,
        "job": job,
        "matches": {
            "location": location_result,
            "technical_tools": tools_result,
        },
    }


def build_match_context_from_profile_data(
    jd_text: str,
    profile_data: dict[str, str],
    parsed_metadata: dict | None = None,
) -> dict:
    """
    Alternative entry point when profile_data dict is available directly
    (keys: profile.yml, portals.yml, cv.md, _profile.md).
    """
    candidate = build_candidate_model(profile_data)
    job = build_job_model(jd_text, parsed_metadata)
    location_result = evaluate_location_compatibility(candidate, job)
    tools_result = match_tools(job["technical_tools"], candidate["tools"])

    return {
        "candidate": candidate,
        "job": job,
        "matches": {
            "location": location_result,
            "technical_tools": tools_result,
        },
    }


def format_match_context(match_context: dict) -> str:
    return json.dumps(match_context, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Profile text builder (used by both analyzers)
# ---------------------------------------------------------------------------

def build_profile_text(profile_data: dict[str, str]) -> str:
    """Combine profile file contents into a single labelled text block for LLM system prompts."""
    return (
        f"=== IDENTITY (profile.yml) ===\n{profile_data.get('profile.yml', '')}\n\n"
        f"=== TARGET KEYWORDS (portals.yml) ===\n{profile_data.get('portals.yml', '')}\n\n"
        f"=== EXPERIENCE (cv.md) ===\n{profile_data.get('cv.md', '')}\n\n"
        f"=== APPLICATION STRATEGY (_profile.md) ===\n{profile_data.get('_profile.md', '')}"
    )


# ---------------------------------------------------------------------------
# Legacy compatibility shim (used by job_post_parser.py)
# ---------------------------------------------------------------------------

def extract_candidate_facts(profile_text: str) -> dict:
    """Legacy shim — returns minimal facts dict from combined profile text."""
    sections = _profile_sections(profile_text)
    profile_data = {
        "profile.yml": sections.get("identity (profile.yml)", sections.get("identity", profile_text[:3000])),
        "portals.yml": "",
        "cv.md": sections.get("experience (cv.md)", sections.get("experience", "")),
        "_profile.md": "",
    }
    model = build_candidate_model(profile_data)
    return {
        "countries": model["countries"],
        "regions": model["regions"],
        "remote_preference": "remote" if "remote" in model["workplace_preferences"]["preferred_types"] else None,
        "tools": model["tools"],
    }
