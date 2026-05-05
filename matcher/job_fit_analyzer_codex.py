#!/usr/bin/env python3
"""
Job Fit Analyzer - NVIDIA NIM API
Scores the fit between a job posting and your profile.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
import re
import time
import requests

try:
    from matching_intelligence_codex import build_match_context, build_profile_text, format_match_context
except ImportError:  # pragma: no cover
    from .matching_intelligence_codex import build_match_context, build_profile_text, format_match_context

# ============ CONFIGURATION ============
NVIDIA_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "meta/llama-4-maverick-17b-128e-instruct"
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PROFILE_DIR = os.environ.get("CAREER_OPS_DIR", "career-ops")
DEFAULT_DIMENSION_SCORE = 3.0
MAX_RETRIES = 3
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


# ============ CHARGEMENT DES FICHIERS PROFIL ============
def log_progress(message):
    """Writes a progress log to stderr without polluting JSON output."""
    print(message, file=sys.stderr, flush=True)


def load_profile_files(profile_dir=DEFAULT_PROFILE_DIR):
    """Loads the 4 profile files."""
    files = ["profile.yml", "portals.yml", "cv.md", "_profile.md"]
    profile_data = {}
    profile_root = Path(profile_dir)
    if not profile_root.is_absolute():
        profile_root = BASE_DIR / profile_root

    for filename in files:
        filepath = profile_root / filename
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                profile_data[filename] = f.read()
        else:
            print(f"⚠️  Missing file: {filename}")
            profile_data[filename] = f"File {filename} not found"

    return profile_data


def build_system_prompt(profile_data):
    """Builds the system prompt from profile data."""
    return f"""
You are a senior technical recruiting evaluator.

Here is my complete profile:

=== IDENTITY (profile.yml) ===
{profile_data.get('profile.yml', 'Not provided')}

=== TARGET KEYWORDS (portals.yml) ===
{profile_data.get('portals.yml', 'Not provided')}

=== EXPERIENCE (cv.md) ===
{profile_data.get('cv.md', 'Not provided')}

=== APPLICATION STRATEGY (_profile.md) ===
{profile_data.get('_profile.md', 'Not provided')}

Evaluate each job with a structured scorecard inspired by career-ops.
Reason explicitly about the role archetype, gaps, blockers, and match dimensions.
The final score will be recalculated by the program, so do NOT invent an arbitrary final score.
Reason like a senior evaluator, not like a summarizer.
Your priority is to map JD requirements to explicit profile evidence, then classify gaps as blocker vs nice-to-have.
All textual output fields must be in English only.

=== PRE-SCORING CHECKS (apply before assigning dimension scores) ===

Check A — Employment model:
- Determine whether the hiring company operates as a consulting firm, professional services firm, or staffing/contracting model where the candidate would be embedded at external client sites.
- If yes → cap `target_alignment` score at 2.0. Add to `blockers`: "Job type: consulting/professional services — not a target employment model."

Check B — Domain match:
- Identify the primary industry domain this role requires experience in (e.g. "financial services", "healthcare", "logistics", "legal tech", …). Do not assume — read the JD.
- Then check whether the candidate's CV shows direct experience in that same domain.
- If the JD treats domain experience as a must-have (explicit requirement, specialist firm, or domain-specific regulation/tooling that cannot transfer) AND the candidate has no direct experience in that domain → cap `relevant_experience` score at 2.0. Add to `blockers`: "Domain mismatch: role requires [detected domain] experience — candidate has none."
- If domain experience is preferred but not required, or the candidate's experience is genuinely transferable, do not cap — reflect the gap in the score naturally (e.g. 2.5–3.5) with a reason.
- Adjacent experience belongs ONLY in `mitigation`. It does not raise a capped score.

