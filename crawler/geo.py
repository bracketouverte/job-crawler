"""Location string -> (lat, lon) resolution.

Ported line-for-line from crawler/src/geo.ts, including its accidental
quirks — do not "fix" these while reading this file:

  1. normalize() replaces every non-alphanumeric character (commas,
     dashes, parens, colons) with a space *before* resolve_coords() does
     anything else. This means resolve_coords()'s own `s.split(",")` call
     almost always yields a single-element list (no commas survive
     normalize()), and the punctuation-stripping steps later in the
     pipeline (strip_work_arrangement's dash/colon/comma prefix variants,
     the parenthetical-strip regex, the "- remote" suffix strip) are
     largely unreachable dead code, since that punctuation is already
     gone. The genuinely load-bearing path for "City, ST" inputs is the
     single-token reconstruction block (split on space, check if the last
     *word* is a US state) — not the comma split.
  2. Because of (1), 3-segment inputs like "Miami, FL, USA" do not
     reliably resolve to city+state+country the way the multi-token
     extract_country()/extract_us_state() logic might suggest at a
     glance — they typically fall through to a single combined-city
     lookup and miss.

These are preserved exactly as the TypeScript version behaves today.
Changing them would be a real geocoding-accuracy change, not a faithful
port — flag it for a deliberate follow-up decision instead of fixing it
here.
"""

import json
import re
import unicodedata
from pathlib import Path

Coords = tuple[float, float]

US_STATES: dict[str, str] = {
    "al": "AL",
    "alabama": "AL",
    "ak": "AK",
    "alaska": "AK",
    "az": "AZ",
    "arizona": "AZ",
    "ar": "AR",
    "arkansas": "AR",
    "ca": "CA",
    "california": "CA",
    "co": "CO",
    "colorado": "CO",
    "ct": "CT",
    "connecticut": "CT",
    "de": "DE",
    "delaware": "DE",
    "fl": "FL",
    "florida": "FL",
    "ga": "GA",
    "georgia": "GA",
    "hi": "HI",
    "hawaii": "HI",
    "id": "ID",
    "idaho": "ID",
    "il": "IL",
    "illinois": "IL",
    "in": "IN",
    "indiana": "IN",
    "ia": "IA",
    "iowa": "IA",
    "ks": "KS",
    "kansas": "KS",
    "ky": "KY",
    "kentucky": "KY",
    "la": "LA",
    "louisiana": "LA",
    "me": "ME",
    "maine": "ME",
    "md": "MD",
    "maryland": "MD",
    "ma": "MA",
    "massachusetts": "MA",
    "mi": "MI",
    "michigan": "MI",
    "mn": "MN",
    "minnesota": "MN",
    "ms": "MS",
    "mississippi": "MS",
    "mo": "MO",
    "missouri": "MO",
    "mt": "MT",
    "montana": "MT",
    "ne": "NE",
    "nebraska": "NE",
    "nv": "NV",
    "nevada": "NV",
    "nh": "NH",
    "new hampshire": "NH",
    "nj": "NJ",
    "new jersey": "NJ",
    "nm": "NM",
    "new mexico": "NM",
    "ny": "NY",
    "new york": "NY",
    "nc": "NC",
    "north carolina": "NC",
    "nd": "ND",
    "north dakota": "ND",
    "oh": "OH",
    "ohio": "OH",
    "ok": "OK",
    "oklahoma": "OK",
    "or": "OR",
    "oregon": "OR",
    "pa": "PA",
    "pennsylvania": "PA",
    "ri": "RI",
    "rhode island": "RI",
    "sc": "SC",
    "south carolina": "SC",
    "sd": "SD",
    "south dakota": "SD",
    "tn": "TN",
    "tennessee": "TN",
    "tx": "TX",
    "texas": "TX",
    "ut": "UT",
    "utah": "UT",
    "vt": "VT",
    "vermont": "VT",
    "va": "VA",
    "virginia": "VA",
    "wa": "WA",
    "washington": "WA",
    "wv": "WV",
    "west virginia": "WV",
    "wi": "WI",
    "wisconsin": "WI",
    "wy": "WY",
    "wyoming": "WY",
    "dc": "DC",
    "d c": "DC",
    "district of columbia": "DC",
    "washington dc": "DC",
    "washington d c": "DC",
}

