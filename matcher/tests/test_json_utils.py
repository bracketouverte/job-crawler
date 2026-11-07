import pytest

from lib.json_utils import (
    clamp,
    compute_overall_score,
    extract_json_payload,
    infer_application_recommendation,
    infer_verdict,
    normalize_analysis_result,
    normalize_scorecard,
    normalize_text_list,
    sanitize_text,
    score_100_to_5,
)


def test_clamp():
    assert clamp(5, 1, 3) == 3
    assert clamp(-1, 1, 3) == 1
    assert clamp(2, 1, 3) == 2


def test_normalize_text_list_filters_placeholders_and_blanks():
    # None isn't special-cased — it stringifies to the literal "None" and survives.
    assert normalize_text_list(["real reason", "force1", "  ", None]) == ["real reason", "None"]
    assert normalize_text_list(None) == []
    assert normalize_text_list("single value") == ["single value"]
    assert normalize_text_list("blocker1") == []


def test_sanitize_text():
    assert sanitize_text("  hello  ") == "hello"
    assert sanitize_text("Optional comment") == ""
    assert sanitize_text(None) == ""


def test_infer_verdict():
    assert infer_verdict(80, []) == "yes"
    assert infer_verdict(60, []) == "with_adjustments"
    assert infer_verdict(40, []) == "no"
    assert infer_verdict(70, ["blocker"]) == "with_adjustments"
    assert infer_verdict(50, ["blocker"]) == "no"


def test_score_100_to_5_bounds():
    assert score_100_to_5(0) == 1.0
    assert score_100_to_5(100) == 5.0
    assert score_100_to_5(50) == 3.0


def test_infer_application_recommendation():
    assert infer_application_recommendation(4.5) == "apply_now"
    assert infer_application_recommendation(4.0) == "worth_applying"
    assert infer_application_recommendation(3.5) == "only_if_strategic"
    assert infer_application_recommendation(2.0) == "do_not_apply"


def test_extract_json_payload_plain():
    assert extract_json_payload('{"a": 1}') == {"a": 1}


def test_extract_json_payload_fenced():
    text = '```json\n{"a": 1}\n```'
    assert extract_json_payload(text) == {"a": 1}


def test_extract_json_payload_embedded_in_prose():
    text = 'Sure, here is the JSON: {"a": 1} — hope that helps.'
    assert extract_json_payload(text) == {"a": 1}


def test_extract_json_payload_empty():
    assert extract_json_payload("") == {}
    assert extract_json_payload(None) == {}


def test_extract_json_payload_invalid_raises():
    with pytest.raises(Exception):
        extract_json_payload("not json at all")


def test_normalize_scorecard_defaults_missing_dimension():
    result = normalize_scorecard({"core_skills": {"score": 4.5, "reason": "Strong fit"}})
    assert result["core_skills"]["score"] == 4.5
    assert result["core_skills"]["reason"] == "Strong fit"
    assert result["relevant_experience"]["score"] == 3.0


def test_normalize_scorecard_clamps_and_handles_bad_types():
    result = normalize_scorecard({"core_skills": {"score": "not-a-number"}})
    assert result["core_skills"]["score"] == 3.0
    result2 = normalize_scorecard({"core_skills": 6.0})
    assert result2["core_skills"]["score"] == 5.0


def test_compute_overall_score_with_blockers_penalty():
    scorecard = normalize_scorecard({})
    base = compute_overall_score(scorecard, [])
    with_one_blocker = compute_overall_score(scorecard, ["b1"])
    with_many_blockers = compute_overall_score(scorecard, ["b1", "b2", "b3", "b4"])
    assert with_one_blocker == base - 7
    assert with_many_blockers == base - 21  # capped at 21


def test_normalize_analysis_result_full_shape():
    raw = {
        "scorecard": {"core_skills": {"score": 4.0, "reason": "ok"}},
        "blockers": ["real blocker"],
        "forces": ["force1", "genuine strength"],
        "faiblesses": ["real weakness"],
        "remarques": "optional comment",
        "verdict": "",
        "posting_legitimacy": {"assessment": "high_confidence", "reasoning": ["signal1", "real signal"]},
        "evidence": [
            {
                "requirement": "r",
                "profile_evidence": "e",
                "fit": "bogus",
                "source": "cv",
                "importance": "bogus",
            }
        ],
        "requirement_match": [
            {"requirement": "r", "strength": "bogus", "gap_type": "bogus", "is_blocker": True}
        ],
        "tool_match": [{"tool": "SQL", "strength": "bogus", "importance": "bogus"}],
        "gaps": [{"gap": "g", "severity": "bogus", "blocker": True}],
        "role_summary": {"domain": "fintech"},
        "standout_differentiator": "unique",
        "_pipeline_tag": "maverick",
    }
    result = normalize_analysis_result(raw)
    assert result["pipeline"] == "maverick"
    assert result["blockers"] == ["real blocker"]
    assert result["forces"] == ["genuine strength"]
    assert result["evidence"][0]["fit"] == "partial"
    assert result["evidence"][0]["importance"] == "important"
    assert result["requirement_match"][0]["strength"] == "partial"
    assert result["requirement_match"][0]["gap_type"] == "unknown"
    assert result["tool_match"][0]["strength"] == "missing"
    assert result["gaps"][0]["severity"] == "medium"
    assert result["role_summary"]["domain"] == "fintech"
    assert "score" in result and "score_5" in result
    assert result["remarques"] == ""


def test_normalize_analysis_result_non_dict_input():
    result = normalize_analysis_result("not a dict")
    assert result["scorecard"]["core_skills"]["score"] == 3.0
    assert result["blockers"] == []