Check B2 — Hard requirement with no CV evidence:
- Scan the JD for any requirement phrased with hard-requirement language ("required", "must have", "mandatory", "you must have", "X+ years of [specific thing]") where the candidate's CV contains ZERO direct evidence — not adjacent, not transferable.
- This applies to any type of hard requirement: domain/industry experience, specific platform ownership, process expertise, certifications, etc.
- For each such unmet hard requirement with no mitigation path:
  - In `requirement_match`, record `is_blocker: true`, `gap_type: "direct_gap"`, `strength: "missing"`, `mitigation: ""`.
  - Cap `relevant_experience` at 2.5.
  - Add to `blockers`: "Hard requirement unmet: [requirement text] — no direct evidence in profile."
- Exception — do NOT cap if ALL of the following are true: (a) the JD uses softening language ("or equivalent", "preferred"), (b) the candidate has a concrete transferable substitute, AND (c) you can write a specific mitigation. In that case, set `mitigation` with the concrete path and score 3.0–3.5.
- A mitigation field must describe a real bridge, not a generic "fast learner" claim.

Check C — Explicit must-have requirements with no CV evidence:
- Scan the JD for requirements phrased as hard requirements: "X+ years of [specific skill/function]", "required", "must have", "experience with [specific platform/domain]".
- For each such requirement, check whether the CV contains direct evidence — not adjacent, not transferable, but actual matching experience.
- Count how many hard requirements have ZERO direct CV evidence.
- If 2 or more hard requirements have no direct evidence → reduce `requirements_coverage` score by 1.0 per unmet requirement, floor at 1.0. List each unmet requirement in `gaps` with `blocker: true` and `severity: high`.
- If 1 hard requirement has no direct evidence → reduce `requirements_coverage` by 0.75 and add to `gaps` with `severity: medium`.
- Do NOT use "transferable skills" or "adjacent experience" to satisfy a hard requirement. The standard is: did the candidate actually do this specific thing?
- Example: "3+ years managing eCommerce websites" — a B2B SaaS background does NOT satisfy this. Mark as unmet.

Check D — Geographic eligibility:
- Use the structured match context supplied with the JD. It was extracted generically from the candidate profile and JD.
- If `matches.location.status` is `incompatible` → cap `workplace_fit` at 1.5 and add a blocker with the structured reason.
- If `matches.location.status` is `compatible` → do not invent geographic blockers.
- Do not infer job location from compensation notes. Compensation geography is not the same as work eligibility.
- Excluded regions only block the candidate if they overlap the candidate's extracted region(s).

=== END PRE-SCORING CHECKS ===

{{
  "archetype": {{
    "primary": "AI Platform / LLMOps",
    "secondary": "Agentic / Automation"
  }},
  "role_summary": {{
    "domain": "platform / onboarding / payroll / compliance",
    "function": "build / manage / discovery / delivery",
    "seniority": "Senior PM II",
    "remote_policy": "Remote US/Canada",
    "team_context": "tenured eng team + designer",
    "tldr": "resume en une phrase de ce que l'entreprise achete vraiment"
  }},
  "scorecard": {{
    "core_skills": {{
      "score": 4.2,
      "reason": "Explication courte et factuelle"
    }},
    "relevant_experience": {{
      "score": 4.0,
      "reason": "Explication courte et factuelle"
    }},
    "target_alignment": {{
      "score": 4.5,
      "reason": "Explication courte et factuelle"
    }},
    "seniority_fit": {{
      "score": 3.5,
      "reason": "Explication courte et factuelle"
    }},
    "workplace_fit": {{
      "score": 4.0,
      "reason": "Explication courte et factuelle"
    }},
    "requirements_coverage": {{
      "score": 3.8,
      "reason": "Explication courte et factuelle"
    }}
  }},
  "evidence": [
    {{
      "requirement": "Exigence JD",
      "profile_evidence": "Explicit evidence from the profile",
      "fit": "strong",
      "source": "cv.md",
      "importance": "must_have"
    }}
  ],
  "requirement_match": [
    {{
      "requirement": "5+ years PM in SaaS or fintech",
      "profile_evidence": "10+ years PM in SaaS, ex full-stack dev, complex integrations",
      "strength": "strong",
      "gap_type": "none",
      "is_blocker": false,
      "mitigation": ""
    }},
    {{
      "requirement": "payroll domain experience",
      "profile_evidence": "",
      "strength": "weak",
      "gap_type": "adjacent_only",
      "is_blocker": false,
      "mitigation": "regulatory/compliance adjacency and fast ramp plan"
    }}
  ],
  "tool_match": [
    {{
      "tool": "Snowflake",
      "profile_evidence": "Explicit evidence from profile or empty string",
      "strength": "missing",
      "importance": "important"
    }}
  ],
  "gaps": [
    {{
      "gap": "No direct payroll background",
      "severity": "medium",
      "blocker": false,
      "mitigation": "Adjacent regulated-environment experience"
    }}
  ],
  "standout_differentiator": "The strongest differentiator versus market peers",
  "forces": ["force1", "force2", "force3"],
  "faiblesses": ["faiblesse1", "faiblesse2", "faiblesse3"],
  "blockers": ["blocker1"],
  "verdict": "yes / no / with_adjustments",
  "posting_legitimacy": {{
    "assessment": "high_confidence",
    "reasoning": ["signal1", "signal2"]
  }},
  "remarques": "optional comment"
}}

