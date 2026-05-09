#!/usr/bin/env python3
import os, json, time, requests, concurrent.futures, re

API_KEY = os.environ["NVIDIA_API_KEY"]
URL = "https://integrate.api.nvidia.com/v1"

# Scorer models (run in parallel per JD)
SCORERS = [
    "meta/llama-4-maverick-17b-128e-instruct",
    "moonshotai/kimi-k2-instruct",
    "deepseek-ai/deepseek-v3.2",
]

# Synthesizer — best reasoning quality from single-model benchmark
SYNTHESIZER = "deepseek-ai/deepseek-v3.2"

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

SYNTHESIS_SYSTEM = """You are a senior technical recruiting evaluator. You will receive multiple independent fit analyses for the same candidate and job posting. Your task is to synthesize them into one authoritative assessment.

Rules:
- If models agree on a score (within 0.5), use that score
- If models diverge on a score, reason through which assessment is most accurate and explain the disagreement in the reason field
- Synthesize forces/faiblesses/blockers: keep unique insights from each model, remove duplicates
- Write a remarques that integrates the best insights from all models
- Return ONLY valid JSON with this exact structure:
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
Return JSON only, no markdown, no explanation."""

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


def strip_json(content):
    content = re.sub(r"^```(?:json)?\s*", "", content.strip())
    content = re.sub(r"\s*```$", "", content.strip())
    try:
        return json.loads(content)
    except Exception:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        return json.loads(m.group()) if m else {"raw": content[:500]}


def call_scorer(model, jd_name, jd_text):
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
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    try:
        r = requests.post(f"{URL}/chat/completions", headers=headers, json=payload, timeout=180)
        elapsed = round(time.time() - t0, 1)
        if not r.ok:
            return {"model": model, "jd": jd_name, "error": f"HTTP {r.status_code}: {r.text[:200]}", "elapsed": elapsed}
        content = r.json()["choices"][0]["message"]["content"]
        parsed = strip_json(content)
        return {"model": model, "jd": jd_name, "result": parsed, "elapsed": elapsed}
    except Exception as e:
        return {"model": model, "jd": jd_name, "error": str(e)[:200], "elapsed": round(time.time() - t0, 1)}


def call_synthesizer(jd_name, jd_text, scorer_results):
    t0 = time.time()
    analyses_text = ""
    for i, r in enumerate(scorer_results, 1):
        model_short = r["model"].split("/")[-1]
        analyses_text += f"\n\n--- Analysis {i} ({model_short}) ---\n"
        analyses_text += json.dumps(r["result"], ensure_ascii=False, indent=2)

    payload = {
        "model": SYNTHESIZER,
        "messages": [
            {"role": "system", "content": SYNTHESIS_SYSTEM + "\n\nCandidate profile:\n" + PROFILE},
            {"role": "user", "content": f"Job posting:\n\n{jd_text}\n\nIndependent analyses to synthesize:{analyses_text}"},
        ],
        "temperature": 0.1,
        "max_tokens": 2000,
    }
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    try:
        r = requests.post(URL, headers=headers, json=payload, timeout=180)
        elapsed = round(time.time() - t0, 1)
        if not r.ok:
            return {"error": f"HTTP {r.status_code}: {r.text[:200]}", "elapsed": elapsed}
        content = r.json()["choices"][0]["message"]["content"]
        parsed = strip_json(content)
        return {"result": parsed, "elapsed": elapsed}
    except Exception as e:
        return {"error": str(e)[:200], "elapsed": round(time.time() - t0, 1)}


# Phase 1: all scorer calls in parallel (9 total: 3 models × 3 JDs)
print("=== Phase 1: Scoring (3 models × 3 JDs in parallel) ===")
scorer_tasks = [(m, jd_name, jd_text) for jd_name, jd_text in JDS.items() for m in SCORERS]
scorer_results_raw = []

with concurrent.futures.ThreadPoolExecutor(max_workers=9) as pool:
    futures = {pool.submit(call_scorer, m, jn, jt): (m, jn) for m, jn, jt in scorer_tasks}
    for f in concurrent.futures.as_completed(futures):
        res = f.result()
        scorer_results_raw.append(res)
        if "error" in res:
            print(f"  [{res['elapsed']}s] ERROR  {res['model'].split('/')[-1][:30]} | {res['jd'][:35]} | {res['error'][:80]}", flush=True)
        else:
            sc = res["result"].get("scorecard", {})
            avg = round(sum(v.get("score", 0) for v in sc.values()) / len(sc), 2) if sc else 0
            print(f"  [{res['elapsed']}s] OK     {res['model'].split('/')[-1][:30]} | {res['jd'][:35]} | avg={avg}", flush=True)

# Group by JD
by_jd = {}
for res in scorer_results_raw:
    jd = res["jd"]
    if jd not in by_jd:
        by_jd[jd] = []
    if "result" in res:
        by_jd[jd].append(res)

# Phase 2: synthesize per JD (3 synthesis calls, run in parallel)
print("\n=== Phase 2: Synthesis (DeepSeek synthesizes per JD) ===")
ensemble_results = []

def synthesize_jd(jd_name):
    jd_text = JDS[jd_name]
    valid_scores = by_jd.get(jd_name, [])
    if not valid_scores:
        return {"jd": jd_name, "error": "no valid scorer results", "scorers": [], "synthesis": None}
    print(f"  Synthesizing {jd_name[:40]} ({len(valid_scores)} scorer results)…", flush=True)
    synth = call_synthesizer(jd_name, jd_text, valid_scores)
    if "error" in synth:
        print(f"  [{synth['elapsed']}s] ERROR synthesis {jd_name[:35]} | {synth['error'][:80]}", flush=True)
    else:
        sc = synth["result"].get("scorecard", {})
        avg = round(sum(v.get("score", 0) for v in sc.values()) / len(sc), 2) if sc else 0
        print(f"  [{synth['elapsed']}s] OK synthesis {jd_name[:35]} | avg={avg} verdict={synth['result'].get('verdict','?')}", flush=True)
    return {
        "jd": jd_name,
        "scorers": valid_scores,
        "synthesis": synth,
    }

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    futures = {pool.submit(synthesize_jd, jd_name): jd_name for jd_name in JDS}
    for f in concurrent.futures.as_completed(futures):
        ensemble_results.append(f.result())

print("\n===JSON_RESULTS===")
print(json.dumps(ensemble_results, ensure_ascii=False, indent=2))