COUNTRY_ALIASES: dict[str, str] = {
    "us": "US",
    "usa": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "united states": "US",
    "united states of america": "US",
    "america": "US",
    "can": "CA",
    "canada": "CA",
    "mx": "MX",
    "mex": "MX",
    "mexico": "MX",
    "gb": "GB",
    "uk": "GB",
    "united kingdom": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "de": "DE",
    "germany": "DE",
    "deutschland": "DE",
    "fr": "FR",
    "france": "FR",
    "es": "ES",
    "spain": "ES",
    "it": "IT",
    "italy": "IT",
    "nl": "NL",
    "netherlands": "NL",
    "holland": "NL",
    "se": "SE",
    "sweden": "SE",
    "no": "NO",
    "norway": "NO",
    "dk": "DK",
    "denmark": "DK",
    "fi": "FI",
    "finland": "FI",
    "ch": "CH",
    "switzerland": "CH",
    "at": "AT",
    "austria": "AT",
    "be": "BE",
    "belgium": "BE",
    "pl": "PL",
    "poland": "PL",
    "pt": "PT",
    "portugal": "PT",
    "au": "AU",
    "australia": "AU",
    "nz": "NZ",
    "new zealand": "NZ",
    "in": "IN",
    "india": "IN",
    "cn": "CN",
    "china": "CN",
    "jp": "JP",
    "japan": "JP",
    "sg": "SG",
    "singapore": "SG",
    "br": "BR",
    "brazil": "BR",
    "za": "ZA",
    "south africa": "ZA",
    "il": "IL",
    "israel": "IL",
    "ae": "AE",
    "uae": "AE",
    "united arab emirates": "AE",
}

CITY_ALIASES: dict[str, str] = {
    "new york": "new york city",
    "nyc": "new york city",
    "new york ny": "new york city",
    "bangalore": "bengaluru",
    "bombay": "mumbai",
    "madras": "chennai",
    "calcutta": "kolkata",
    "peking": "beijing",
}

NYC_BOROUGHS = {"brooklyn", "queens", "bronx", "staten island", "manhattan"}

REMOTE_KEYWORDS = ["remote", "anywhere", "worldwide", "work from home", "wfh"]
TIMEZONE_KEYWORDS = ["time zone", "timezone"]

GARBAGE_LOCATIONS = {
    "",
    "not specified",
    "n/a",
    "none",
    "tbd",
    "unspecified",
    "multiple locations",
    "various",
    "flexible",
    "other",
    "global",
    "multiple",
    "varies",
    "various locations",
}

WORK_ARRANGEMENT_PREFIXES = [
    "hybrid in ",
    "hybrid - ",
    "hybrid: ",
    "hybrid, ",
    "hybrid ",
    "on-site in ",
    "on site in ",
    "onsite in ",
    "in-office in ",
    "in office in ",
    "based in ",
    "located in ",
    "remote in ",
    "remote - ",
    "remote: ",
]

JUNK_SUFFIXES = {"area", "metro", "region", "greater", "metropolitan"}

_DIACRITIC_RE = re.compile(r"[\u0300-\u036f]")  # combining diacritical marks block
_NON_ALPHANUM_RE = re.compile(r"[^a-z0-9 ]")
_WHITESPACE_RE = re.compile(r"\s+")
_FT_RE = re.compile(r"\bft\b")
_MT_RE = re.compile(r"\bmt\b")
_ST_RE = re.compile(r"\bst\b")
_N_RE = re.compile(r"\bn\b")
_S_RE = re.compile(r"\bs\b")
_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)\s*")
_DASH_REMOTE_RE = re.compile(r"[-—]\s*remote")
_TRIM_PUNCT_RE = re.compile(r"^[-,—\s]+|[-,—\s]+$")

_DATA_PATH = Path(__file__).resolve().parent / "data" / "locations.json"

_maps: dict[str, dict[str, Coords]] | None = None


def _normalize(s: str) -> str:
    s = s.lower()
    s = unicodedata.normalize("NFD", s)
    s = _DIACRITIC_RE.sub("", s)
    s = _NON_ALPHANUM_RE.sub(" ", s)
    s = _WHITESPACE_RE.sub(" ", s)
    return s.strip()