Rules:
- Return valid JSON only.
- Every scorecard.*.score must be a number from 1.0 to 5.0.
- If information is missing, use 3.0 and explain uncertainty in `reason`.
- `posting_legitimacy` is separate from fit and must not directly lower fit scores.
- `fit` in `evidence` must be one of: strong, partial, missing.
- `strength` in `requirement_match` must be one of: strong, good, partial, weak, missing.
- `gap_type` in `requirement_match` must be one of: none, adjacent_only, direct_gap, unknown.
- `importance` in `evidence` must be one of: must_have, important, nice_to_have.
- `tool_match[].strength` must be one of: direct, adjacent, missing, not_relevant.
- Be strict on must-haves, but distinguish hard blockers from nice-to-haves.
- Use `job_facts.requirement_groups.must_have` as the primary must-have checklist when present.
- Use `job_facts.requirement_groups.nice_to_have` as nice-to-have only; do not create blockers for those items.
- Use `matches.technical_tools` as the initial tool checklist, but you may upgrade a missing tool to adjacent if the profile has credible adjacent evidence.
- Produce at least 6 lines in `requirement_match` if the JD contains enough information.
- Do not fall back to generic bullets. Use the distinctive signals of the role: domain, stack, regulation, AI, seniority, platform type.
"""


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


def recommendation_label(code):
    labels = {
        "apply_now": "Apply now",
        "worth_applying": "Worth applying",
        "only_if_strategic": "Only if strategic",
        "do_not_apply": "Do not apply",
    }
    return labels.get(str(code), str(code))


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
            return json.loads(text[start:end + 1])
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
            normalized_evidence.append({
                "requirement": sanitize_text(item.get("requirement", "")),
                "profile_evidence": sanitize_text(item.get("profile_evidence", "")),
                "fit": fit,
                "source": sanitize_text(item.get("source", "")),
                "importance": importance,
            })

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
            normalized_requirement_match.append({
                "requirement": sanitize_text(item.get("requirement", "")),
                "profile_evidence": sanitize_text(item.get("profile_evidence", "")),
                "strength": strength,
                "gap_type": gap_type,
                "is_blocker": bool(item.get("is_blocker", False)),
                "mitigation": sanitize_text(item.get("mitigation", "")),
            })

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
            normalized_tool_match.append({
                "tool": sanitize_text(item.get("tool", "")),
                "profile_evidence": sanitize_text(item.get("profile_evidence", "")),
                "strength": strength,
                "importance": importance,
            })

    normalized_gaps = []
    gaps = result.get("gaps")
    if isinstance(gaps, list):
        for item in gaps[:8]:
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity", "medium")).strip().lower()
            if severity not in {"low", "medium", "high"}:
                severity = "medium"
            normalized_gaps.append({
                "gap": sanitize_text(item.get("gap", "")),
                "severity": severity,
                "blocker": bool(item.get("blocker", False)),
                "mitigation": sanitize_text(item.get("mitigation", "")),
            })

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
        "pipeline": "codex",
    }


def remove_location_false_positives(analysis):
    location_terms = ("geographic mismatch", "location mismatch", "state exclusion", "country mismatch")
    for key in ("blockers", "faiblesses"):
        analysis[key] = [
            item for item in analysis.get(key, [])
            if not any(term in str(item).lower() for term in location_terms)
        ]
    analysis["gaps"] = [
        item for item in analysis.get("gaps", [])
        if not any(term in str(item.get("gap", "")).lower() for term in location_terms)
    ]


def add_gap_once(analysis, gap):
    existing = {str(item.get("gap", "")).strip().lower() for item in analysis.get("gaps", []) if isinstance(item, dict)}
    if str(gap.get("gap", "")).strip().lower() not in existing:
        analysis.setdefault("gaps", []).append(gap)


def _enforce_hard_blocker_guardrail(analysis):
    """Cap relevant_experience when the LLM flagged a requirement as a hard blocker with no mitigation.

    Fires on structure alone — no domain keyword list. Any requirement marked
    is_blocker=true + gap_type=direct_gap + strength=missing + no mitigation path
    is treated as a disqualifying gap regardless of what domain or skill it names.
    """
    requirement_match = analysis.get("requirement_match") or []
    scorecard = analysis.get("scorecard") or {}
    rel_exp = scorecard.get("relevant_experience")
    if not isinstance(rel_exp, dict):
        return

    for item in requirement_match:
        if not isinstance(item, dict):
            continue
        if not item.get("is_blocker"):
            continue
        if item.get("gap_type") != "direct_gap":
            continue
        if item.get("strength") != "missing":
            continue
        if item.get("mitigation", "").strip():
            continue
        current_score = float(rel_exp.get("score", 5.0) or 5.0)
        if current_score > 2.5:
            rel_exp["score"] = 2.5
            rel_exp["reason"] = (
                rel_exp.get("reason", "")
                + " [Guardrail] Hard requirement with no CV evidence and no mitigation path — capped at 2.5."
            ).strip()
        blocker_text = f"Hard requirement unmet: {item.get('requirement', 'required experience')} — no direct evidence in profile."
        if not any(blocker_text.lower()[:40] in str(b).lower() for b in analysis.get("blockers", [])):
            analysis.setdefault("blockers", []).append(blocker_text)
        add_gap_once(analysis, {
            "gap": blocker_text,
            "severity": "high",
            "blocker": True,
            "mitigation": "",
        })


def apply_match_guardrails(analysis, match_context):
    location = ((match_context or {}).get("matches") or {}).get("location") or {}
    status = location.get("status")
    reason = sanitize_text(location.get("reason"))
    scorecard = analysis.get("scorecard") or {}
    workplace = scorecard.get("workplace_fit")

    if status == "compatible":
        remove_location_false_positives(analysis)
        if isinstance(workplace, dict) and float(workplace.get("score", 3.0) or 3.0) < 4.0:
            workplace["score"] = 4.0
            workplace["reason"] = reason or "Structured location check found the role compatible."
    elif status == "incompatible":
        blocker = f"Geographic mismatch: {reason}" if reason else "Geographic mismatch"
        if blocker not in analysis.get("blockers", []):
            analysis.setdefault("blockers", []).append(blocker)
        add_gap_once(analysis, {"gap": blocker, "severity": "high", "blocker": True, "mitigation": ""})
        if isinstance(workplace, dict):
            workplace["score"] = min(float(workplace.get("score", 3.0) or 3.0), 1.5)
            workplace["reason"] = reason or "Structured location check found the role incompatible."

    _enforce_hard_blocker_guardrail(analysis)

    if not analysis.get("tool_match"):
        analysis["tool_match"] = [
            {
                "tool": item.get("tool", ""),
                "profile_evidence": item.get("profile_evidence", ""),
                "strength": "direct" if item.get("status") == "direct" else "missing",
                "importance": "important",
            }
            for item in (((match_context or {}).get("matches") or {}).get("technical_tools") or [])[:16]
        ]

    analysis["match_context"] = match_context
    analysis["score"] = compute_overall_score(scorecard, analysis.get("blockers", []))
    analysis["score_5"] = score_100_to_5(analysis["score"])
    analysis["application_recommendation"] = infer_application_recommendation(analysis["score_5"])
    analysis["verdict"] = infer_verdict(analysis["score"], analysis.get("blockers", []))
    if status == "incompatible":
        analysis["verdict"] = "no"
        analysis["application_recommendation"] = "do_not_apply"
    return analysis


def calculate_fit(jd_text, system_prompt, api_key, model, job_label=None, profile_text=""):
    """Calls the NVIDIA NIM API to compute job fit."""
    match_context = build_match_context(jd_text, profile_text)
    user_content = (
        "Here is the structured candidate/JD match context. Treat deterministic location compatibility, "
        "must-have vs nice-to-have grouping, and explicit tool mentions as the source of truth unless the JD text clearly contradicts it:\n\n"
        f"{format_match_context(match_context)}\n\n"
        f"Here is the job posting to analyze:\n\n{jd_text}"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt, "cache_control": {"type": "ephemeral"}},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.2,
        "max_tokens": 2600,
        "response_format": {"type": "json_object"}
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if job_label:
                log_progress(f"[match] {job_label} | calling NVIDIA NIM | attempt {attempt}/{MAX_RETRIES}")
            response = requests.post(f"{NVIDIA_URL}/chat/completions", headers=headers, json=payload, timeout=60)
            response.raise_for_status()

            result = response.json()
            content = result["choices"][0]["message"]["content"]
            parsed = extract_json_payload(content)
            normalized = apply_match_guardrails(normalize_analysis_result(parsed), match_context)
            if job_label:
                usage = result.get("usage") or {}
                cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
                cache_note = f" cached_tokens={cached_tokens}" if cached_tokens else ""
                log_progress(
                    f"[match] {job_label} | response received | score={normalized.get('score', 0)} "
                    f"verdict={normalized.get('verdict', 'n/a')} blockers={len(normalized.get('blockers', []))}"
                    f"{cache_note}"
                )
            return normalized

        except json.JSONDecodeError:
            last_error = "non_json_response"
            log_progress(f"[match] {job_label or 'job'} | non-JSON response | attempt {attempt}/{MAX_RETRIES}")
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            log_progress(f"[match] {job_label or 'job'} | API error | attempt {attempt}/{MAX_RETRIES} | {e}")

        if attempt < MAX_RETRIES:
            if job_label:
                log_progress(f"[match] {job_label} | retrying in {attempt}s")
            time.sleep(attempt)

    if job_label:
        log_progress(f"[match] {job_label} | failed after {MAX_RETRIES} attempts")
    return {
        "score": 0,
        "scorecard": normalize_scorecard({}),
        "forces": [],
        "faiblesses": [],
        "blockers": ["model_call_failed"],
        "verdict": "no",
        "posting_legitimacy": {"assessment": "unknown", "reasoning": []},
        "remarques": "",
        "erreur": last_error or "unknown_error",
    }


# ============ FONCTIONS UTILITAIRES ============
def read_jd_from_file(filepath):
    """Reads a job posting from a file."""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def read_jd_from_stdin():
    """Reads a job posting from stdin (pipe or paste)."""
    print("📝 Paste your job posting below (Ctrl+D or Ctrl+Z to finish):")
    return sys.stdin.read()


def save_result(jd_text, result, output_file=None):
    """Saves the result to a file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    rapport = {
        "date": timestamp,
        "jd": jd_text[:500] + "..." if len(jd_text) > 500 else jd_text,
        "analyse": result
    }

    filename = output_file if output_file else f"job_fit_report_{timestamp}.json"

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(rapport, f, indent=2, ensure_ascii=False)

    print(f"\n📄 Report saved: {filename}")
    return filename


