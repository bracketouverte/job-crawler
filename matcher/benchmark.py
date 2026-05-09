#!/usr/bin/env python3
import os, json, time, requests, concurrent.futures, re

API_KEY = os.environ["NVIDIA_API_KEY"]
URL = "https://integrate.api.nvidia.com/v1"

MODELS = [
    "meta/llama-4-maverick-17b-128e-instruct",
    "moonshotai/kimi-k2-instruct",
    "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "nvidia/nemotron-3-nano-30b-a3b",
]

SYSTEM = """You are a senior technical recruiting evaluator. Evaluate the job posting and return ONLY valid JSON with this exact structure:
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
  "blockers": [],
  "verdict": "yes",
  "remarques": "..."
}
Scores 1.0-5.0. Return JSON only, no markdown, no explanation."""

PROFILE = """Candidate: Michael Levy, Cooper City FL, EST
Target: Senior Technical Product Manager / Senior PM

CV highlights:
- Principal PM, 10+ years B2B SaaS, 0-to-scale platforms
- Former full-stack developer (strong technical depth)
- Founder/PM Job Explorer: B2B SaaS ATS/CRM, 0->1M ARR, 5,000+ users, 14 years, 20+ integrations
- Senior Technical PO Apave: mobile inspection platform, 3,000+ field inspectors, ELK observability pipeline (1M+ reports), adoption x3, inspection speed +30%, errors -50%
- Product Advisor Hunel: ATS integration strategy, cut GTM by 2 months
- Strong: AI/LLM product, agentic workflows, API/integrations, regulated environments, cross-functional leadership
- Comp target: 150K-200K USD, remote preferred, no sponsorship needed, US-based
Archetypes: Technical AI PM (primary), AI Platform/LLMOps, Agentic/Automation"""

JDS = {
    "SmartRecruiters - Sr PM Career Sites": """Title: Senior Product Manager (Career Sites)
Company: SmartRecruiters (SAP company)
Location: Remote USA (East Coast, 8AM ET start required)
Employment: Full-time

Description: Own defined problem spaces within career sites product area. Contribute to shared roadmap across multiple PMs. Lead discovery: candidate, customer, market needs. Partner with engineering and design to ship enterprise-ready career site capabilities. Balance usability, performance, accessibility, SEO, localization, compliance. Collaborate with platform, AI, integrations, SAP teams. Define and track success metrics: conversion, engagement, adoption, performance.

Requirements: 6+ years PM in B2B SaaS or enterprise software. Experience building career sites, job boards, candidate portals, ATS front-ends, or job search/discovery. Strong product discovery skills. Technical fluency, familiarity with CMS, SEO for job listings, web performance a plus. Experience with global high-traffic products (localization, accessibility, compliance).""",

    "Wrapbook - Sr PM II Production Payroll": """Title: Senior Product Manager II
Company: Wrapbook
Location: United States (Remote)

Responsibilities: Own roadmap and vision for product area. Collaborate cross-functionally with sales, legal, go-to-market. Deep understanding of production payroll domain. Define success metrics, data-driven prioritization. Advocate for quality and compliance in financial/regulated environments. Drive execution end-to-end. Use AI tools daily - discovery, analysis, writing, code comprehension, prototyping. PMs expected to be builders, not just strategists.

Requirements: Strong PM fundamentals, cross-functional collaboration, regulated/financial domain experience, AI tool fluency, builder mindset.""",

    "A Place for Mom - Sr/Lead PM Agentic": """Title: Senior/Lead Product Manager, Agentic Experiences
Company: A Place for Mom
Location: United States (Remote)
Compensation: 165,000-195,000 USD/year

Responsibilities: Build and ship agentic products - conversational agents, intelligent matching, automated guidance. Own product vision, roadmap, execution for consumer-facing AI experiences. Prototype rapidly using AI coding tools and agent frameworks. Define how AI agents interact with families across channels. Ship iteratively, experimentation and data-driven. Identify highest-leverage opportunities for agentic experiences. Reports to Director of Product.

Requirements: Strong product fundamentals + deep hands-on AI fluency. Built agents, written production prompts, opinions on model selection, tool use patterns, eval frameworks. Technical depth: evaluate agentic approaches, design for messy LLM outputs, pragmatic tradeoffs. Consumer empathy - families in stressful care decisions.""",
}


def call_model(model, jd_name, jd_text):
    t0 = time.time()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM + "\n\nCandidate profile:\n" + PROFILE, "cache_control": {"type": "ephemeral"}},
            {"role": "user", "content": "Analyze this job posting:\n\n" + jd_text},
        ],
        "temperature": 0.2,
        "max_tokens": 1500,
    }
    if "nemotron-super" in model:
        payload["nvext"] = {"thinking": "on"}
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    try:
        r = requests.post(f"{URL}/chat/completions", headers=headers, json=payload, timeout=180)
        elapsed = round(time.time() - t0, 1)
        if not r.ok:
            return {"model": model, "jd": jd_name, "error": f"HTTP {r.status_code}: {r.text[:200]}", "elapsed": elapsed}
        msg = r.json()["choices"][0]["message"]
        content = msg.get("content") or msg.get("reasoning_content", "") or ""
        content = re.sub(r"^```(?:json)?\s*", "", content.strip())
        content = re.sub(r"\s*```$", "", content.strip())
        try:
            parsed = json.loads(content)
        except Exception:
            m = re.search(r"\{.*\}", content, re.DOTALL)
            parsed = json.loads(m.group()) if m else {"raw": content[:300]}
        return {"model": model, "jd": jd_name, "result": parsed, "elapsed": elapsed}
    except Exception as e:
        return {"model": model, "jd": jd_name, "error": str(e)[:120], "elapsed": round(time.time() - t0, 1)}


tasks = [(m, jd_name, jd_text) for m in MODELS for jd_name, jd_text in JDS.items()]
results = []

with concurrent.futures.ThreadPoolExecutor(max_workers=18) as pool:
    futures = {pool.submit(call_model, m, jn, jt): (m, jn) for m, jn, jt in tasks}
    for f in concurrent.futures.as_completed(futures):
        res = f.result()
        results.append(res)
        if "error" in res:
            print(f"[{res['elapsed']}s] ERROR  {res['model'][:42]} | {res['jd'][:35]} | {res['error'][:80]}", flush=True)
        else:
            sc = res["result"].get("scorecard", {})
            avg = round(sum(v.get("score", 0) for v in sc.values()) / len(sc), 2) if sc else 0
            print(f"[{res['elapsed']}s] OK     {res['model'][:42]} | {res['jd'][:35]} | avg={avg} verdict={res['result'].get('verdict', '?')}", flush=True)

print("\n===JSON_RESULTS===")
print(json.dumps(results, ensure_ascii=False, indent=2))
