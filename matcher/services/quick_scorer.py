"""Quick (single-model) fit scorer.

Ported from matcher/job_fit_analyzer.py per the matcher rewrite plan's
"Do NOT change ... the scoring logic, prompt content, guardrails" instruction
— build_system_prompt, synthesize_jd_text, and every guardrail function below
are unchanged from the original except for being made async at the LLM-call
boundary (lib/llm_client.chat_completions replaces requests.post).
"""

import re

from lib import llm_client
from lib.json_utils import (
    compute_overall_score,
    extract_json_payload,
    infer_application_recommendation,
    infer_verdict,
    normalize_analysis_result,
    sanitize_text,
    score_100_to_5,
)
from lib.matching_intelligence import build_match_context_from_profile_data, format_match_context

QUICK_MODEL_MAX_TOKENS = 2600
QUICK_MODEL_TEMPERATURE = 0.2


def build_system_prompt(profile_data: dict) -> str:
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
- Only trigger if the JD contains EXPLICIT, unambiguous evidence: phrases like "client delivery", "billable hours", "client engagements", "placed at client sites", "work at client locations", or the company is explicitly named as a known consultancy (Accenture, McKinsey, Deloitte, BCG, Big 4, etc.).
- Do NOT trigger based on: the word "mission" (common in tech/defense/startups), "partner", "client" in a product context, "services" as a product category, or absence of information about the company type.
- When in doubt, do NOT trigger — a false positive here is more damaging than a false negative.
- If yes → cap `target_alignment` score at 2.0. Add to `blockers`: "Job type: consulting/professional services — not a target employment model."

Check B — Domain match:
- Identify the primary industry domain this role requires experience in (e.g. "financial services", "healthcare", "logistics", "legal tech", …). Do not assume — read the JD.
- Then check whether the candidate's CV shows direct experience in that same domain.
- If the JD treats domain experience as a must-have (explicit requirement, specialist firm, or domain-specific regulation/tooling that cannot transfer) AND the candidate has no direct experience in that domain → cap `relevant_experience` score at 2.0. Add to `blockers`: "Domain mismatch: role requires [detected domain] experience — candidate has none."
- If domain experience is preferred but not required, or the candidate's experience is genuinely transferable, do not cap — reflect the gap in the score naturally (e.g. 2.5–3.5) with a reason.
- Adjacent experience belongs ONLY in `mitigation`. It does not raise a capped score.

Check B2 — Hard requirement with no CV evidence:
- Scan the JD for any requirement phrased with hard-requirement language ("required", "must have", "mandatory", "you must have", "X+ years of [specific thing]") where the candidate's CV contains ZERO direct evidence — not adjacent, not transferable.
- This applies to domain/industry experience, process expertise, and certifications. It does NOT automatically apply to named tools, vendors, or frameworks — see the tool-name rule below.
- For each such unmet hard requirement with no mitigation path:
  - In `requirement_match`, record `is_blocker: true`, `gap_type: "direct_gap"`, `strength: "missing"`, `mitigation: ""`.
  - Cap `relevant_experience` at 2.5.
  - Add to `blockers`: "Hard requirement unmet: [requirement text] — no direct evidence in profile."
- Exception — do NOT cap if ALL of the following are true: (a) the JD uses softening language ("or equivalent", "preferred"), (b) the candidate has a concrete transferable substitute, AND (c) you can write a specific mitigation. In that case, set `mitigation` with the concrete path and score 3.0–3.5.
- A mitigation field must describe a real bridge, not a generic "fast learner" claim.

Tool-name blocker rule:
- Do NOT treat a missing named tool, vendor, framework, or library as a hard blocker if the resume shows equivalent systems, workflows, or technical depth.
- A named-tool gap may only be a hard blocker when ALL THREE are true:
  1. The JD explicitly requires hands-on production experience with that exact tool (not just "familiarity" or "experience with tools like X").
  2. The tool is central to the role's day-to-day execution (not incidental).
  3. The resume shows no equivalent experience or adjacent capability whatsoever.
- If the candidate has built or owned equivalent systems, downgrade to a minor gap or ramp-up note in `gaps` (severity: low), NOT a blocker.

Contradiction guard — apply before finalizing any blocker:
- Review the explanation you wrote for each blocker candidate. If your own explanation contains any of the following phrases: "equivalent systems", "adjacent experience", "similar workflows", "transferable experience", "can ramp up", "built similar", "analogous" — then that item MUST NOT be a hard blocker unless the JD explicitly states the exact tool/skill is mandatory with no substitutes.
- If a contradiction is detected, move the item to `gaps` with severity: low and populate `mitigation` with the bridging path you identified.

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


def _bullet_lines(items):
    return "\n".join(f"- {item}" for item in items if str(item).strip())


def synthesize_jd_text(record: dict) -> str:
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
    add(
        "Technical tools mentioned",
        ", ".join(str(item) for item in technical_tools if str(item).strip()),
    )

    if responsibilities:
        sections.append("Responsibilities:\n" + _bullet_lines(responsibilities))
    if must_have:
        sections.append("Requirements:\n" + _bullet_lines(must_have))
    if nice_to_have:
        sections.append("Nice-to-have:\n" + _bullet_lines(nice_to_have))

    body = record.get("jd_text")
    if body and str(body).strip():
        sections.append(f"Job description:\n{body}")

    return "\n\n".join(section for section in sections if section.strip())


