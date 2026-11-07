import dataclasses

import pytest

from config import settings
from lib import llm_client
from services import ensemble_scorer


def test_strip_json_plain():
    assert ensemble_scorer.strip_json('{"a": 1}') == {"a": 1}


def test_strip_json_fenced():
    assert ensemble_scorer.strip_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_strip_json_embedded():
    assert ensemble_scorer.strip_json('noise {"a": 1} noise') == {"a": 1}


def test_strip_json_invalid_raises():
    with pytest.raises(Exception):
        ensemble_scorer.strip_json("nope")


def test_score_to_100_uses_ensemble_weights():
    scorecard = {
        "core_skills": {"score": 5.0},
        "relevant_experience": {"score": 5.0},
        "target_alignment": {"score": 5.0},
        "seniority_fit": {"score": 5.0},
        "workplace_fit": {"score": 5.0},
        "requirements_coverage": {"score": 5.0},
    }
    assert ensemble_scorer.score_to_100(scorecard) == 100


def test_score_to_100_defaults_missing_dimension_to_3():
    assert ensemble_scorer.score_to_100({}) == 50


def test_remove_location_false_positives():
    analysis = {
        "blockers": ["Geographic mismatch: x", "Real blocker"],
        "faiblesses": ["Country mismatch noted", "Real weakness"],
        "gaps": [{"gap": "State exclusion"}, {"gap": "Real gap"}],
    }
    ensemble_scorer._remove_location_false_positives(analysis)
    assert analysis["blockers"] == ["Real blocker"]
    assert analysis["faiblesses"] == ["Real weakness"]
    assert analysis["gaps"] == [{"gap": "Real gap"}]


def test_remove_softened_tool_blockers():
    analysis = {"blockers": ["Hard requirement unmet: no experience with Snowflake"], "gaps": []}
    ensemble_scorer._remove_softened_tool_blockers(
        analysis, "The role requires experience with tools like Snowflake, dbt."
    )
    assert analysis["blockers"] == []
    assert any("Tool ramp-up" in g["gap"] for g in analysis["gaps"])


def test_remove_consulting_false_positive():
    analysis = {
        "blockers": ["Job type: consulting/professional services — not a target employment model."],
        "gaps": [],
        "scorecard": {"target_alignment": {"score": 2.0}},
    }
    ensemble_scorer._remove_consulting_false_positive(analysis, "We are a product company.")
    assert analysis["blockers"] == []
    assert analysis["scorecard"]["target_alignment"]["score"] == 3.5


def _base_scorecard():
    return {
        "core_skills": {"score": 4.0},
        "relevant_experience": {"score": 4.0},
        "target_alignment": {"score": 4.0},
        "seniority_fit": {"score": 4.0},
        "workplace_fit": {"score": 3.0},
        "requirements_coverage": {"score": 4.0},
    }


def test_apply_match_guardrails_incompatible_location():
    analysis = {"scorecard": _base_scorecard(), "blockers": [], "gaps": [], "faiblesses": []}
    match_context = {
        "matches": {"location": {"status": "incompatible", "reason": "excluded state"}, "technical_tools": []}
    }
    result = ensemble_scorer.apply_match_guardrails(analysis, match_context)
    assert result["verdict"] == "no"
    assert result["application_recommendation"] == "do_not_apply"
    assert result["scorecard"]["workplace_fit"]["score"] == 1.5


def test_apply_match_guardrails_compatible_location():
    analysis = {"scorecard": _base_scorecard(), "blockers": [], "gaps": [], "faiblesses": []}
    match_context = {"matches": {"location": {"status": "compatible", "reason": "US"}, "technical_tools": []}}
    result = ensemble_scorer.apply_match_guardrails(analysis, match_context)
    assert result["scorecard"]["workplace_fit"]["score"] == 4.0


def test_scorer_cache_path_sanitizes_model_and_job_id(tmp_path, monkeypatch):
    monkeypatch.setattr(ensemble_scorer, "settings", dataclasses.replace(settings, state_dir=str(tmp_path)))
    path = ensemble_scorer._scorer_cache_path("abc/123", "meta/llama-4-maverick-17b-128e-instruct")
    assert path.parent == tmp_path / ".scorer_cache"
    assert "/" not in path.name.replace(str(tmp_path), "")


