"""JSON/LLM-response parsing and normalization helpers.

Ported verbatim (logic unchanged) from matcher/job_fit_analyzer.py per the
matcher rewrite plan's "Do NOT change ... the scoring logic" instruction.
"""

import json
import re

DEFAULT_DIMENSION_SCORE = 3.0
SCORE_WEIGHTS = {
    "core_skills": 0.30,
    "relevant_experience": 0.20,
    "target_alignment": 0.20,
    "seniority_fit": 0.10,
    "workplace_fit": 0.10,
    "requirements_coverage": 0.10,
}
SCORING_DIMENSIONS = {
    "core_skills": "Alignment of core technical and functional skills.",
    "relevant_experience": "Proximity between the profile's proven experience and the actual role responsibilities.",
    "target_alignment": "Alignment with the candidate's target archetypes, goals, and preferences.",
    "seniority_fit": "Fit between the expected seniority level and the candidate's likely level for this role.",
    "workplace_fit": "Compatibility with remote/hybrid/on-site policy, geography, and work constraints.",
    "requirements_coverage": "Coverage of explicit JD requirements, including must-haves.",
}
PLACEHOLDER_TEXTS = {
    "force1",
    "force2",
    "force3",
    "faiblesse1",
    "faiblesse2",
    "faiblesse3",
    "blocker1",
    "commentaire optionnel",
    "explication courte et factuelle",
    "recommendation (yes/no/with adjustments)",
    "yes / no / with_adjustments",
    "the strongest differentiator versus market peers",
    "resume en une phrase de ce que l'entreprise achete vraiment",
    "optional comment",
}


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def normalize_text_list(value):
    if isinstance(value, list):
        normalized = []
        for item in value:
            text = str(item).strip()
            if not text or text.lower() in PLACEHOLDER_TEXTS:
                continue
            normalized.append(text)
        return normalized
    if value is None:
        return []
    text = str(value).strip()
    if text.lower() in PLACEHOLDER_TEXTS:
        return []
    return [text] if text else []


def sanitize_text(value):
    text = str(value or "").strip()
    if not text or text.lower() in PLACEHOLDER_TEXTS:
        return ""
    return text


def infer_verdict(score, blockers):
    if blockers:
        return "with_adjustments" if score >= 65 else "no"
    if score >= 75:
        return "yes"
    if score >= 55:
        return "with_adjustments"
    return "no"


def score_100_to_5(score):
    normalized = 1.0 + (4.0 * (float(score) / 100.0))
    return round(clamp(normalized, 1.0, 5.0), 1)


def infer_application_recommendation(score_5):
    if score_5 >= 4.5:
        return "apply_now"
    if score_5 >= 4.0:
        return "worth_applying"
    if score_5 >= 3.5:
        return "only_if_strategic"
    return "do_not_apply"


def extract_json_payload(content):
    text = str(content or "").strip()
    if not text:
        return {}

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def normalize_scorecard(scorecard):
    normalized = {}

    for key, description in SCORING_DIMENSIONS.items():
        raw_dimension = scorecard.get(key) if isinstance(scorecard, dict) else None
        if isinstance(raw_dimension, dict):
            raw_score = raw_dimension.get("score", DEFAULT_DIMENSION_SCORE)
            reason = sanitize_text(raw_dimension.get("reason", "")) or description
        else:
            raw_score = raw_dimension if raw_dimension is not None else DEFAULT_DIMENSION_SCORE
            reason = description

        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            score = DEFAULT_DIMENSION_SCORE

        normalized[key] = {
            "score": round(clamp(score, 1.0, 5.0), 2),
            "reason": reason,
            "weight": SCORE_WEIGHTS[key],
        }

    return normalized


def compute_overall_score(scorecard, blockers):
    weighted = sum(scorecard[key]["score"] * SCORE_WEIGHTS[key] for key in SCORE_WEIGHTS)
    base_score = round(((weighted - 1.0) / 4.0) * 100.0)
    blocker_penalty = min(len(blockers) * 7, 21)
    return int(clamp(base_score - blocker_penalty, 0, 100))


