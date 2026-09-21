"""Laya-backed job-title pre-filter (System-1 gate before the LLM ensemble).

POST /score  {"title": str, "targets": [str, ...]}
  -> {"match": bool, "family": str|null, "confidence": float, "engine": "laya"|"substring",
       "latency_ms": int}

GET /health -> {"status": "ok", "engine": ..., "model": ...}

Behavior:
- Tries the English `laya` checkpoint (`convaiinnovations/laya`) loaded once at
  startup. Keeps the `choice` label set small (<=12 families + "other") because
  Laya accuracy degrades with high-cardinality option sets.
- If laya/torch is unavailable or inference fails, falls back to a normalized
  substring rule so the caller can still gate cheaply. Low confidence is left
  to the caller (viewer falls back to the LLM ensemble).
"""

from __future__ import annotations

import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

MODEL_REPO = os.environ.get("LAYA_MODEL_REPO", "convaiinnovations/laya")
PORT = int(os.environ.get("PORT", "8001"))
MATCH_THRESHOLD = float(os.environ.get("TITLE_MATCH_MIN_CONFIDENCE", "0.85"))
MAX_FAMILIES = 12

_agent = None
_agent_error: str | None = None

try:
    import laya  # type: ignore

    _agent = laya.load(MODEL_REPO)
    _ENGINE = "laya"
except Exception as exc:  # torch missing, no network, etc. -> substring fallback
    _agent = None
    _agent_error = str(exc)
    _ENGINE = "substring"


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9+\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def family_key(target: str) -> str:
    return normalize(target) or target.strip().lower()


def substring_score(title: str, targets: list[str]) -> tuple[bool, str | None, float]:
    norm = normalize(title)
    for target in targets:
        key = family_key(target)
        if key and key in norm:
            return True, target, 1.0
    return False, None, 1.0


def laya_score(title: str, targets: list[str]) -> tuple[bool, str | None, float]:
    """Single-forward-pass `choice` over target families + other."""
    assert _agent is not None
    families = [t for t in dict.fromkeys(targets) if t.strip()][:MAX_FAMILIES]
    criteria = {family_key(t): t for t in families}
    criteria["other"] = "everything else"
    questions = {
        "title_family": {
            "type": "choice",
            "instructions": "Which target title family does this job title belong to?",
            "criteria": criteria,
        }
    }
    result = _agent.predict({"title": title}, questions)
    answer = result["answers"]["title_family"]
    choice = str(answer.get("choice", "other"))
    confidence = float(answer.get("confidence", 0.0))
    if choice == "other":
        return False, None, confidence
    # Map normalized key back to the original target label.
    for target in families:
        if family_key(target) == choice:
            return True, target, confidence
    return True, choice, confidence


def score(title: str, targets: list[str]) -> dict:
    started = time.perf_counter()
    title = (title or "").strip()
    targets = [t.strip() for t in (targets or []) if t and t.strip()]
    if not title or not targets:
        return {
            "match": False,
            "family": None,
            "confidence": 0.0,
            "engine": "none",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    engine = "substring"
    try:
        if _agent is not None:
            match, family, confidence = laya_score(title, targets)
            engine = "laya"
        else:
            raise RuntimeError(_agent_error or "laya unavailable")
    except Exception:
        match, family, confidence = substring_score(title, targets)
        engine = "substring"
    return {
        "match": bool(match) if engine == "substring" else bool(match and confidence >= MATCH_THRESHOLD),
        "family": family,
        "confidence": float(confidence),
        "engine": engine,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep logs terse; stdout via print below
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/health":
            self._send(200, {"status": "ok", "engine": _ENGINE, "model": MODEL_REPO})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/score":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:
            self._send(400, {"error": f"invalid JSON: {exc}"})
            return
        result = score(str(payload.get("title", "")), list(payload.get("targets", [])))
        print(f"[title-filter] title={payload.get('title')!r} -> {result}", flush=True)
        self._send(200, result)


if __name__ == "__main__":
    print(f"[title-filter] engine={_ENGINE} model={MODEL_REPO} port={PORT}", flush=True)
    if _agent_error:
        print(f"[title-filter] laya unavailable, substring fallback: {_agent_error}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
