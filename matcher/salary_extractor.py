"""
Salary extraction from job description text.

Detects salary patterns including:
- Ranges: $120,000 - $160,000, $80k-$100k, €90 000–€110 000
- Single amounts: $150,000, £75k
- Location-based blocks: "Based in Colorado: $155,520 - $194,400"
- Hourly rates: $45/hr, $60 per hour
- OTE/commission: $200k OTE, €120k + bonus

Returns structured data with min, max, currency, period, and location qualifiers.
"""

import re
from dataclasses import dataclass
from typing import Optional


CURRENCY_SYMBOL_TO_CODE = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "A$": "AUD",
    "C$": "CAD",
}

US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming",
    "washington d.c.", "district of columbia", "dc",
}

US_STATE_ABBR = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi",
    "id", "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi",
    "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc",
    "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut",
    "vt", "va", "wa", "wv", "wi", "wy", "dc",
}

UK_CITIES = {
    "london", "manchester", "birmingham", "leeds", "glasgow", "edinburgh",
    "bristol", "liverpool", "sheffield", "cambridge", "oxford",
}


@dataclass
class SalaryEntry:
    raw_text: str
    currency: str
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    period: str = "annual"
    location_qualifier: Optional[str] = None
    is_estimated: bool = False
    ote: bool = False
    has_bonus: bool = False
    equity: bool = False


def _parse_amount(raw: str) -> float:
    cleaned = raw.strip().replace(",", "").replace(" ", "")
    cleaned = cleaned.lstrip("$€£")
    if cleaned.lower().endswith("k"):
        return float(cleaned[:-1]) * 1_000
    return float(cleaned)


def _detect_currency(text: str) -> str:
    for symbol, code in CURRENCY_SYMBOL_TO_CODE.items():
        if symbol in text:
            return code
    return "USD"


def _detect_period(text: str) -> str:
    lower = text.lower()
    if re.search(r'\b(per\s*hour|/hr|hourly|\bhr\b)\b', lower):
        return "hourly"
    if re.search(r'\b(per\s*month|monthly)\b', lower):
        return "monthly"
    if re.search(r'\b(per\s*week|weekly)\b', lower):
        return "weekly"
    return "annual"


def _is_estimated(text: str) -> bool:
    return bool(re.search(r'\b(estimated|approximate|around|about|typically|target\s*pay)\b', text, re.IGNORECASE))


def _has_ote(text: str) -> bool:
    return bool(re.search(r'\bote\b', text, re.IGNORECASE))


def _has_bonus(text: str) -> bool:
    return bool(re.search(r'\b(bonus|commission|incentive)\b', text, re.IGNORECASE))


def _has_equity(text: str) -> bool:
    return bool(re.search(r'\b(equity|rsu|stock|option)\b', text, re.IGNORECASE))


def _extract_location_qualifier(text: str) -> Optional[str]:
    location_patterns = [
        r'(?:based\s+in|located\s+in|for\s+(?:candidates\s+)?in|work\s+from)\s+([^:]+?)(?:\s*[:\.]\s*)',
        r'(?:for\s+)?([^:]+?)\s+(?:residents|area|region)\s*[:\.]',
    ]
    for pattern in location_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            loc = match.group(1).strip().rstrip(":.,")
            if len(loc) > 2:
                return loc
    return None


def _contains_location_reference(text: str) -> bool:
    lower = text.lower()
    for state in US_STATES:
        if state in lower:
            return True
    for abbr in US_STATE_ABBR:
        if re.search(rf'\b{abbr}\b', lower):
            return True
    for city in UK_CITIES:
        if city in lower:
            return True
    return bool(re.search(r'\b(remote|us|uk|europe|asia)\b', lower))