def normalize_analysis_result(result):
    if not isinstance(result, dict):
        result = {"raw": result}

    scorecard = normalize_scorecard(result.get("scorecard") or {})
    blockers = normalize_text_list(result.get("blockers"))
    forces = normalize_text_list(result.get("forces"))
    weaknesses = normalize_text_list(result.get("faiblesses"))
    remarks = sanitize_text(result.get("remarques", ""))
    verdict = sanitize_text(result.get("verdict", ""))

    raw_legitimacy = result.get("posting_legitimacy") or {}
    if not isinstance(raw_legitimacy, dict):
        raw_legitimacy = {}
    legitimacy_assessment = str(raw_legitimacy.get("assessment", "")).strip() or "unknown"
    legitimacy_reasoning = normalize_text_list(raw_legitimacy.get("reasoning"))

    normalized_evidence = []
    evidence = result.get("evidence")
    if isinstance(evidence, list):
        for item in evidence[:8]:
            if not isinstance(item, dict):
                continue
            fit = str(item.get("fit", "partial")).strip().lower()
            if fit not in {"strong", "partial", "missing"}:
                fit = "partial"
            importance = str(item.get("importance", "important")).strip().lower()
            if importance not in {"must_have", "important", "nice_to_have"}:
                importance = "important"
            normalized_evidence.append(
                {
                    "requirement": sanitize_text(item.get("requirement", "")),
                    "profile_evidence": sanitize_text(item.get("profile_evidence", "")),
                    "fit": fit,
                    "source": sanitize_text(item.get("source", "")),
                    "importance": importance,
                }
            )

    normalized_requirement_match = []
    requirement_match = result.get("requirement_match")
    if isinstance(requirement_match, list):
        for item in requirement_match[:12]:
            if not isinstance(item, dict):
                continue
            strength = str(item.get("strength", "partial")).strip().lower()
            if strength not in {"strong", "good", "partial", "weak", "missing"}:
                strength = "partial"
            gap_type = str(item.get("gap_type", "unknown")).strip().lower()
            if gap_type not in {"none", "adjacent_only", "direct_gap", "unknown"}:
                gap_type = "unknown"
            normalized_requirement_match.append(
                {
                    "requirement": sanitize_text(item.get("requirement", "")),
                    "profile_evidence": sanitize_text(item.get("profile_evidence", "")),
                    "strength": strength,
                    "gap_type": gap_type,
                    "is_blocker": bool(item.get("is_blocker", False)),
                    "mitigation": sanitize_text(item.get("mitigation", "")),
                }
            )

    normalized_tool_match = []
    tool_match = result.get("tool_match")
    if isinstance(tool_match, list):
        for item in tool_match[:16]:
            if not isinstance(item, dict):
                continue
            strength = str(item.get("strength", "missing")).strip().lower()
            if strength not in {"direct", "adjacent", "missing", "not_relevant"}:
                strength = "missing"
            importance = str(item.get("importance", "important")).strip().lower()
            if importance not in {"must_have", "important", "nice_to_have"}:
                importance = "important"
            normalized_tool_match.append(
                {
                    "tool": sanitize_text(item.get("tool", "")),
                    "profile_evidence": sanitize_text(item.get("profile_evidence", "")),
                    "strength": strength,
                    "importance": importance,
                }
            )

    normalized_gaps = []
    gaps = result.get("gaps")
    if isinstance(gaps, list):
        for item in gaps[:8]:
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity", "medium")).strip().lower()
            if severity not in {"low", "medium", "high"}:
                severity = "medium"
            normalized_gaps.append(
                {
                    "gap": sanitize_text(item.get("gap", "")),
                    "severity": severity,
                    "blocker": bool(item.get("blocker", False)),
                    "mitigation": sanitize_text(item.get("mitigation", "")),
                }
            )

    role_summary = result.get("role_summary")
    if not isinstance(role_summary, dict):
        role_summary = {}

    overall_score = compute_overall_score(scorecard, blockers)
    overall_score_5 = score_100_to_5(overall_score)
    if not verdict:
        verdict = infer_verdict(overall_score, blockers)

    return {
        "score": overall_score,
        "score_5": overall_score_5,
        "application_recommendation": infer_application_recommendation(overall_score_5),
        "scorecard": scorecard,
        "archetype": result.get("archetype") if isinstance(result.get("archetype"), dict) else {},
        "role_summary": {
            "domain": sanitize_text(role_summary.get("domain", "")),
            "function": sanitize_text(role_summary.get("function", "")),
            "seniority": sanitize_text(role_summary.get("seniority", "")),
            "remote_policy": sanitize_text(role_summary.get("remote_policy", "")),
            "team_context": sanitize_text(role_summary.get("team_context", "")),
            "tldr": sanitize_text(role_summary.get("tldr", "")),
        },
        "evidence": normalized_evidence,
        "requirement_match": normalized_requirement_match,
        "tool_match": normalized_tool_match,
        "gaps": normalized_gaps,
        "standout_differentiator": sanitize_text(result.get("standout_differentiator", "")),
        "forces": forces,
        "faiblesses": weaknesses,
        "blockers": blockers,
        "verdict": verdict,
        "posting_legitimacy": {
            "assessment": legitimacy_assessment,
            "reasoning": legitimacy_reasoning,
        },
        "remarques": remarks,
        "pipeline": result.get("_pipeline_tag", "maverick"),
    }