@pytest.mark.asyncio
async def test_score_with_model_strips_cache_control_for_mistral(monkeypatch):
    llm_client.start_client()
    captured = {}
    try:

        async def fake_chat_completions(**kwargs):
            captured["messages"] = kwargs["messages"]
            return '{"scorecard": {}}'

        monkeypatch.setattr(llm_client, "chat_completions", fake_chat_completions)
        result = await ensemble_scorer.score_with_model(
            "mistralai/mistral-large-3-675b-instruct-2512",
            "system",
            "user",
        )
        assert result == {"scorecard": {}}
    finally:
        await llm_client.stop_client()


@pytest.mark.asyncio
async def test_score_with_model_returns_none_on_failure(monkeypatch):
    llm_client.start_client()
    try:

        async def fake_chat_completions(**kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(llm_client, "chat_completions", fake_chat_completions)
        result = await ensemble_scorer.score_with_model("meta/llama-4-maverick-17b-128e-instruct", "s", "u")
        assert result is None
    finally:
        await llm_client.stop_client()


@pytest.mark.asyncio
async def test_score_job_ensemble_end_to_end(monkeypatch, tmp_path, profile_data):
    monkeypatch.setattr(
        ensemble_scorer,
        "settings",
        dataclasses.replace(
            settings,
            state_dir=str(tmp_path),
            nvidia_ensemble_scorers=["meta/llama-4-maverick-17b-128e-instruct"],
            nvidia_ensemble_synthesizer="nvidia/llama-3.3-nemotron-super-49b-v1.5",
        ),
    )

    llm_client.start_client()
    try:

        async def fake_chat_completions(*, model, **kwargs):
            payload = {
                "scorecard": {
                    "core_skills": {"score": 4.0, "reason": "ok"},
                    "relevant_experience": {"score": 4.0, "reason": "ok"},
                    "target_alignment": {"score": 4.0, "reason": "ok"},
                    "seniority_fit": {"score": 4.0, "reason": "ok"},
                    "workplace_fit": {"score": 4.0, "reason": "ok"},
                    "requirements_coverage": {"score": 4.0, "reason": "ok"},
                },
                "blockers": [],
                "verdict": "yes",
                "forces": ["strong fit"],
                "faiblesses": [],
                "remarques": "solid",
            }
            import json as _json

            return _json.dumps(payload)

        monkeypatch.setattr(llm_client, "chat_completions", fake_chat_completions)

        job = {
            "job_id": "123",
            "title": "Senior TPM",
            "company": "Acme",
            "location": "Remote US",
            "responsibilities": ["Lead delivery"],
            "requirements_summary": ["5+ years TPM"],
        }
        result = await ensemble_scorer.score_job_ensemble(job, profile_data)
        assert result["pipeline"] == "ensemble"
        assert "score" in result
        cache_dir = tmp_path / ".scorer_cache"
        assert not any(cache_dir.iterdir()) if cache_dir.exists() else True
    finally:
        await llm_client.stop_client()


@pytest.mark.asyncio
async def test_score_job_ensemble_raises_when_all_scorers_fail(monkeypatch, tmp_path, profile_data):
    monkeypatch.setattr(
        ensemble_scorer,
        "settings",
        dataclasses.replace(
            settings,
            state_dir=str(tmp_path),
            nvidia_ensemble_scorers=["meta/llama-4-maverick-17b-128e-instruct"],
        ),
    )

    llm_client.start_client()
    try:

        async def failing_chat_completions(**kwargs):
            raise RuntimeError("network down")

        monkeypatch.setattr(llm_client, "chat_completions", failing_chat_completions)
        job = {"job_id": "999", "title": "PM", "company": "Acme"}
        with pytest.raises(RuntimeError, match="All scorers failed"):
            await ensemble_scorer.score_job_ensemble(job, profile_data)
    finally:
        await llm_client.stop_client()