def _extract_location_pay_blocks(text: str) -> list[SalaryEntry]:
    entries = []
    pattern = re.compile(
        r'(?:based\s+in|located\s+in|for\s+(?:candidates\s+)?in|work\s+from)\s+'
        r'([^:\n]+?)\s*[:\.]\s*'
        r'([\$€£])\s?(\d{2,3}(?:[,\s]\d{3}|[kK]))\s*'
        r'(?:-|–|to|—)\s*'
        r'([\$€£]?)\s?(\d{2,3}(?:[,\s]\d{3}|[kK]))',
        re.IGNORECASE
    )
    for match in pattern.finditer(text):
        location = match.group(1).strip()
        currency = CURRENCY_SYMBOL_TO_CODE.get(match.group(2), "USD")
        min_amount = _parse_amount(match.group(3))
        max_amount = _parse_amount(match.group(5))
        raw = match.group(0).strip()
        entries.append(SalaryEntry(
            raw_text=raw,
            currency=currency,
            min_amount=min_amount,
            max_amount=max_amount,
            period=_detect_period(raw),
            location_qualifier=location if _contains_location_reference(location) else None,
            is_estimated=_is_estimated(raw),
            ote=_has_ote(raw),
            has_bonus=_has_bonus(raw),
            equity=_has_equity(raw),
        ))
    return entries


def _extract_ranges(text: str) -> list[SalaryEntry]:
    entries = []
    pattern = re.compile(
        r'([\$€£])\s?(\d{2,3}(?:[,\s]\d{3}|[kK]))\s*'
        r'(?:-|–|to|—)\s*'
        r'([\$€£]?)\s?(\d{2,3}(?:[,\s]\d{3}|[kK]))',
        re.IGNORECASE
    )
    for match in pattern.finditer(text):
        currency = CURRENCY_SYMBOL_TO_CODE.get(match.group(1), "USD")
        min_amount = _parse_amount(match.group(2))
        max_amount = _parse_amount(match.group(4))
        raw = match.group(0).strip()
        if min_amount > 5_000_000 or max_amount > 5_000_000:
            continue
        if max_amount < min_amount:
            min_amount, max_amount = max_amount, min_amount
        entries.append(SalaryEntry(
            raw_text=raw,
            currency=currency,
            min_amount=min_amount,
            max_amount=max_amount,
            period=_detect_period(raw),
            location_qualifier=_extract_location_qualifier(raw),
            is_estimated=_is_estimated(raw),
            ote=_has_ote(raw),
            has_bonus=_has_bonus(raw),
            equity=_has_equity(raw),
        ))
    return entries


def _extract_single_amounts(text: str) -> list[SalaryEntry]:
    entries = []
    pattern = re.compile(
        r'([\$€£])\s?(\d{2,3}(?:[,\s]\d{3}|[kK]))\b',
        re.IGNORECASE
    )
    for match in pattern.finditer(text):
        currency = CURRENCY_SYMBOL_TO_CODE.get(match.group(1), "USD")
        amount = _parse_amount(match.group(2))
        if amount > 5_000_000:
            continue
        raw = match.group(0).strip()
        entries.append(SalaryEntry(
            raw_text=raw,
            currency=currency,
            min_amount=amount,
            max_amount=amount,
            period=_detect_period(raw),
            location_qualifier=_extract_location_qualifier(raw),
            is_estimated=_is_estimated(raw),
            ote=_has_ote(raw),
            has_bonus=_has_bonus(raw),
            equity=_has_equity(raw),
        ))
    return entries


def _extract_hourly_rates(text: str) -> list[SalaryEntry]:
    entries = []
    pattern = re.compile(
        r'([\$€£])\s?(\d{1,3}(?:\.\d{1,2})?)\s*(?:/hr|per\s*hour|hourly)',
        re.IGNORECASE
    )
    for match in pattern.finditer(text):
        currency = CURRENCY_SYMBOL_TO_CODE.get(match.group(1), "USD")
        hourly = float(match.group(2))
        raw = match.group(0).strip()
        entries.append(SalaryEntry(
            raw_text=raw,
            currency=currency,
            min_amount=hourly,
            max_amount=hourly,
            period="hourly",
            is_estimated=_is_estimated(raw),
        ))
    return entries