def display_result(result):
    """Pretty-prints the result."""
    print("\n" + "=" * 50)
    print("📊 ANALYSIS RESULT")
    print("=" * 50)

    score_5 = float(result.get("score_5", 0) or 0)
    bar_length = 30
    filled = int(bar_length * score_5 / 5)
    bar = "█" * filled + "░" * (bar_length - filled)

    print(f"\n⭐ FIT SCORE : {score_5}/5")
    print(f"   [{bar}]")

    if score_5 >= 4.5:
        print("   ✅ Strong match")
    elif score_5 >= 4.0:
        print("   👍 Worth applying")
    elif score_5 >= 3.5:
        print("   ⚠️  Only if strategic")
    else:
        print("   ❌ Weak fit")

    print("\n💪 STRENGTHS:")
    for force in result.get("forces", []):
        print(f"   • {force}")

    print("\n🔧 WEAKNESSES / GAPS:")
    for faiblesse in result.get("faiblesses", []):
        print(f"   • {faiblesse}")

    print(f"\n🎯 VERDICT: {result.get('verdict', 'unspecified')}")
    recommendation = result.get("application_recommendation")
    if recommendation:
        print(f"📌 RECOMMENDATION: {recommendation_label(recommendation)}")

    scorecard = result.get("scorecard") or {}
    if scorecard:
        print("\n🧮 SCORECARD:")
        for key, details in scorecard.items():
            label = key.replace("_", " ")
            print(f"   • {label}: {details.get('score', DEFAULT_DIMENSION_SCORE)}/5")
            reason = str(details.get("reason", "")).strip()
            if reason:
                print(f"     {reason}")

    blockers = result.get("blockers") or []
    if blockers:
        print("\n⛔ BLOCKERS:")
        for blocker in blockers:
            print(f"   • {blocker}")

    legitimacy = result.get("posting_legitimacy") or {}
    legitimacy_assessment = legitimacy.get("assessment")
    if legitimacy_assessment:
        print(f"\n🕵️ POSTING LEGITIMACY: {legitimacy_assessment}")
        for reason in legitimacy.get("reasoning", []):
            print(f"   • {reason}")

    if result.get("remarques"):
        print(f"\n💬 NOTES: {result['remarques']}")

    if result.get("erreur"):
        print(f"\n⚠️  ERROR: {result['erreur']}")


