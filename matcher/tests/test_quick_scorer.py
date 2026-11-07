import pytest

from lib import llm_client
from services import quick_scorer


def test_build_system_prompt_embeds_profile_fields(profile_data):
    prompt = quick_scorer.build_system_prompt(profile_data)
    assert profile_data["profile.yml"] in prompt
    assert profile_data["cv.md"] in prompt
    assert profile_data["portals.yml"] in prompt
    assert profile_data["_profile.md"] in prompt


def test_synthesize_jd_text_includes_all_sections():
    record = {
        "title": "Senior PM",
        "company": "Acme",
        "provider": "greenhouse",
        "location": "Remote US",
        "employment_type": "full-time",
        "workplace_type": "remote",
        "compensation": "$150k-$180k",
        "posted_datetime": "2026-01-01",
        "jd_concepts": ["product management", "saas"],
        "technical_tools_mentioned": ["SQL", "Figma"],
        "responsibilities": ["Own the roadmap"],
        "must_have_requirements": ["5+ years PM experience"],
        "nice_to_have_requirements": ["Fintech background"],
    }
    text = quick_scorer.synthesize_jd_text(record)
    assert "Title: Senior PM" in text
    assert "Own the roadmap" in text
    assert "5+ years PM experience" in text
    assert "Fintech background" in text
    assert "SQL, Figma" in text


def test_synthesize_jd_text_skips_empty_fields():
    text = quick_scorer.synthesize_jd_text({"title": "PM"})
    assert "Company" not in text
    assert "Title: PM" in text


def test_add_gap_once_deduplicates_case_insensitively():
    analysis = {"gaps": [{"gap": "Missing SQL"}]}
    quick_scorer.add_gap_once(analysis, {"gap": "missing sql"})
    assert len(analysis["gaps"]) == 1
    quick_scorer.add_gap_once(analysis, {"gap": "Missing Python"})
    assert len(analysis["gaps"]) == 2


def test_remove_incompatible_location_false_positives():
    analysis = {
        "blockers": ["Geographic mismatch: excluded state", "Real blocker"],
        "faiblesses": ["Location mismatch noted", "Real weakness"],
        "gaps": [{"gap": "State exclusion issue"}, {"gap": "Real gap"}],
    }
    quick_scorer.remove_incompatible_location_false_positives(analysis)
    assert analysis["blockers"] == ["Real blocker"]
    assert analysis["faiblesses"] == ["Real weakness"]
    assert analysis["gaps"] == [{"gap": "Real gap"}]


def test_enforce_hard_blocker_guardrail_caps_score_and_adds_blocker():
    analysis = {
        "scorecard": {"relevant_experience": {"score": 4.0, "reason": "ok"}},
        "requirement_match": [
            {
                "requirement": "5 years payroll",
                "is_blocker": True,
                "gap_type": "direct_gap",
                "strength": "missing",
                "mitigation": "",
            }
        ],
        "blockers": [],
        "gaps": [],
    }
    quick_scorer._enforce_hard_blocker_guardrail(analysis)
    assert analysis["scorecard"]["relevant_experience"]["score"] == 2.5
    assert any("payroll" in b for b in analysis["blockers"])
    assert any("payroll" in g["gap"] for g in analysis["gaps"])


def test_enforce_hard_blocker_guardrail_skips_when_mitigated():
    analysis = {
        "scorecard": {"relevant_experience": {"score": 4.0, "reason": "ok"}},
        "requirement_match": [
            {
                "requirement": "5 years payroll",
                "is_blocker": True,
                "gap_type": "direct_gap",
                "strength": "missing",
                "mitigation": "adjacent regulated-industry experience",
            }
        ],
        "blockers": [],
        "gaps": [],
    }
    quick_scorer._enforce_hard_blocker_guardrail(analysis)
    assert analysis["scorecard"]["relevant_experience"]["score"] == 4.0


def test_remove_softened_tool_blockers_demotes_to_gap():
    analysis = {
        "blockers": ["Hard requirement unmet: no experience with Snowflake"],
        "gaps": [],
    }
    jd_text = "The role requires experience with tools like Snowflake, dbt."
    quick_scorer._remove_softened_tool_blockers(analysis, jd_text)
    assert analysis["blockers"] == []
    assert any("Tool ramp-up" in g["gap"] for g in analysis["gaps"])


