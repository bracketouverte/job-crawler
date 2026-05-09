#!/usr/bin/env python3
"""Quick benchmark: nemotron-super-49b vs maverick vs kimi on trimmed JDs."""
import os, requests, json, time, re, concurrent.futures

API_KEY = os.environ["NVIDIA_API_KEY"]
URL = "https://integrate.api.nvidia.com/v1/chat/completions"
headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

SYSTEM = (
    'You are a senior technical recruiting evaluator. Evaluate the job posting and return ONLY valid JSON '
    'with this exact structure:\n'
    '{"archetype": {"primary": "...", "secondary": "..."}, "role_summary": {"domain": "...", "seniority": "...", "remote_policy": "...", "tldr": "..."}, '
    '"scorecard": {"core_skills": {"score": 4.0, "reason": "..."}, "relevant_experience": {"score": 4.0, "reason": "..."}, '
    '"target_alignment": {"score": 4.0, "reason": "..."}, "seniority_fit": {"score": 4.0, "reason": "..."}, '
    '"workplace_fit": {"score": 4.0, "reason": "..."}, "requirements_coverage": {"score": 4.0, "reason": "..."}}, '
    '"forces": ["...", "...", "..."], "faiblesses": ["...", "..."], "blockers": [], "verdict": "yes", "remarques": "..."}\n'
    'Scores 1.0-5.0. Return JSON only, no markdown, no explanation.'
)

PROFILE = (
    "Candidate: Michael Levy, Cooper City FL, EST\n"
    "Target: Senior Technical Product Manager / Senior PM\n"
    "CV: Principal PM 10+ yrs B2B SaaS 0-to-scale, ex-full-stack dev, "
    "Founder Job Explorer (B2B SaaS ATS/CRM 0->1M ARR 5k users 14yr 20+ integrations), "
    "Sr Technical PO Apave (mobile inspection 3k field inspectors ELK 1M+ reports adoption x3 speed+30% errors-50%), "
    "Product Advisor Hunel (ATS integration GTM -2mo). "
    "Strong: AI/LLM product agentic workflows API/integrations regulated cross-functional. "
    "Comp 150-200K USD remote preferred no sponsorship US-based.\n"
    "Archetypes: Technical AI PM (primary), AI Platform/LLMOps, Agentic/Automation"
)

JDS = {
    "SmartRecruiters - Sr PM Career Sites": (
        "Title: Senior Product Manager (Career Sites)\nCompany: SmartRecruiters (SAP)\n"
        "Location: Remote USA (East Coast, 8AM ET)\n"
        "Description: Own career sites product area. Shared roadmap. Lead discovery. Partner eng/design. "
        "Balance usability performance accessibility SEO localization compliance. Collaborate platform AI integrations SAP teams. "
        "Track metrics: conversion engagement adoption.\n"
        "Requirements: 6+ yrs PM B2B SaaS enterprise. Experience career sites job boards ATS front-ends or job search. "
        "Strong discovery. Technical fluency, CMS SEO web performance. Global high-traffic products."
    ),
    "Wrapbook - Sr PM II Payroll": (
        "Title: Senior Product Manager II\nCompany: Wrapbook\nLocation: US Remote\n"
        "Responsibilities: Own roadmap. Cross-functional sales legal GTM. Deep production payroll domain knowledge. "
        "Success metrics data-driven. Quality compliance financial regulated. Drive execution. "
        "Use AI tools daily (discovery analysis writing code prototyping). Builders not strategists.\n"
        "Requirements: Strong PM fundamentals cross-functional regulated/financial domain AI tool fluency builder mindset."
    ),
    "A Place for Mom - Lead PM Agentic": (
        "Title: Senior/Lead PM Agentic Experiences\nCompany: A Place for Mom\nLocation: US Remote\nComp: 165-195K\n"
        "Responsibilities: Build ship agentic products conversational agents intelligent matching automated guidance. "
        "Own vision roadmap execution consumer-facing AI. Prototype rapidly AI coding tools agent frameworks. "
        "Define how AI agents interact with families. Ship iteratively experimentation data-driven.\n"
        "Requirements: Strong product fundamentals deep hands-on AI fluency. Built agents written production prompts "
        "opinions on model selection tool use patterns eval frameworks. Technical depth: evaluate agentic approaches "
        "design for messy LLM outputs. Consumer empathy."
    ),
}

MODELS = [
    ("nvidia/llama-3.3-nemotron-super-49b-v1.5", {"nvext": {"thinking": "on"}}),
    ("meta/llama-4-maverick-17b-128e-instruct", {}),
    ("moonshotai/kimi-k2-instruct", {}),
]


def call(jd_name, jd_text, model, extra_payload):
    t0 = time.time()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM + "\n\nCandidate profile:\n" + PROFILE},
            {"role": "user", "content": "Analyze this job posting:\n\n" + jd_text},
        ],
        "temperature": 0.2,
        "max_tokens": 1500,
    }
    payload.update(extra_payload)
    try:
        r = requests.post(URL, headers=headers, json=payload, timeout=120)
        elapsed = round(time.time() - t0, 1)
        if not r.ok:
            return jd_name, model, None, elapsed, f"HTTP {r.status_code}: {r.text[:100]}"
        msg = r.json()["choices"][0]["message"]
        content = msg.get("content") or msg.get("reasoning_content", "")
        content = content.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            return jd_name, model, None, elapsed, f"no JSON: {content[:100]}"
        parsed = json.loads(m.group())
        return jd_name, model, parsed, elapsed, None
    except Exception as e:
        return jd_name, model, None, round(time.time() - t0, 1), str(e)[:100]


tasks = [(jn, jt, m, ep) for jn, jt in JDS.items() for m, ep in MODELS]

with concurrent.futures.ThreadPoolExecutor(max_workers=9) as pool:
    futures = [pool.submit(call, *t) for t in tasks]
    for f in concurrent.futures.as_completed(futures):
        jd_name, model, parsed, elapsed, err = f.result()
        short_model = model.split("/")[-1]
        if err:
            print(f"[{elapsed}s] ERROR {short_model[:40]} | {jd_name[:38]} | {err}")
        else:
            sc = parsed.get("scorecard", {})
            avg = round(sum(v.get("score", 0) for v in sc.values()) / len(sc), 2) if sc else 0
            print(f"[{elapsed}s] OK    {short_model[:40]} | {jd_name[:38]} | avg={avg} verdict={parsed.get('verdict', '?')}")
            print(json.dumps(parsed, indent=2, ensure_ascii=False))
            print("---")
