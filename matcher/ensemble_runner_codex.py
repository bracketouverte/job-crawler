#!/usr/bin/env python3
"""
Ensemble fit analyzer: runs 3 scorer models in parallel per JD, then synthesizes
with DeepSeek. Accepts the same --jobs-jsonl / --results-jsonl interface as
job_fit_analyzer.py so server.ts can call it as a drop-in replacement.
"""
import os, sys, json, time, re, argparse, concurrent.futures
from pathlib import Path
import requests

try:
    from matching_intelligence_codex import build_match_context, format_match_context
except ImportError:  # pragma: no cover
    from .matching_intelligence_codex import build_match_context, format_match_context

BASE_DIR = Path(__file__).parent
DEFAULT_PROFILE_DIR = "career-ops"

API_KEY = os.environ.get("NVIDIA_API_KEY", "").strip()
URL = "https://integrate.api.nvidia.com/v1/chat/completions"

SCORERS = [
    "meta/llama-4-maverick-17b-128e-instruct",
    "moonshotai/kimi-k2-instruct",
    "deepseek-ai/deepseek-v3.2",
]
SYNTHESIZER = "deepseek-ai/deepseek-v3.2"

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

SCORER_SYSTEM = """You are a senior technical recruiting evaluator. Evaluate the job posting against the candidate profile.
""" + _PRE_SCORING_CHECKS + """
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

SYNTHESIS_SYSTEM = """You are a senior technical recruiting evaluator synthesizing multiple independent analyses of the same candidate + job.
""" + _PRE_SCORING_CHECKS + """
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


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def load_profile(profile_dir):
    files = ["profile.yml", "portals.yml", "cv.md", "_profile.md"]
    root = Path(profile_dir) if Path(profile_dir).is_absolute() else BASE_DIR / profile_dir
    data = {}
    for f in files:
        p = root / f
        data[f] = p.read_text(encoding="utf-8") if p.exists() else f"File {f} not found"
    return data


def build_profile_text(profile_data):
    return (
        f"=== IDENTITY ===\n{profile_data.get('profile.yml', '')}\n\n"
        f"=== TARGET KEYWORDS ===\n{profile_data.get('portals.yml', '')}\n\n"
        f"=== EXPERIENCE ===\n{profile_data.get('cv.md', '')}\n\n"
        f"=== APPLICATION STRATEGY ===\n{profile_data.get('_profile.md', '')}"
    )


def strip_json(content):
    content = re.sub(r"^```(?:json)?\s*", "", content.strip())
    content = re.sub(r"\s*```$", "", content.strip())
    try:
        return json.loads(content)
    except Exception:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise


def call_model(model, system, user_content, max_tokens=2000, temperature=0.2, retries=3):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(URL, headers=headers, json=payload, timeout=180)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            if attempt == retries:
                raise
            wait = attempt * 2
            log(f"[ensemble] {model.split('/')[-1]} | attempt {attempt}/{retries} failed: {e} | retrying in {wait}s")
            time.sleep(wait)


def score_to_100(scorecard):
    weights = {
        "core_skills": 0.25,
        "relevant_experience": 0.25,
        "target_alignment": 0.20,
        "seniority_fit": 0.10,
        "workplace_fit": 0.10,
        "requirements_coverage": 0.10,
    }
    weighted = sum(scorecard.get(k, {}).get("score", 3.0) * w for k, w in weights.items())
    return int(round(((weighted - 1.0) / 4.0) * 100.0))


def infer_recommendation(score_5):
    if score_5 >= 4.5: return "apply_now"
    if score_5 >= 4.0: return "worth_applying"
    if score_5 >= 3.5: return "only_if_strategic"
    return "do_not_apply"


def score_100_to_5(score):
    return round(max(1.0, min(5.0, 1.0 + (4.0 * float(score) / 100.0))), 1)


def remove_location_false_positives(analysis):
    terms = ("geographic mismatch", "location mismatch", "state exclusion", "country mismatch")
    for key in ("blockers", "faiblesses"):
        analysis[key] = [item for item in analysis.get(key, []) if not any(term in str(item).lower() for term in terms)]
    analysis["gaps"] = [
        item for item in analysis.get("gaps", [])
        if not any(term in str(item.get("gap", "")).lower() for term in terms)
    ]


def apply_match_guardrails(analysis, match_context):
    location = ((match_context or {}).get("matches") or {}).get("location") or {}
    status = location.get("status")
    reason = str(location.get("reason") or "").strip()
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
        if isinstance(workplace, dict):
            workplace["score"] = min(float(workplace.get("score", 3.0) or 3.0), 1.5)
            workplace["reason"] = reason or "Structured location check found the role incompatible."
        if not any(item.get("gap") == blocker for item in analysis.get("gaps", [])):
            analysis.setdefault("gaps", []).append({"gap": blocker, "severity": "high", "blocker": True, "mitigation": ""})

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
    analysis["application_recommendation"] = infer_recommendation(analysis["score_5"])
    if analysis.get("blockers"):
        analysis["verdict"] = "no" if analysis["score"] < 65 else "with_adjustments"
    if status == "incompatible":
        analysis["verdict"] = "no"
        analysis["application_recommendation"] = "do_not_apply"
    return analysis