def filter_salary_entries(entries: list[SalaryEntry]) -> list[SalaryEntry]:
    filtered = []
    for entry in entries:
        raw = entry.raw_text
        if re.match(r'^(req|r|jr|job)[-_]?\d+[a-z0-9-]*$', raw, re.IGNORECASE):
            continue
        if re.match(r'^/?job/', raw, re.IGNORECASE):
            continue
        if entry.min_amount is not None and entry.min_amount < 1_000:
            continue
        filtered.append(entry)
    return filtered


def deduplicate_entries(entries: list[SalaryEntry]) -> list[SalaryEntry]:
    if not entries:
        return []
    seen = set()
    unique = []
    for entry in entries:
        key = (entry.currency, entry.period, entry.min_amount, entry.max_amount)
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    return unique


def extract_salaries(text: str) -> list[SalaryEntry]:
    if not text or len(text) < 20:
        return []

    all_entries: list[SalaryEntry] = []

    all_entries.extend(_extract_location_pay_blocks(text))
    all_entries.extend(_extract_ranges(text))
    all_entries.extend(_extract_hourly_rates(text))
    all_entries.extend(_extract_single_amounts(text))

    all_entries = filter_salary_entries(all_entries)
    all_entries = deduplicate_entries(all_entries)

    return all_entries


def match_location(candidate_location: str, entries: list[SalaryEntry]) -> Optional[SalaryEntry]:
    if not entries or not candidate_location:
        return entries[0] if entries else None

    candidate_lower = candidate_location.lower().strip()
    candidate_tokens = set(re.findall(r'[a-z]+', candidate_lower))

    for entry in entries:
        if not entry.location_qualifier:
            continue
        loc_lower = entry.location_qualifier.lower()
        loc_tokens = set(re.findall(r'[a-z]+', loc_lower))
        if candidate_tokens & loc_tokens:
            return entry

    for entry in entries:
        if entry.location_qualifier:
            return entry

    return entries[0] if entries else None


def format_salary_display(entry: SalaryEntry) -> str:
    parts = []
    if entry.min_amount == entry.max_amount:
        if entry.period == "hourly":
            parts.append(f"{entry.currency}{entry.min_amount:,.0f}/hr")
        else:
            parts.append(f"{entry.currency}{entry.min_amount:,.0f}")
    else:
        if entry.period == "hourly":
            parts.append(f"{entry.currency}{entry.min_amount:,.0f} - {entry.currency}{entry.max_amount:,.0f}/hr")
        else:
            parts.append(f"{entry.currency}{entry.min_amount:,.0f} - {entry.currency}{entry.max_amount:,.0f}")

    if entry.ote:
        parts.append("OTE")
    if entry.has_bonus:
        parts.append("+ bonus")
    if entry.equity:
        parts.append("+ equity")
    if entry.is_estimated:
        parts.append("(estimated)")
    if entry.location_qualifier:
        parts.append(f"[{entry.location_qualifier}]")

    return " ".join(parts)


def extract_salary_structured(text: str, candidate_location: Optional[str] = None) -> Optional[dict]:
    entries = extract_salaries(text)
    if not entries:
        return None

    if candidate_location:
        best = match_location(candidate_location, entries)
    else:
        best = entries[0]

    return {
        "raw_text": best.raw_text,
        "currency": best.currency,
        "min": best.min_amount,
        "max": best.max_amount,
        "period": best.period,
        "location": best.location_qualifier,
        "is_estimated": best.is_estimated,
        "all_entries": [
            {
                "raw_text": e.raw_text,
                "currency": e.currency,
                "min": e.min_amount,
                "max": e.max_amount,
                "period": e.period,
                "location": e.location_qualifier,
                "is_estimated": e.is_estimated,
            }
            for e in entries
        ],
    }
