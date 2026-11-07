import re
from typing import Any
from urllib.parse import quote

from cachetools import LRUCache

import config

LOGO_CACHE_MAX = 2000
logo_dev_brand_cache: LRUCache = LRUCache(maxsize=LOGO_CACHE_MAX)

_COMP_JUNK_RE = re.compile(r"^(req|r|jr|job)[-_]?\d+[a-z0-9-]*$", re.IGNORECASE)
_COMP_JOB_PATH_RE = re.compile(r"^/?job/", re.IGNORECASE)
_COMP_HINT_RE = re.compile(
    r"(salary|compensation|base pay|pay range|ote|equity|bonus|hour|annual|year|yr|"
    r"[$€£]|\b\d{2,3}\s?k\b|\b\d{2,3}[,\s]\d{3}\b)",
    re.IGNORECASE,
)
_COMP_VALUE_RE = re.compile(
    r"[$€£]\s?\d|\b\d{2,3}\s?k\b|\b\d{2,3}[,\s]\d{3}\b|\b\d+\s?-\s?\d+\b",
    re.IGNORECASE,
)


def is_real_compensation(value: Any) -> bool:
    text = str(value if value is not None else "").strip()
    if not text:
        return False
    if _COMP_JUNK_RE.match(text):
        return False
    if _COMP_JOB_PATH_RE.match(text):
        return False
    if not _COMP_HINT_RE.search(text):
        return False
    return bool(_COMP_VALUE_RE.search(text))


def sanitize_job(row: dict) -> dict:
    job = dict(row)
    job["compensation"] = job.get("compensation") if is_real_compensation(job.get("compensation")) else None
    return job


def company_name(job: dict) -> str:
    source_key = job.get("source_key") or ""
    if job.get("provider") == "workday":
        return source_key.split("/")[0] if source_key else source_key
    return source_key


def normalize_label(value: Any) -> str:
    text = str(value if value is not None else "")
    return re.sub(r"\s+", " ", text).strip()


def job_mode(location: Any, employment_type: Any) -> str:
    normalized_location = normalize_label(location)
    normalized_employment_type = normalize_label(employment_type)
    combined = f"{normalized_location} {normalized_employment_type}".lower()

    if re.search(r"\bremote\b", combined):
        return "Remote"
    if re.search(r"\bhybrid\b", combined):
        return "Hybrid"
    if re.search(r"\bonsite\b|\bon-site\b|\bin-office\b|\boffice\b", combined):
        return "On-site"

    return normalized_location or normalized_employment_type or "n/a"


def job_compensation(compensation: Any) -> str:
    return normalize_label(compensation) or "n/a"


def decision_emoji(score: float) -> str:
    if score >= 4.75:
        return "🌟 Top pick"
    if score >= 4.5:
        return "🎯 Strong match"
    if score > 4.2:
        return "⚡ Quick apply"
    return "✅ Worth applying"


def company_logo_url(company: str) -> str | None:
    if not config.LOGO_DEV_PUBLISHABLE_KEY:
        return None

    normalized_company = normalize_label(company)
    if not normalized_company:
        return None

    token = quote(config.LOGO_DEV_PUBLISHABLE_KEY, safe="")
    cached_domain = logo_dev_brand_cache.get(normalized_company.lower())
    if cached_domain:
        path = quote(cached_domain, safe="")
        return f"https://img.logo.dev/{path}?token={token}&size=64&format=png&fallback=404"

    path = quote(normalized_company, safe="")
    return f"https://img.logo.dev/name/{path}?token={token}&size=64&format=png&fallback=404"


def company_website(company: str) -> str | None:
    normalized_company = normalize_label(company)
    if not normalized_company:
        return None

    cached_domain = logo_dev_brand_cache.get(normalized_company.lower())
    return f"https://{cached_domain}" if cached_domain else None