def _build_maps() -> dict[str, dict[str, Coords]]:
    with open(_DATA_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    schema: list[str] = raw["schema"]
    data: list[list] = raw["data"]
    city_i = schema.index("city")
    admin_i = schema.index("admin")
    country_i = schema.index("country")
    lat_i = schema.index("lat")
    lng_i = schema.index("lng")

    maps: dict[str, dict[str, Coords]] = {
        "city_admin_country": {},
        "city_country": {},
        "city_admin": {},
        "city": {},
    }

    for row in data:
        city_n = _normalize(str(row[city_i] or ""))
        admin_n = _normalize(str(row[admin_i] or ""))
        country = str(row[country_i] or "")
        coords: Coords = (float(row[lat_i]), float(row[lng_i]))

        if not city_n:
            continue

        if admin_n and country:
            k = f"{city_n}|{admin_n}|{country}"
            maps["city_admin_country"].setdefault(k, coords)
        if country:
            k = f"{city_n}|{country}"
            maps["city_country"].setdefault(k, coords)
        if admin_n:
            k = f"{city_n}|{admin_n}"
            maps["city_admin"].setdefault(k, coords)
        maps["city"].setdefault(city_n, coords)

    return maps


def _get_maps() -> dict[str, dict[str, Coords]]:
    global _maps
    if _maps is None:
        _maps = _build_maps()
    return _maps


def _clean_token(t: str) -> str:
    words = t.split(" ")
    while words and words[-1] in JUNK_SUFFIXES:
        words.pop()
    return " ".join(words)


def _strip_work_arrangement(s: str) -> str:
    for prefix in WORK_ARRANGEMENT_PREFIXES:
        if s.startswith(prefix):
            return s[len(prefix) :]
    return s


def _extract_us_state(tokens: list[str]) -> tuple[str | None, list[str]]:
    for i in range(len(tokens) - 1, -1, -1):
        t = tokens[i]
        if t in US_STATES:
            return US_STATES[t], tokens[:i] + tokens[i + 1 :]
    return None, tokens


def _extract_country(tokens: list[str]) -> tuple[str | None, list[str]]:
    if len(tokens) < 2:
        return None, tokens
    last = tokens[-1]
    if last in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[last], tokens[:-1]
    return None, tokens


def resolve_coords(location: str | None) -> Coords | None:
    if not location:
        return None

    maps = _get_maps()
    s = _normalize(location)

    if not s or s in GARBAGE_LOCATIONS:
        return None
    if any(kw in s for kw in REMOTE_KEYWORDS):
        return None
    if any(kw in s for kw in TIMEZONE_KEYWORDS):
        return None

    # Apply abbreviation expansions before stripping work arrangement
    s = _FT_RE.sub("fort", s)
    s = _MT_RE.sub("mount", s)
    s = _ST_RE.sub("saint", s)
    s = _N_RE.sub("north", s)
    s = _S_RE.sub("south", s)

    s = _strip_work_arrangement(s)

    # Strip parentheticals: "(HQ)", "(Remote)", etc.
    s = _PARENTHETICAL_RE.sub(" ", s).strip()
    # Strip "- remote" / "-- remote" suffixes
    s = _DASH_REMOTE_RE.sub("", s).strip()
    s = _TRIM_PUNCT_RE.sub("", s)

    if not s:
        return None

    tokens = [_clean_token(t.strip()) for t in s.split(",")]
    tokens = [t for t in tokens if t]

    # Dedupe consecutive identical tokens
    tokens = [t for i, t in enumerate(tokens) if i == 0 or t != tokens[i - 1]]

    if not tokens:
        return None

    # Check full joined string against city aliases
    joined = " ".join(tokens)
    if joined in CITY_ALIASES:
        tokens = [CITY_ALIASES[joined]]

    # Single token: check if it's "city state" space-separated (e.g. "miami fl")
    if len(tokens) == 1:
        words = tokens[0].split(" ")
        if len(words) >= 2 and words[-1] in US_STATES:
            state = words[-1]
            city = " ".join(words[:-1])
            tokens = [city, state]

    # Single token: country-only
    if len(tokens) == 1 and tokens[0] in COUNTRY_ALIASES:
        return None

    country, tokens = _extract_country(tokens)

    if country == "US" or country is None:
        state, tokens = _extract_us_state(tokens)
        if state:
            if country is None:
                country = "US"
            # Rebuild: remaining tokens are city parts
            city = " ".join(tokens)
            if city in CITY_ALIASES:
                city = CITY_ALIASES[city]
            if not city:
                return None

            # NYC borough -> New York City
            if city in NYC_BOROUGHS and state == "NY":
                city = "new york city"

            admin_n = state.lower()
            return (
                maps["city_admin_country"].get(f"{city}|{admin_n}|{country}")
                or maps["city_country"].get(f"{city}|{country}")
                or maps["city_admin"].get(f"{city}|{admin_n}")
                or maps["city"].get(city)
            )

    # No US state extracted -- use remaining tokens
    city = None
    admin = None

    if len(tokens) >= 2:
        admin = tokens[-1]
        city = " ".join(tokens[:-1])
    elif len(tokens) == 1:
        city = tokens[0]

    if not city:
        return None
    if city in CITY_ALIASES:
        city = CITY_ALIASES[city]
    if city in NYC_BOROUGHS and (admin or "").lower() == "ny":
        city = "new york city"

    admin_n = _normalize(admin) if admin else None

    if admin_n and country:
        hit = maps["city_admin_country"].get(f"{city}|{admin_n}|{country}")
        if hit:
            return hit
    if country:
        hit = maps["city_country"].get(f"{city}|{country}")
        if hit:
            return hit
    if admin_n:
        hit = maps["city_admin"].get(f"{city}|{admin_n}")
        if hit:
            return hit
    return maps["city"].get(city)