def bullet_lines(items):
    return "\n".join(f"- {item}" for item in items if str(item).strip())


def format_job_label(record, line_number=None):
    company = str(record.get("company") or record.get("source_key") or "unknown-company").strip()
    title = str(record.get("title") or record.get("job_id") or "unknown-title").strip()
    prefix = f"#{line_number} " if line_number is not None else ""
    return f"{prefix}{company} | {title}"


def synthesize_jd_text(record):
    """Builds a usable JD text from a structured payload."""
    responsibilities = record.get("responsibilities") or []
    requirements = record.get("requirements_summary") or []
    must_have = record.get("must_have_requirements") or requirements
    nice_to_have = record.get("nice_to_have_requirements") or []
    technical_tools = record.get("technical_tools_mentioned") or []
    concepts = record.get("jd_concepts") or []

    sections = []

    def add(label, value):
        if value in (None, "", []):
            return
        sections.append(f"{label}: {value}")

    add("Title", record.get("title"))
    add("Company", record.get("company"))
    add("Provider", record.get("provider"))
    add("Location", record.get("location"))
    add("Employment type", record.get("employment_type"))
    add("Workplace type", record.get("workplace_type"))
    add("Compensation", record.get("compensation"))
    add("Posted datetime", record.get("posted_datetime"))
    add("JD concepts", ", ".join(str(item) for item in concepts if str(item).strip()))
    add("Technical tools mentioned", ", ".join(str(item) for item in technical_tools if str(item).strip()))

    if responsibilities:
        sections.append("Responsibilities:\n" + bullet_lines(responsibilities))
    if must_have:
        sections.append("Requirements:\n" + bullet_lines(must_have))
    if nice_to_have:
        sections.append("Nice-to-have:\n" + bullet_lines(nice_to_have))

    body = record.get("jd_text")
    if body and str(body).strip():
        sections.append(f"Job description:\n{body}")

    return "\n\n".join(section for section in sections if section.strip())


