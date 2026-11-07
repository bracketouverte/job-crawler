"""Ensemble (multi-model) fit scorer.

Ported from matcher/ensemble_runner.py per the matcher rewrite plan's "Do NOT
change ... the scoring logic" instruction — prompts, ensemble score weights
(0.25/0.25/0.20/0.10/0.10/0.10, different from the quick scorer's), and the
guardrail set (notably: ensemble does NOT run the quick scorer's
_enforce_hard_blocker_guardrail — that's a quick-pipeline-only guardrail,
preserved as an intentional difference) are all unchanged. Only the
concurrency model changes: asyncio.gather over the 3 scorers instead of a
ThreadPoolExecutor, and llm_client.chat_completions instead of requests.post.
"""

import asyncio
import json
import re
from pathlib import Path

from config import settings
from lib import llm_client
from lib.json_utils import infer_application_recommendation, score_100_to_5
from lib.matching_intelligence import (
    build_match_context_from_profile_data,
    build_profile_text,
    format_match_context,
)
from services.quick_scorer import synthesize_jd_text

DEFAULT_SYNTHESIZER = "nvidia/llama-3.3-nemotron-super-49b-v1.5"

ENSEMBLE_SCORE_WEIGHTS = {
    "core_skills": 0.25,
    "relevant_experience": 0.25,
    "target_alignment": 0.20,
    "seniority_fit": 0.10,
    "workplace_fit": 0.10,
    "requirements_coverage": 0.10,
}

_PRE_SCORING_CHECKS = """
=== PRE-SCORING CHECKS (apply before assigning dimension scores) ===

Check A — Employment model:
- If the hiring company is a consulting, professional services, or staffing/contracting firm where the candidate would be embedded at external client sites → cap target_alignment at 2.0. Add to blockers: "Job type: consulting/professional services — not a target employment model."

Check B — Domain match:
- Identify the primary industry domain the role requires (e.g. healthcare, fintech, logistics). Check whether the CV shows direct experience in that domain.
- If domain experience is a must-have AND the candidate has none → cap relevant_experience at 2.0. Add to blockers: "Domain mismatch: role requires [domain] experience — candidate has none."
- Transferable/adjacent experience belongs only in mitigation, never raises a capped score.

Check C — Explicit must-have requirements with no CV evidence:
- Identify requirements phrased as hard requirements: "X+ years of [specific skill/function]", "required", "must have", "experience with [specific platform/domain]".
- For each, verify direct CV evidence — not adjacent, not transferable, but actual matching experience.
- 2+ unmet hard requirements → reduce requirements_coverage by 1.0 per gap (floor 1.0). Add each to blockers.
- 1 unmet hard requirement → reduce requirements_coverage by 0.75. Add to gaps with severity: high.
- Do NOT use transferable skills to satisfy a hard requirement. Example: "3+ years managing eCommerce websites" is NOT satisfied by B2B SaaS experience.

Check D — Geographic eligibility:
- Use the structured match context supplied with the JD. It was extracted generically from the candidate profile and JD.
- If matches.location.status is incompatible → cap workplace_fit at 1.5 and add a blocker with the structured reason.
- If matches.location.status is compatible → do not invent geographic blockers.
- Do not infer job location from compensation notes. Compensation geography is not the same as work eligibility.
- Excluded regions only block the candidate if they overlap the candidate's extracted region(s).

=== END PRE-SCORING CHECKS ===
"""

SCORER_SYSTEM = (
    """You are a senior technical recruiting evaluator. Evaluate the job posting against the candidate profile.
"""
    + _PRE_SCORING_CHECKS
    + """
Return ONLY valid JSON, no markdown, no explanation:
{
  "archetype": {"primary": "...", "secondary": "..."},
  "role_summary": {"domain": "...", "seniority": "...", "remote_policy": "...", "tldr": "..."},
  "scorecard": {
    "core_skills": {"score": 4.0, "reason": "..."},
    "relevant_experience": {"score": 4.0, "reason": "..."},
    "target_alignment": {"score": 4.0, "reason": "..."},
    "seniority_fit": {"score": 4.0, "reason": "..."},
    "workplace_fit": {"score": 4.0, "reason": "..."},
    "requirements_coverage": {"score": 4.0, "reason": "..."}
  },
  "forces": ["...", "...", "..."],
  "faiblesses": ["...", "..."],
  "tool_match": [{"tool": "...", "profile_evidence": "...", "strength": "direct", "importance": "important"}],
  "blockers": [],
  "verdict": "yes",
  "remarques": "..."
}
Scores 1.0-5.0."""
)