def test_remove_softened_tool_blockers_noop_without_softening_language():
    analysis = {"blockers": ["Hard requirement unmet: no experience with Snowflake"], "gaps": []}
    quick_scorer._remove_softened_tool_blockers(analysis, "You must have Snowflake experience.")
    assert analysis["blockers"] == ["Hard requirement unmet: no experience with Snowflake"]


def test_remove_consulting_false_positive_strips_without_explicit_signal():
    analysis = {
        "blockers": ["Job type: consulting/professional services — not a target employment model."],
        "gaps": [{"gap": "Job type: consulting mismatch"}],
        "scorecard": {"target_alignment": {"score": 2.0, "reason": "capped"}},
    }
    quick_scorer._remove_consulting_false_positive(
        analysis, "We build our own product, no client work mentioned."
    )
    assert analysis["blockers"] == []
    assert analysis["scorecard"]["target_alignment"]["score"] == 3.5


def test_remove_consulting_false_positive_keeps_with_explicit_signal():
    analysis = {
        "blockers": ["Job type: consulting/professional services — not a target employment model."],
        "gaps": [],
        "scorecard": {"target_alignment": {"score": 2.0, "reason": "capped"}},
    }
    quick_scorer._remove_consulting_false_positive(
        analysis, "This role involves billable hours and client delivery."
    )
    assert len(analysis["blockers"]) == 1
    assert analysis["scorecard"]["target_alignment"]["score"] == 2.0


def _base_analysis():
    return {
        "scorecard": {
            "core_skills": {"score": 4.0, "reason": "r"},
            "relevant_experience": {"score": 4.0, "reason": "r"},
            "target_alignment": {"score": 4.0, "reason": "r"},
            "seniority_fit": {"score": 4.0, "reason": "r"},
            "workplace_fit": {"score": 3.0, "reason": "r"},
            "requirements_coverage": {"score": 4.0, "reason": "r"},
        },
        "blockers": [],
        "gaps": [],
        "faiblesses": [],
    }


def test_apply_match_guardrails_compatible_location_raises_workplace_score():
    analysis = _base_analysis()
    match_context = {
        "matches": {"location": {"status": "compatible", "reason": "US-based"}, "technical_tools": []}
    }
    result = quick_scorer.apply_match_guardrails(analysis, match_context)
    assert result["scorecard"]["workplace_fit"]["score"] == 4.0
    assert result["verdict"] in {"yes", "with_adjustments", "no"}
    assert "score" in result


def test_apply_match_guardrails_incompatible_location_forces_no_verdict():
    analysis = _base_analysis()
    match_context = {
        "matches": {"location": {"status": "incompatible", "reason": "excluded state"}, "technical_tools": []}
    }
    result = quick_scorer.apply_match_guardrails(analysis, match_context)
    assert result["verdict"] == "no"
    assert result["application_recommendation"] == "do_not_apply"
    assert result["scorecard"]["workplace_fit"]["score"] == 1.5
    assert any("Geographic mismatch" in b for b in result["blockers"])


def test_apply_match_guardrails_builds_tool_match_from_context_when_missing():
    analysis = _base_analysis()
    match_context = {
        "matches": {
            "location": {"status": "unknown", "reason": ""},
            "technical_tools": [{"tool": "SQL", "status": "direct", "profile_evidence": "SQL"}],
        }
    }
    result = quick_scorer.apply_match_guardrails(analysis, match_context)
    assert result["tool_match"][0]["tool"] == "SQL"
    assert result["tool_match"][0]["strength"] == "direct"


@pytest.mark.asyncio
async def test_score_job_quick_end_to_end(monkeypatch, profile_data):
    llm_client.start_client()
    try:

        async def fake_chat_completions(**kwargs):
            return (
                '{"scorecard": {"core_skills": {"score": 4.5, "reason": "strong"}}, '
                '"blockers": [], "verdict": "yes"}'
            )

        monkeypatch.setattr(llm_client, "chat_completions", fake_chat_completions)
        job = {
            "title": "Senior TPM",
            "company": "Acme",
            "location": "Remote US",
            "responsibilities": ["Lead cross-functional delivery"],
            "requirements_summary": ["5+ years TPM experience"],
        }
        result = await quick_scorer.score_job_quick(
            job, profile_data, model="meta/llama-4-maverick-17b-128e-instruct"
        )
        assert result["pipeline"] == "maverick"
        assert "score" in result
    finally:
        await llm_client.stop_client()