def process_batch(input_file, output_file, system_prompt, api_key, model, dry_run=False, profile_text="", pipeline_tag="codex"):
    """Processes a JSONL file of structured job postings and writes a JSONL of results."""
    total = 0
    succeeded = 0
    failed = 0

    log_progress(f"[batch] start | input={input_file} output={output_file} dry_run={str(dry_run).lower()} model={model}")

    with open(input_file, "r", encoding="utf-8") as src, open(output_file, "w", encoding="utf-8") as dst:
        for line_number, raw_line in enumerate(src, start=1):
            line = raw_line.strip()
            if not line:
                continue

            total += 1

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                failed += 1
                log_progress(f"[batch] line {line_number} | invalid json | {exc}")
                dst.write(json.dumps({
                    "line_number": line_number,
                    "status": "error",
                    "error": f"Invalid JSON: {exc}"
                }, ensure_ascii=False) + "\n")
                continue

            job_label = format_job_label(record, line_number=line_number)
            jd_text = synthesize_jd_text(record)
            log_progress(f"[batch] {job_label} | start processing | jd_chars={len(jd_text)}")
            if not jd_text.strip():
                analysis = {"score": 0, "error": "empty_job_description"}
                log_progress(f"[batch] {job_label} | empty job description")
            elif dry_run:
                match_context = build_match_context(jd_text, profile_text)
                analysis = apply_match_guardrails(normalize_analysis_result({
                    "archetype": {"primary": "Simulation", "secondary": ""},
                    "scorecard": {key: {"score": 3.75, "reason": "Mode dry-run"} for key in SCORING_DIMENSIONS},
                    "forces": ["Simulation"],
                    "faiblesses": ["Mode dry-run"],
                    "blockers": [],
                    "verdict": "simulation",
                    "posting_legitimacy": {"assessment": "unknown", "reasoning": ["Mode dry-run"]},
                }), match_context)
                log_progress(f"[batch] {job_label} | dry-run | score={analysis.get('score', 0)}")
            else:
                analysis = calculate_fit(jd_text, system_prompt, api_key, model, job_label=job_label, profile_text=profile_text)

            analysis["pipeline"] = pipeline_tag
            status = "ok" if not analysis.get("erreur") else "error"
            if status == "ok":
                succeeded += 1
            else:
                failed += 1
            log_progress(
                f"[batch] {job_label} | fin traitement | status={status} "
                f"score={analysis.get('score', 0)} verdict={analysis.get('verdict', 'n/a')}"
            )

            output_row = {
                "line_number": line_number,
                "status": status,
                "provider": record.get("provider"),
                "source_key": record.get("source_key"),
                "job_id": record.get("job_id"),
                "title": record.get("title"),
                "company": record.get("company"),
                "location": record.get("location"),
                "job_url": record.get("job_url") or record.get("url"),
                "parsed_job": {
                    "jd_concepts": record.get("jd_concepts"),
                    "posted_datetime": record.get("posted_datetime"),
                    "compensation": record.get("compensation"),
                    "workplace_type": record.get("workplace_type"),
                    "employment_type": record.get("employment_type"),
                    "responsibilities": record.get("responsibilities"),
                    "requirements_summary": record.get("requirements_summary"),
                    "must_have_requirements": record.get("must_have_requirements"),
                    "nice_to_have_requirements": record.get("nice_to_have_requirements"),
                    "technical_tools_mentioned": record.get("technical_tools_mentioned"),
                },
                "analysis": analysis
            }
            dst.write(json.dumps(output_row, ensure_ascii=False) + "\n")

    log_progress(f"[batch] fin | total={total} ok={succeeded} failed={failed}")
    return {"total": total, "succeeded": succeeded, "failed": failed}