def ensemble_analyze(jd_text, profile_text, job_label):
    match_context = build_match_context(jd_text, profile_text)
    system_with_profile = SCORER_SYSTEM + "\n\nCandidate profile:\n" + profile_text
    user_msg = (
        "Structured candidate/JD match context:\n\n"
        f"{format_match_context(match_context)}\n\n"
        f"Analyze this job posting:\n\n{jd_text}"
    )

    # Phase 1: parallel scoring
    scorer_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(SCORERS)) as pool:
        futures = {pool.submit(call_model, m, system_with_profile, user_msg): m for m in SCORERS}
        for f in concurrent.futures.as_completed(futures):
            model = futures[f]
            try:
                parsed = strip_json(f.result())
                scorer_results.append({"model": model, "result": parsed})
                sc = parsed.get("scorecard", {})
                avg = round(sum(v.get("score", 0) for v in sc.values()) / max(len(sc), 1), 2)
                log(f"[ensemble] {job_label} | scorer {model.split('/')[-1]} | avg={avg}")
            except Exception as e:
                log(f"[ensemble] {job_label} | scorer {model.split('/')[-1]} | error: {e}")

    if not scorer_results:
        raise RuntimeError("All scorers failed")

    # Phase 2: synthesis
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

    log(f"[ensemble] {job_label} | synthesizing with {SYNTHESIZER.split('/')[-1]}…")
    synth_raw = call_model(SYNTHESIZER, synth_system, synth_user, max_tokens=2000, temperature=0.1)
    synthesis = strip_json(synth_raw)
    log(f"[ensemble] {job_label} | synthesis done")

    return synthesis, match_context


def process_batch(input_file, output_file, profile_text, pipeline_tag="codex-ensemble"):
    results = []
    total = succeeded = failed = 0

    with open(input_file, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]

    total = len(lines)
    log(f"[ensemble-batch] start | jobs={total}")

    with open(output_file, "w", encoding="utf-8") as out:
        for i, line in enumerate(lines, 1):
            try:
                job = json.loads(line)
            except Exception:
                log(f"[ensemble-batch] line {i} | invalid json")
                failed += 1
                continue

            provider = job.get("provider", "?")
            source_key = job.get("source_key", "?")
            job_id = job.get("job_id", "?")
            title = job.get("title", "?")
            job_label = f"#{i} {source_key} | {title}"
            jd_text = job.get("jd_text", "").strip()

            if not jd_text:
                log(f"[ensemble-batch] {job_label} | empty jd_text")
                failed += 1
                continue

            log(f"[ensemble-batch] {job_label} | start | jd_chars={len(jd_text)}")
            t0 = time.time()
            try:
                synthesis, match_context = ensemble_analyze(jd_text, profile_text, job_label)
                scorecard = synthesis.get("scorecard", {})
                score_100 = score_to_100(scorecard)
                score_5 = round(1.0 + (4.0 * score_100 / 100.0), 1)
                blockers = synthesis.get("blockers", [])
                verdict = synthesis.get("verdict", "yes")
                recommendation = infer_recommendation(score_5)

                analysis = {
                    "score": score_100,
                    "score_5": score_5,
                    "verdict": verdict,
                    "application_recommendation": recommendation,
                    "archetype": synthesis.get("archetype", {}),
                    "role_summary": synthesis.get("role_summary", {}),
                    "scorecard": scorecard,
                    "tool_match": synthesis.get("tool_match", []),
                    "forces": synthesis.get("forces", []),
                    "faiblesses": synthesis.get("faiblesses", []),
                    "gaps": [{"gap": f, "severity": "medium", "blocker": False, "mitigation": ""} for f in synthesis.get("faiblesses", [])],
                    "blockers": blockers,
                    "standout_differentiator": synthesis.get("remarques", ""),
                    "remarques": synthesis.get("remarques", ""),
                    "pipeline": pipeline_tag,
                }
                analysis = apply_match_guardrails(analysis, match_context)
                score_100 = analysis["score"]
                verdict = analysis["verdict"]
                row = {
                    "provider": provider,
                    "source_key": source_key,
                    "job_id": job_id,
                    "title": title,
                    "status": "ok",
                    "elapsed": round(time.time() - t0, 1),
                    "analysis": analysis,
                }
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                succeeded += 1
                log(f"[ensemble-batch] {job_label} | done | score={score_100} verdict={verdict} elapsed={row['elapsed']}s")
            except Exception as e:
                log(f"[ensemble-batch] {job_label} | error: {e}")
                row = {
                    "provider": provider, "source_key": source_key, "job_id": job_id,
                    "title": title, "status": "error", "score": 0, "verdict": "no",
                    "error": str(e)[:300],
                }
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                failed += 1

    summary = {"total": total, "succeeded": succeeded, "failed": failed}
    log(f"[ensemble-batch] done | {summary}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Ensemble job fit analyzer")
    parser.add_argument("--jobs-jsonl", required=True)
    parser.add_argument("--results-jsonl", required=True)
    parser.add_argument("--profile-dir", default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--pipeline", default="codex-ensemble", help="Pipeline tag written to analysis.pipeline")
    args = parser.parse_args()

    if not API_KEY:
        print("❌ NVIDIA_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    print(f"📁 Loading profile files…")
    profile_data = load_profile(args.profile_dir)
    profile_text = build_profile_text(profile_data)

    print(f"📚 Ensemble batch: {args.jobs_jsonl}")
    print(f"🧠 Scorers: {', '.join(s.split('/')[-1] for s in SCORERS)} → {SYNTHESIZER.split('/')[-1]}")

    summary = process_batch(args.jobs_jsonl, args.results_jsonl, profile_text, pipeline_tag=args.pipeline)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
