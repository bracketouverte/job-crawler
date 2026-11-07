import pytest

from normalizers import (
    as_string,
    canonicalize_employment_type,
    classify_tier,
    compact_object_strings,
    first_string,
    join_strings,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("", None),
        ("Intern", "Internship"),
        ("Internship", "Internship"),
        ("Volunteer", "Volunteer"),
        ("Temp", "Temporary"),
        ("Temporary", "Temporary"),
        ("Casual", "Temporary"),
        ("Part-time", "Part-time"),
        ("PT", "Part-time"),
        ("Contractor", "Contract"),
        ("Freelance", "Contract"),
        ("Full-time", "Full-time"),
        ("FT", "Full-time"),
        ("Permanent", "Full-time"),
        ("CDI", "Full-time"),
        ("Employee", "Full-time"),
        ("something unrecognized", None),
        ("JR-12345", None),
        ("REQ-001", None),
    ],
)
def test_canonicalize_employment_type(raw, expected):
    assert canonicalize_employment_type(raw) == expected


@pytest.mark.parametrize(
    "title,expected",
    [
        (None, "mid"),
        ("", "mid"),
        ("Chief Technology Officer", "senior"),
        ("VP of Engineering", "senior"),
        ("Director of Sales", "senior"),
        ("Principal Engineer", "senior"),
        ("Distinguished Engineer", "senior"),
        ("Staff Software Engineer", "senior"),
        ("Lead Product Manager", "senior"),
        ("Head of Design", "senior"),
        ("Senior Backend Engineer", "senior"),
        ("Sr. Data Scientist", "senior"),
        ("Solutions Architect", "senior"),
        ("Engineering Manager", "senior"),
        ("Software Engineer L5", "senior"),
        ("Software Engineer Level 6", "senior"),
        ("Engineer IV", "senior"),
        ("Engineer V", "senior"),
        ("Engineer III", "mid"),
        ("Junior Developer", "entry"),
        ("Jr. Developer", "entry"),
        ("Graduate Software Engineer", "entry"),
        ("New Grad Engineer", "entry"),
        ("Entry-level Analyst", "entry"),
        ("Associate Product Manager", "entry"),
        ("Engineer II", "entry"),
        ("Software Engineer I", "entry"),
        ("Intern", "intern"),
        ("Summer Internship", "intern"),
        ("Software Engineer", "mid"),
        # "manager" alone scores +15 (architect|manager rule), crossing the
        # senior threshold -- this is real behavior of the ported scoring
        # rules, not a test bug: any "X Manager" title is classified senior.
        ("Product Manager", "senior"),
    ],
)
def test_classify_tier(title, expected):
    assert classify_tier(title) == expected


def test_as_string():
    assert as_string("  hello  ") == "hello"
    assert as_string("   ") is None
    assert as_string(True) == "true"
    assert as_string(False) == "false"
    assert as_string(42) == "42"
    assert as_string(3.5) == "3.5"
    assert as_string(None) is None
    assert as_string({"a": 1}) is None


def test_first_string():
    assert first_string(None, "", "  ", "value") == "value"
    assert first_string(None, None) is None
    assert first_string(1, "two") == "1"


def test_join_strings():
    assert join_strings(["a", "b", None, "  "]) == "a, b"
    assert join_strings([]) is None
    assert join_strings("solo") == "solo"
    assert join_strings(["x", "y"], separator=" | ") == "x | y"


def test_compact_object_strings():
    assert compact_object_strings({"a": "1", "b": None, "c": "3"}) == "1, 3"
    assert compact_object_strings({}) is None
    assert compact_object_strings(None) is None
    assert compact_object_strings("bare") == "bare"