SYNTHESIS_SYSTEM = (
    """You are a senior technical recruiting evaluator synthesizing multiple independent analyses of the same candidate + job.
"""
    + _PRE_SCORING_CHECKS
    + """
Synthesis rules:
- If models agree on a score (within 0.5), use that score.
- If models diverge, reason through which is most accurate; explain in the reason field.
- A model that ignored a pre-scoring check (e.g. scored high despite an unmet must-have) is wrong — override it.
- Merge forces/faiblesses/blockers: keep unique insights, remove duplicates.
- Write remarques integrating the best insight from each model.

Return ONLY valid JSON, no markdown, no explanation:
{
  "archetype": {"primary": "...", "secondary": "..."},
  "role_summary": {"domain": "...", "seniority": "...", "remote_policy": "...", "tldr": "..."},
  "scorecard": {
    "core_skills": {"score": 4.0, "reason": "..."},
    "relevant_experience": {"score": 4.0, "reason": "..."},
    "target_alignment": {"score": 4.0, "reason": "..."},
    "seniority_fit": {"score": 4.0, "reason": "..."},
    "workplace_fit": {"score": 4.0, "reason": "..."},
    "requirements_coverage": {"score": 4.0, "reason": "..."}
  },
  "forces": ["...", "...", "..."],
  "faiblesses": ["...", "..."],
  "tool_match": [{"tool": "...", "profile_evidence": "...", "strength": "direct", "importance": "important"}],
  "blockers": [],
  "verdict": "yes",
  "remarques": "..."
}
Scores 1.0-5.0."""
)


def strip_json(content: str) -> dict:
    content = re.sub(r"^```(?:json)?\s*", "", content.strip())
    content = re.sub(r"\s*```$", "", content.strip())
    try:
        return json.loads(content)
    except Exception:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise


def score_to_100(scorecard: dict) -> int:
    weighted = sum(scorecard.get(k, {}).get("score", 3.0) * w for k, w in ENSEMBLE_SCORE_WEIGHTS.items())
    return int(round(((weighted - 1.0) / 4.0) * 100.0))


def _remove_location_false_positives(analysis: dict) -> None:
    terms = ("geographic mismatch", "location mismatch", "state exclusion", "country mismatch")
    for key in ("blockers", "faiblesses"):
        analysis[key] = [
            item for item in analysis.get(key, []) if not any(term in str(item).lower() for term in terms)
        ]
    analysis["gaps"] = [
        item
        for item in analysis.get("gaps", [])
        if not any(term in str(item.get("gap", "")).lower() for term in terms)
    ]


_CONSULTING_SIGNALS = (
    "billable hours",
    "client delivery",
    "client engagement",
    "placed at client",
    "work at client",
    "on-site at client",
    "client-facing delivery",
    "consulting firm",
    "professional services firm",
    "staffing firm",
    "accenture",
    "mckinsey",
    "deloitte",
    "bcg",
    "bain",
    "kpmg",
    "pwc",
    "ernst & young",
    "big 4",
    "boutique consulting",
)

_TOOL_BLOCKER_PATTERNS = re.compile(
    r"\b(unmet hard requirement|hard requirement unmet|missing.*tool|tooling gap|no.*experience with|lacks.*experience with)\b",
    re.IGNORECASE,
)
_SOFTENED_TOOL_PATTERN = re.compile(
    r"(?:tools?\s+(?:like|such as|including)|familiarity with|experience with tools like)\s+(\w[\w\s\-\.]+)",
    re.IGNORECASE,
)


def _remove_softened_tool_blockers(analysis: dict, jd_text: str) -> None:
    jd_lower = (jd_text or "").lower()
    softened_tools = set()
    for m in _SOFTENED_TOOL_PATTERN.finditer(jd_lower):
        softened_tools.update(w.strip() for w in m.group(1).split(",") if len(w.strip()) > 2)
    if not softened_tools:
        return
    kept_blockers = []
    demoted = []
    for b in analysis.get("blockers", []):
        b_lower = str(b).lower()
        if _TOOL_BLOCKER_PATTERNS.search(b_lower) and any(tool in b_lower for tool in softened_tools):
            demoted.append(b)
        else:
            kept_blockers.append(b)
    if not demoted:
        return
    analysis["blockers"] = kept_blockers
    gaps = analysis.setdefault("gaps", [])
    existing = {str(g.get("gap", "")).strip().lower() for g in gaps if isinstance(g, dict)}
    for b in demoted:
        gap_text = (
            str(b)
            .replace("Unmet hard requirement: ", "Tool ramp-up: ")
            .replace("Hard requirement unmet: ", "Tool ramp-up: ")
        )
        if gap_text.lower() not in existing:
            gaps.append(
                {
                    "gap": gap_text,
                    "severity": "low",
                    "blocker": False,
                    "mitigation": "JD uses softening language ('tools like X') — direct tool experience not strictly required.",
                }
            )