# ============ MAIN ============
def main():
    parser = argparse.ArgumentParser(description="Job fit analysis via NVIDIA NIM")
    parser.add_argument("-j", "--jd", help="File containing the job posting")
    parser.add_argument("-o", "--output", help="Fichier de sortie pour le rapport")
    parser.add_argument("--jobs-jsonl", help="JSONL file of structured job postings to analyze in batch")
    parser.add_argument("--results-jsonl", help="JSONL output file for batch results")
    parser.add_argument("-p", "--profile-dir", default=DEFAULT_PROFILE_DIR, help=f"Directory containing profile files (default: {DEFAULT_PROFILE_DIR})")
    parser.add_argument("--model", default=os.environ.get("NVIDIA_MODEL", DEFAULT_MODEL), help=f"Modele NVIDIA NIM (defaut: {DEFAULT_MODEL})")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without API call")
    parser.add_argument("--pipeline", default="codex", help="Pipeline tag written to analysis.pipeline (default: codex)")

    args = parser.parse_args()

    if args.jobs_jsonl and args.jd:
        print("❌ Utilise soit --jd soit --jobs-jsonl, pas les deux")
        sys.exit(1)

    if args.jobs_jsonl and not args.results_jsonl:
        print("❌ --results-jsonl is required with --jobs-jsonl")
        sys.exit(1)

    api_key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not api_key and not args.dry_run:
        print("❌ Error: set your NVIDIA API key")
        print("   export NVIDIA_API_KEY='your_key'")
        sys.exit(1)

    print("📁 Loading profile files...")
    profile_data = load_profile_files(args.profile_dir)
    system_prompt = build_system_prompt(profile_data)
    profile_text = build_profile_text(profile_data)

    if args.jobs_jsonl:
        print(f"📚 Batch analysis: {args.jobs_jsonl}")
        print(f"🧠 NVIDIA model: {args.model}")
        summary = process_batch(args.jobs_jsonl, args.results_jsonl, system_prompt, api_key, args.model, dry_run=args.dry_run, profile_text=profile_text, pipeline_tag=args.pipeline)
        print(json.dumps(summary, ensure_ascii=False))
        return

    if args.jd:
        print(f"📄 Reading job posting: {args.jd}")
        jd_text = read_jd_from_file(args.jd)
    else:
        jd_text = read_jd_from_stdin()

    if not jd_text.strip():
        print("❌ Empty job posting")
        sys.exit(1)

    print(f"📏 Job posting: {len(jd_text)} characters")
    print(f"🧠 NVIDIA model: {args.model}")

    if args.dry_run:
        print("\n🔍 DRY RUN mode - no API call")
        print(f"System prompt (excerpt): {system_prompt[:200]}...")
        result = normalize_analysis_result({
            "archetype": {"primary": "Simulation", "secondary": ""},
            "scorecard": {key: {"score": 3.75, "reason": "Dry-run mode"} for key in SCORING_DIMENSIONS},
            "forces": ["Simulation"],
            "faiblesses": ["Dry-run mode"],
            "blockers": [],
            "verdict": "simulation",
            "posting_legitimacy": {"assessment": "unknown", "reasoning": ["Dry-run mode"]},
        })
    else:
        print("\n🤖 Calling NVIDIA NIM API...")
        result = calculate_fit(jd_text, system_prompt, api_key, args.model, profile_text=profile_text)

    display_result(result)
    save_result(jd_text, result, args.output)


if __name__ == "__main__":
    main()