def add_gap_once(analysis, gap):
    existing = {
        str(item.get("gap", "")).strip().lower()
        for item in analysis.get("gaps", [])
        if isinstance(item, dict)
    }
    if str(gap.get("gap", "")).strip().lower() not in existing:
        analysis.setdefault("gaps", []).append(gap)


def remove_incompatible_location_false_positives(analysis):
    location_terms = ("geographic mismatch", "location mismatch", "state exclusion", "country mismatch")
    for key in ("blockers", "faiblesses"):
        analysis[key] = [
            item
            for item in analysis.get(key, [])
            if not any(term in str(item).lower() for term in location_terms)
        ]
    analysis["gaps"] = [
        item
        for item in analysis.get("gaps", [])
        if not any(term in str(item.get("gap", "")).lower() for term in location_terms)
    ]


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
        add_gap_once(
            analysis,
            {
                "gap": blocker_text,
                "severity": "high",
                "blocker": True,
                "mitigation": "",
            },
        )


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


def _remove_softened_tool_blockers(analysis, jd_text):
    """Strip tool-name blockers when the JD uses softening language for that tool."""
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
        if _TOOL_BLOCKER_PATTERNS.search(b_lower):
            if any(tool in b_lower for tool in softened_tools):
                demoted.append(b)
                continue
        kept_blockers.append(b)

    if not demoted:
        return

    analysis["blockers"] = kept_blockers
    for b in demoted:
        add_gap_once(
            analysis,
            {
                "gap": str(b)
                .replace("Unmet hard requirement: ", "Tool ramp-up: ")
                .replace("Hard requirement unmet: ", "Tool ramp-up: "),
                "severity": "low",
                "blocker": False,
                "mitigation": "JD uses softening language ('tools like X') — direct tool experience not strictly required.",
            },
        )


def _remove_consulting_false_positive(analysis, jd_text):
    """Strip Check A blocker if the JD contains no explicit consulting signals."""
    consulting_blocker_prefix = "job type: consulting"
    blockers = analysis.get("blockers", [])
    has_blocker = any(consulting_blocker_prefix in str(b).lower() for b in blockers)
    if not has_blocker:
        return

    jd_lower = (jd_text or "").lower()
    if any(sig in jd_lower for sig in _CONSULTING_SIGNALS):
        return  # Explicit evidence found — keep the blocker

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


def apply_match_guardrails(analysis, match_context):
    location = ((match_context or {}).get("matches") or {}).get("location") or {}
    status = location.get("status")
    reason = sanitize_text(location.get("reason"))
    scorecard = analysis.get("scorecard") or {}
    workplace = scorecard.get("workplace_fit")

    if status == "compatible":
        remove_incompatible_location_false_positives(analysis)
        if isinstance(workplace, dict) and float(workplace.get("score", 3.0) or 3.0) < 4.0:
            workplace["score"] = 4.0
            workplace["reason"] = reason or "Structured location check found the role compatible."
    elif status == "incompatible":
        blocker = f"Geographic mismatch: {reason}" if reason else "Geographic mismatch"
        if blocker not in analysis.get("blockers", []):
            analysis.setdefault("blockers", []).append(blocker)
        add_gap_once(
            analysis,
            {
                "gap": blocker,
                "severity": "high",
                "blocker": True,
                "mitigation": "",
            },
        )
        if isinstance(workplace, dict):
            workplace["score"] = min(float(workplace.get("score", 3.0) or 3.0), 1.5)
            workplace["reason"] = reason or "Structured location check found the role incompatible."

    _remove_consulting_false_positive(analysis, (match_context or {}).get("_jd_text", ""))
    _remove_softened_tool_blockers(analysis, (match_context or {}).get("_jd_text", ""))
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


async def score_job_quick(job: dict, profile_data: dict, model: str) -> dict:
    jd_text = synthesize_jd_text(job)
    parsed_metadata = {
        "location": job.get("location"),
        "compensation": job.get("compensation"),
        "workplace_type": job.get("workplace_type"),
        "employment_type": job.get("employment_type"),
    }
    match_context = build_match_context_from_profile_data(jd_text, profile_data, parsed_metadata)
    match_context["_jd_text"] = jd_text
    system_prompt = build_system_prompt(profile_data)

    user_content = (
        "Here is the structured candidate/JD match context. Treat deterministic location compatibility, "
        "must-have vs nice-to-have grouping, and explicit tool mentions as the source of truth unless the JD text clearly contradicts it:\n\n"
        f"{format_match_context(match_context)}\n\n"
        f"Here is the job posting to analyze:\n\n{jd_text}"
    )

    raw = await llm_client.chat_completions(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt, "cache_control": {"type": "ephemeral"}},
            {"role": "user", "content": user_content},
        ],
        temperature=QUICK_MODEL_TEMPERATURE,
        max_tokens=QUICK_MODEL_MAX_TOKENS,
        response_format={"type": "json_object"},
    )
    parsed = extract_json_payload(raw)
    parsed["_pipeline_tag"] = "maverick"
    normalized = normalize_analysis_result(parsed)
    guarded = apply_match_guardrails(normalized, match_context)
    return guarded