def _remove_consulting_false_positive(analysis: dict, jd_text: str) -> None:
    consulting_blocker_prefix = "job type: consulting"
    blockers = analysis.get("blockers", [])
    has_blocker = any(consulting_blocker_prefix in str(b).lower() for b in blockers)
    if not has_blocker:
        return
    jd_lower = (jd_text or "").lower()
    if any(sig in jd_lower for sig in _CONSULTING_SIGNALS):
        return
    analysis["blockers"] = [b for b in blockers if consulting_blocker_prefix not in str(b).lower()]
    analysis["gaps"] = [
        g for g in analysis.get("gaps", []) if consulting_blocker_prefix not in str(g.get("gap", "")).lower()
    ]
    scorecard = analysis.get("scorecard") or {}
    target = scorecard.get("target_alignment")
    if isinstance(target, dict) and float(target.get("score", 5.0) or 5.0) <= 2.0:
        target["score"] = 3.5
        target["reason"] = (
            "[Guardrail] Check A false positive removed — no explicit consulting signals in JD."
        )


def apply_match_guardrails(analysis: dict, match_context: dict) -> dict:
    location = ((match_context or {}).get("matches") or {}).get("location") or {}
    status = location.get("status")
    reason = str(location.get("reason") or "").strip()
    scorecard = analysis.get("scorecard") or {}
    workplace = scorecard.get("workplace_fit")

    if status == "compatible":
        _remove_location_false_positives(analysis)
        if isinstance(workplace, dict) and float(workplace.get("score", 3.0) or 3.0) < 4.0:
            workplace["score"] = 4.0
            workplace["reason"] = reason or "Structured location check found the role compatible."
    elif status == "incompatible":
        blocker = f"Geographic mismatch: {reason}" if reason else "Geographic mismatch"
        if blocker not in analysis.get("blockers", []):
            analysis.setdefault("blockers", []).append(blocker)
        if isinstance(workplace, dict):
            workplace["score"] = min(float(workplace.get("score", 3.0) or 3.0), 1.5)
            workplace["reason"] = reason or "Structured location check found the role incompatible."
        if not any(item.get("gap") == blocker for item in analysis.get("gaps", [])):
            analysis.setdefault("gaps", []).append(
                {"gap": blocker, "severity": "high", "blocker": True, "mitigation": ""}
            )

    _remove_consulting_false_positive(analysis, (match_context or {}).get("_jd_text", ""))
    _remove_softened_tool_blockers(analysis, (match_context or {}).get("_jd_text", ""))

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
    analysis["score"] = score_to_100(scorecard)
    analysis["score_5"] = score_100_to_5(analysis["score"])
    analysis["application_recommendation"] = infer_application_recommendation(analysis["score_5"])
    if analysis.get("blockers"):
        analysis["verdict"] = "no" if analysis["score"] < 65 else "with_adjustments"
    if status == "incompatible":
        analysis["verdict"] = "no"
        analysis["application_recommendation"] = "do_not_apply"
    return analysis


def _scorer_cache_dir() -> Path:
    return Path(settings.state_dir) / ".scorer_cache"


def _scorer_cache_path(job_id: str, model: str) -> Path:
    safe_model = re.sub(r"[^a-zA-Z0-9_\-]", "_", model)
    safe_job = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(job_id))
    return _scorer_cache_dir() / f"{safe_job}__{safe_model}.json"


async def score_with_model(model: str, system: str, user: str) -> dict | None:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    if "mistral" in model:
        messages = llm_client.strip_cache_control(messages)
    try:
        raw = await llm_client.chat_completions(
            model=model, messages=messages, temperature=0.2, max_tokens=2000
        )
        return strip_json(raw)
    except Exception:
        return None


def _job_id_and_label(job: dict) -> tuple[str, str]:
    job_id = str(job.get("job_id", "?"))
    label = f"{job.get('company') or job.get('source_key') or '?'} | {job.get('title', '?')}"
    return job_id, label


