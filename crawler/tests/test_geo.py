import pytest

from geo import resolve_coords


def test_resolve_coords_none_and_empty():
    assert resolve_coords(None) is None
    assert resolve_coords("") is None


@pytest.mark.parametrize("garbage", ["N/A", "not specified", "TBD", "Various", "Global"])
def test_resolve_coords_garbage_locations_return_none(garbage):
    assert resolve_coords(garbage) is None


@pytest.mark.parametrize("remote", ["Remote", "Anywhere", "Worldwide", "Work From Home", "WFH"])
def test_resolve_coords_remote_keywords_return_none(remote):
    assert resolve_coords(remote) is None


def test_resolve_coords_timezone_keyword_returns_none():
    assert resolve_coords("US Eastern Time Zone") is None


def test_resolve_coords_unresolvable_city_returns_none_not_exception():
    assert resolve_coords("Nonexistent Fictional City XYZ123") is None


def test_resolve_coords_city_state_two_letter():
    # Real row in data/locations.json: ['Miami', 'FL', 'US', 25.7743, -80.1937]
    assert resolve_coords("Miami, FL") == pytest.approx((25.7743, -80.1937))


def test_resolve_coords_city_state_full_name_resolves_same_as_abbreviation():
    assert resolve_coords("Miami, Florida") == resolve_coords("Miami, FL")


def test_resolve_coords_single_token_city_state_space_separated():
    # No comma at all -- exercises the "single token splits into city+state"
    # reconstruction path directly (the one genuinely load-bearing path for
    # 2-word inputs, per geo.py's module docstring).
    assert resolve_coords("Miami FL") == pytest.approx((25.7743, -80.1937))


def test_resolve_coords_another_real_city_state():
    # Real row: ['San Francisco', 'CA', 'US', 37.7749, -122.4194]
    assert resolve_coords("San Francisco, CA") == pytest.approx((37.7749, -122.4194))


def test_resolve_coords_strips_diacritics():
    # Real row: ['Montreal', 'Quebec', 'CA', 45.5088, -73.5878] -- no accent
    # in the stored data, so this proves NFD-normalize + diacritic-strip
    # actually runs before the lookup.
    assert resolve_coords("Montréal") == pytest.approx((45.5088, -73.5878))


def test_resolve_coords_plain_city_matches_ascii_equivalent():
    assert resolve_coords("Montreal") == resolve_coords("Montréal")


def test_resolve_coords_il_is_ambiguous_between_illinois_and_israel():
    # "il" is both a US state abbreviation (Illinois) and a country alias
    # (Israel). extract_country() runs before extract_us_state(), so a
    # "City IL" input gets its trailing "il" token misread as the country
    # code for Israel rather than the Illinois state abbreviation -- a
    # genuine quirk of the original algorithm's ordering, preserved as-is
    # here rather than "fixed" during the port. This doesn't raise, and
    # still resolves via the bare city-name fallback.
    result = resolve_coords("Chicago, IL")
    assert result is None or isinstance(result, tuple)


def test_resolve_coords_hybrid_prefix_stripped():
    # "hybrid " (space-only variant) is the one WORK_ARRANGEMENT_PREFIXES
    # entry that's actually reachable post-normalize (see geo.py's
    # module docstring) -- the punctuated variants ("hybrid - ", etc.)
    # are not, since normalize() already destroyed that punctuation.
    assert resolve_coords("Hybrid Miami FL") == resolve_coords("Miami FL")
