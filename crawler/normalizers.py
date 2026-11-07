"""Employment-type canonicalization and skill-tier classification.

Ported verbatim from crawler/src/normalizers.ts — keyword lists, scoring
weights, and thresholds are copied exactly, not "cleaned up." The
standalone-roman-numeral-I regex uses a fixed-width lookbehind, which
Python's stdlib re supports directly (this isn't a JS-only regex feature).
"""

import re
from typing import Literal

EmploymentTypeCanonical = Literal[
    "Full-time", "Part-time", "Contract", "Internship", "Temporary", "Volunteer"
]
SkillTier = Literal["intern", "entry", "mid", "senior"]

_ATS_ID_RE = re.compile(r"^[A-Za-z]{0,4}[\d\-_/]{3,}$")
_INTERN_RE = re.compile(r"\bintern(ship)?\b")
_VOLUNTEER_RE = re.compile(r"\bvolunteer\b")
_TEMP_RE = re.compile(r"\btemp(orar(y|ily))?\b|\bcasual\b")
_PART_TIME_RE = re.compile(r"\bpart[\s_-]?time\b|\bp[\s_-]?t\b")
_CONTRACT_RE = re.compile(r"\b(contract(or)?|freelance|independent contractor|ctr)\b")
_FULL_TIME_RE = re.compile(r"\b(full[\s_-]?time|f[\s_-]?t|permanent|regular|cdi|employee)\b")


def canonicalize_employment_type(raw: str | None) -> EmploymentTypeCanonical | None:
    if not raw:
        return None
    s = raw.strip()
    # Discard misplaced ATS job IDs (e.g. "JR-12345", "REQ-001")
    if _ATS_ID_RE.match(s):
        return None

    t = s.lower()
    if _INTERN_RE.search(t):
        return "Internship"
    if _VOLUNTEER_RE.search(t):
        return "Volunteer"
    if _TEMP_RE.search(t):
        return "Temporary"
    if _PART_TIME_RE.search(t):
        return "Part-time"
    if _CONTRACT_RE.search(t):
        return "Contract"
    if _FULL_TIME_RE.search(t):
        return "Full-time"
    return None


_SENIOR_STRONG_RE = re.compile(r"\b(chief|cto|ceo|coo|cpo|ciso|vp|vice\s+president|director)\b")
_PRINCIPAL_RE = re.compile(r"\b(principal|distinguished|fellow)\b")
_STAFF_LEAD_RE = re.compile(r"\b(staff|lead|head\s+of)\b")
_SENIOR_RE = re.compile(r"\b(senior|sr\.?)\b")
_ARCHITECT_MANAGER_RE = re.compile(r"\b(architect|manager)\b")
_LEVEL_RE = re.compile(r"\bl(?:evel\s*)?[4-9]\b")
_ROMAN_IV_V_RE = re.compile(r"\b(iv|v)\b")
_ROMAN_III_RE = re.compile(r"\biii\b")
_JUNIOR_RE = re.compile(r"\b(junior|jr\.?)\b")
_ENTRY_RE = re.compile(r"\b(trainee|graduate|new\s*grad|entry[\s-]?level|associate)\b")
_INTERN_TIER_RE = re.compile(r"\b(intern(ship)?)\b")
_ROMAN_II_RE = re.compile(r"\bii\b")
_ROMAN_I_RE = re.compile(r"(?<!\b[a-z])\bi\b(?!\b[a-z])")


def classify_tier(title: str | None) -> SkillTier:
    if not title:
        return "mid"
    t = title.lower()

    score = 0

    # Strong senior signals
    if _SENIOR_STRONG_RE.search(t):
        score += 50
    if _PRINCIPAL_RE.search(t):
        score += 40
    if _STAFF_LEAD_RE.search(t):
        score += 30
    if _SENIOR_RE.search(t):
        score += 20
    if _ARCHITECT_MANAGER_RE.search(t):
        score += 15
    # Level numbers: L4-L9 or Level 4-9
    if _LEVEL_RE.search(t):
        score += 15
    # Roman numerals IV, V = senior; III = mild senior lean
    if _ROMAN_IV_V_RE.search(t):
        score += 15
    if _ROMAN_III_RE.search(t):
        score += 10

    # Junior signals
    if _JUNIOR_RE.search(t):
        score -= 20
    if _ENTRY_RE.search(t):
        score -= 25
    if _INTERN_TIER_RE.search(t):
        score -= 100
    # Roman numeral I, II = entry lean
    if _ROMAN_II_RE.search(t):
        score -= 5
    if _ROMAN_I_RE.search(t):
        score -= 10

    if score <= -50:
        return "intern"
    if score <= -5:
        return "entry"
    if score >= 15:
        return "senior"
    return "mid"


def as_string(value: object) -> str | None:
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed if trimmed else None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return None


def first_string(*values: object) -> str | None:
    for value in values:
        string_value = as_string(value)
        if string_value is not None:
            return string_value
    return None


def join_strings(values: object, separator: str = ", ") -> str | None:
    if not isinstance(values, list):
        return as_string(values)

    strings = [s for v in values if (s := as_string(v)) is not None]
    return separator.join(strings) if strings else None


def compact_object_strings(values: object) -> str | None:
    if not values or not isinstance(values, dict):
        return as_string(values)

    strings = [s for v in values.values() if (s := as_string(v)) is not None]
    return ", ".join(strings) if strings else None