async def score_job_ensemble(job: dict, profile_data: dict) -> dict:
    jd_text = str(job.get("jd_text") or "").strip() or synthesize_jd_text(job)
    job_id, _job_label = _job_id_and_label(job)
    profile_text = build_profile_text(profile_data)

    parsed_metadata = {
        "location": job.get("location"),
        "compensation": job.get("compensation"),
        "workplace_type": job.get("workplace_type"),
        "employment_type": job.get("employment_type"),
    }
    match_context = build_match_context_from_profile_data(jd_text, profile_data, parsed_metadata)
    match_context["_jd_text"] = jd_text

    system_with_profile = SCORER_SYSTEM + "\n\nCandidate profile:\n" + profile_text
    user_msg = (
        "Structured candidate/JD match context:\n\n"
        f"{format_match_context(match_context)}\n\n"
        f"Analyze this job posting:\n\n{jd_text}"
    )

    cache_dir = _scorer_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    async def run_scorer(model: str) -> tuple[str, dict] | None:
        cache_path = _scorer_cache_path(job_id, model)
        if cache_path.exists():
            try:
                return model, json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass  # corrupt cache — re-run
        parsed = await score_with_model(model, system_with_profile, user_msg)
        if parsed is None:
            return None
        cache_path.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
        return model, parsed

    scorer_outcomes = await asyncio.gather(
        *(run_scorer(model) for model in settings.nvidia_ensemble_scorers), return_exceptions=True
    )
    scorer_results = [
        {"model": model, "result": parsed}
        for outcome in scorer_outcomes
        if isinstance(outcome, tuple)
        for model, parsed in [outcome]
    ]
    if not scorer_results:
        raise RuntimeError("All scorers failed")

    synth_cache_path = _scorer_cache_path(job_id, f"{settings.nvidia_ensemble_synthesizer}__synthesis")
    synthesis = None
    if synth_cache_path.exists():
        try:
            synthesis = json.loads(synth_cache_path.read_text(encoding="utf-8"))
        except Exception:
            synthesis = None

    if synthesis is None:
        analyses_text = ""
        for i, r in enumerate(scorer_results, 1):
            analyses_text += f"\n\n--- Analysis {i} ({r['model'].split('/')[-1]}) ---\n"
            analyses_text += json.dumps(r["result"], ensure_ascii=False, indent=2)

        synth_user = (
            "Structured candidate/JD match context:\n\n"
            f"{format_match_context(match_context)}\n\n"
            f"Job posting:\n\n{jd_text}\n\nIndependent analyses to synthesize:{analyses_text}"
        )
        synth_system = SYNTHESIS_SYSTEM + "\n\nCandidate profile:\n" + profile_text

        synth_retries = 3
        last_exc: Exception | None = None
        for attempt in range(1, synth_retries + 1):
            synth_raw = await llm_client.chat_completions(
                model=settings.nvidia_ensemble_synthesizer,
                messages=[
                    {"role": "system", "content": synth_system},
                    {"role": "user", "content": synth_user},
                ],
                temperature=0.1,
                max_tokens=2000,
            )
            try:
                synthesis = strip_json(synth_raw)
                synth_cache_path.write_text(json.dumps(synthesis, ensure_ascii=False), encoding="utf-8")
                break
            except Exception as exc:
                last_exc = exc
                if attempt == synth_retries:
                    raise last_exc

    scorecard = synthesis.get("scorecard", {})
    score_100 = score_to_100(scorecard)
    score_5 = round(1.0 + (4.0 * score_100 / 100.0), 1)
    blockers = synthesis.get("blockers", [])
    verdict = synthesis.get("verdict", "yes")

    analysis = {
        "score": score_100,
        "score_5": score_5,
        "verdict": verdict,
        "application_recommendation": infer_application_recommendation(score_5),
        "archetype": synthesis.get("archetype", {}),
        "role_summary": synthesis.get("role_summary", {}),
        "scorecard": scorecard,
        "tool_match": synthesis.get("tool_match", []),
        "forces": synthesis.get("forces", []),
        "faiblesses": synthesis.get("faiblesses", []),
        "gaps": [
            {"gap": f, "severity": "medium", "blocker": False, "mitigation": ""}
            for f in synthesis.get("faiblesses", [])
        ],
        "blockers": blockers,
        "standout_differentiator": synthesis.get("remarques", ""),
        "remarques": synthesis.get("remarques", ""),
        "pipeline": "ensemble",
    }
    analysis = apply_match_guardrails(analysis, match_context)

    # Clean up scorer cache now that the job succeeded.
    for model in settings.nvidia_ensemble_scorers:
        _scorer_cache_path(job_id, model).unlink(missing_ok=True)
    synth_cache_path.unlink(missing_ok=True)

    return analysis
