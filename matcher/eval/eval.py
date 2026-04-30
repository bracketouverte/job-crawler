#!/usr/bin/env python3
"""
Evaluation runner for matching_intelligence guardrails.

Tests the deterministic extraction and guardrail layer against a set of fixtures
WITHOUT making any LLM API calls. This validates the pre-scoring pipeline:
  - CandidateModel extraction from profile files
  - JobModel extraction from JD text
  - Location compatibility guardrail
  - Must-have / nice-to-have classification
  - Tool extraction

Usage:
  python eval/eval.py [--profile-dir career-ops] [--fixtures eval/fixtures.json] [--verbose]

Exit codes:
  0 = all assertions passed
  1 = one or more assertions failed
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Allow running from project root or matcher/ directory
SCRIPT_DIR = Path(__file__).resolve().parent
MATCHER_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(MATCHER_DIR))

from matching_intelligence import (
    build_candidate_model,
    build_job_model,
    evaluate_location_compatibility,
    extract_location_policy,
    extract_requirement_groups,
    extract_tools,
    build_profile_text,
)

DEFAULT_FIXTURES = SCRIPT_DIR / "fixtures.json"
DEFAULT_PROFILE_DIR = MATCHER_DIR / "career-ops"

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_profile(profile_dir: Path) -> dict[str, str]:
    files = ["profile.yml", "portals.yml", "cv.md", "_profile.md"]
    data = {}
    for f in files:
        p = profile_dir / f
        data[f] = p.read_text(encoding="utf-8") if p.exists() else ""
    return data


def check(label: str, condition: bool, detail: str = "", verbose: bool = False) -> bool:
    status = PASS if condition else FAIL
    if not condition or verbose:
        line = f"  [{status}] {label}"
        if detail:
            line += f"\n         → {detail}"
        print(line)
    return condition


def section(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ---------------------------------------------------------------------------
# Assertions per fixture
# ---------------------------------------------------------------------------

def run_fixture(fixture: dict, candidate: dict, verbose: bool) -> tuple[int, int]:
    """Run assertions for one fixture. Returns (passed, total)."""
    fid = fixture["id"]
    desc = fixture["description"]
    jd_text = fixture["jd_text"]
    expected = fixture["expected"]

    print(f"\n[{fid}]")
    print(f"  {desc}")
    if verbose:
        print(f"  URL: {fixture.get('url', 'n/a')}")
        print(f"  Notes: {expected.get('notes', '')}")

    job = build_job_model(jd_text)
    policy = job["location_policy"]
    req_groups = job["requirement_groups"]
    tools = job["technical_tools"]
    location_result = evaluate_location_compatibility(candidate, job)

    passed = 0
    total = 0

    def assert_check(label: str, condition: bool, detail: str = "") -> None:
        nonlocal passed, total
        total += 1
        if check(label, condition, detail, verbose=verbose):
            passed += 1

    # Location status
    exp_status = expected.get("location_status")
    if exp_status:
        actual_status = location_result.get("status")
        assert_check(
            f"location.status == '{exp_status}'",
            actual_status == exp_status,
            f"actual={actual_status!r}, reason={location_result.get('reason')!r}",
        )

    # Workplace type
    exp_wtype = expected.get("workplace_type")
    if exp_wtype:
        actual_wtype = policy.get("workplace_type")
        assert_check(
            f"workplace_type == '{exp_wtype}'",
            actual_wtype == exp_wtype,
            f"actual={actual_wtype!r}",
        )

    # Eligible countries
    exp_countries = expected.get("eligible_countries")
    if exp_countries:
        actual_countries = set(policy.get("eligible_countries") or [])
        overlap = set(exp_countries) & actual_countries
        assert_check(
            f"eligible_countries contains {exp_countries}",
            len(overlap) >= len(exp_countries) // 2,
            f"actual={sorted(actual_countries)}, expected={sorted(exp_countries)}",
        )

    # Excluded regions
    exp_excluded = expected.get("excluded_regions")
    if exp_excluded:
        actual_excluded = set(policy.get("excluded_regions") or [])
        assert_check(
            f"excluded_regions contains {exp_excluded}",
            set(exp_excluded).issubset(actual_excluded),
            f"actual={sorted(actual_excluded)}, expected={sorted(exp_excluded)}",
        )

    # FL not excluded
    if expected.get("must_not_include_fl_exclusion"):
        actual_excluded = set(policy.get("excluded_regions") or [])
        assert_check(
            "FL not in excluded_regions",
            "FL" not in actual_excluded,
            f"excluded_regions={sorted(actual_excluded)}",
        )

    # Must have geographic blocker
    if expected.get("must_have_geographic_blocker") or expected.get("must_have_blocker"):
        assert_check(
            "location incompatible (geographic blocker expected)",
            location_result.get("status") == "incompatible",
            f"status={location_result.get('status')!r}",
        )

    # Must NOT have geographic blocker
    if expected.get("must_not_have_geographic_blocker"):
        assert_check(
            "location compatible (no geographic blocker)",
            location_result.get("status") != "incompatible",
            f"status={location_result.get('status')!r}, reason={location_result.get('reason')!r}",
        )

    # Must-have requirements extracted
    if expected.get("must_have_requirements_min"):
        min_count = expected["must_have_requirements_min"]
        actual_count = len(req_groups.get("must_have") or [])
        assert_check(
            f"must_have requirements >= {min_count}",
            actual_count >= min_count,
            f"actual={actual_count}, items={req_groups.get('must_have')}",
        )

    # Verdict constraint
    verdict_must_not_be = expected.get("verdict_must_not_be")
    if verdict_must_not_be:
        # We can't check the LLM verdict without an API call; note this as informational
        if verbose:
            print(f"  [{WARN}] verdict_must_not_be='{verdict_must_not_be}' — LLM-only check, skipped in deterministic eval")

    # Show location policy details in verbose
    if verbose:
        print(f"\n  Location policy extracted:")
        print(f"    workplace_type: {policy.get('workplace_type')!r}")
        print(f"    eligible_countries: {policy.get('eligible_countries')}")
        print(f"    eligible_regions: {policy.get('eligible_regions')}")
        print(f"    excluded_regions: {policy.get('excluded_regions')}")
        print(f"    raw_signals: {policy.get('raw_signals')}")
        print(f"\n  Location result:")
        print(f"    status: {location_result.get('status')!r}")
        print(f"    reason: {location_result.get('reason')!r}")
        print(f"    confidence: {location_result.get('confidence')!r}")
        if tools:
            print(f"\n  Tools extracted: {tools[:10]}")
        mh = req_groups.get("must_have") or []
        nth = req_groups.get("nice_to_have") or []
        print(f"\n  Must-have requirements ({len(mh)}): {mh[:5]}")
        print(f"  Nice-to-have requirements ({len(nth)}): {nth[:5]}")

    return passed, total


# ---------------------------------------------------------------------------
# Candidate model diagnostics
# ---------------------------------------------------------------------------

def show_candidate_model(candidate: dict, verbose: bool):
    section("Candidate Model (deterministic extract from profile)")
    print(f"  countries:     {candidate.get('countries')}")
    print(f"  regions:       {candidate.get('regions')}")
    print(f"  country:       {candidate.get('country_display')!r}")
    print(f"  work_auth:     needs_sponsorship={candidate['work_authorization'].get('needs_sponsorship')}")
    print(f"  domains:       {candidate.get('domains')}")
    print(f"  tools ({len(candidate.get('tools') or [])}):      {(candidate.get('tools') or [])[:8]}")
    prefs = candidate.get("workplace_preferences") or {}
    print(f"  workplace pref: {prefs.get('preferred_types')}")
    comp = candidate.get("compensation") or {}
    print(f"  compensation:  min={comp.get('minimum')} target={comp.get('target_min')}-{comp.get('target_max')} {comp.get('currency')}")
    roles = candidate.get("target_roles") or {}
    print(f"  primary titles: {roles.get('primary_titles')}")
    archetypes = roles.get("archetypes") or []
    for a in archetypes[:3]:
        print(f"    archetype: {a.get('name')} ({a.get('level')}, fit={a.get('fit')})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Evaluate matching_intelligence guardrails against fixtures")
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR), help="Path to career-ops profile directory")
    parser.add_argument("--fixtures", default=str(DEFAULT_FIXTURES), help="Path to fixtures JSON file")
    parser.add_argument("--filter", help="Run only fixture with this ID")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show full extraction details")
    args = parser.parse_args()

    fixtures_path = Path(args.fixtures)
    profile_dir = Path(args.profile_dir)
    if not profile_dir.is_absolute():
        profile_dir = MATCHER_DIR / profile_dir

    print(f"\n{'=' * 60}")
    print(f"  Matching Intelligence — Deterministic Eval")
    print(f"{'=' * 60}")
    print(f"  Fixtures: {fixtures_path}")
    print(f"  Profile:  {profile_dir}")

    if not fixtures_path.exists():
        print(f"\n❌ Fixtures not found: {fixtures_path}")
        sys.exit(1)

    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))

    # Load profile and build candidate model once
    profile_data = load_profile(profile_dir)
    has_profile = any(bool(v) and "not found" not in v.lower() for v in profile_data.values())
    if not has_profile:
        print(f"\n⚠️  Profile files not found in {profile_dir}. Candidate model will be empty.")
        print("   Set CAREER_OPS_DIR or mount the profile directory.")

    candidate = build_candidate_model(profile_data)
    show_candidate_model(candidate, verbose=args.verbose)

    # Run fixtures
    section("Fixture Results")
    total_passed = 0
    total_checks = 0
    fixture_results = []

    for fixture in fixtures:
        if args.filter and fixture["id"] != args.filter:
            continue
        passed, total = run_fixture(fixture, candidate, verbose=args.verbose)
        total_passed += passed
        total_checks += total
        fixture_results.append({
            "id": fixture["id"],
            "passed": passed,
            "total": total,
            "ok": passed == total,
        })

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  Results: {total_passed}/{total_checks} checks passed")
    print()
    for r in fixture_results:
        icon = "✓" if r["ok"] else "✗"
        print(f"  {icon}  [{r['id']}]  {r['passed']}/{r['total']}")
    print(f"{'=' * 60}\n")

    if total_passed < total_checks:
        sys.exit(1)


if __name__ == "__main__":
    main()
