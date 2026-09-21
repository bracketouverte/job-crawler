import { readFile } from "node:fs/promises";

export type TitleDecision = {
  match: boolean;
  reason: "laya-match" | "laya-mismatch" | "laya-uncertain" | "substring-match" | "substring-mismatch" | "filter-unavailable" | "no-targets" | "no-title";
  family?: string | null;
  confidence?: number;
  engine?: string;
};

/** Normalize for cheap comparison: lowercase, drop punctuation/seniority noise. */
export function normalizeJobTitle(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9+\s]/g, " ")
    .replace(/\b(senior|sr|staff|principal|lead|junior|jr|i{1,3}|iv|v)\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function substringTitleMatch(title: string | null | undefined, targets: string[]): boolean {
  if (!title) return false;
  const norm = normalizeJobTitle(title);
  if (!norm) return false;
  return targets.some((t) => {
    const key = normalizeJobTitle(t);
    return key.length > 0 && norm.includes(key);
  });
}

export function parseTargetTitles(raw: string | undefined): string[] {
  if (!raw) return [];
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

export async function loadTargetTitles(envRaw: string | undefined, filePath: string | undefined): Promise<string[]> {
  const fromEnv = parseTargetTitles(envRaw);
  if (fromEnv.length > 0) return fromEnv;
  if (!filePath) return [];
  try {
    const raw = await readFile(filePath, "utf8");
    const parsed: unknown = JSON.parse(raw);
    const list = Array.isArray(parsed) ? parsed : (parsed as { targets?: unknown }).targets;
    if (!Array.isArray(list)) return [];
    return list.filter((t): t is string => typeof t === "string" && t.trim() !== "").map((t) => t.trim());
  } catch {
    return [];
  }
}

async function fetchWithTimeout(url: string, body: unknown, timeoutMs: number): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`title-filter HTTP ${res.status}`);
    return (await res.json()) as unknown;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Decide whether a job title matches the target list.
 * - Laya sidecar high-confidence mismatch -> skip LLM.
 * - Match, low confidence, no targets/title, or sidecar down -> proceed (caller falls back to LLM).
 */
export async function decideTitleMatch(
  title: string | null | undefined,
  targets: string[],
  options?: { filterUrl?: string; minConfidence?: number; timeoutMs?: number },
): Promise<TitleDecision> {
  if (targets.length === 0) return { match: true, reason: "no-targets" };
  if (!title?.trim()) return { match: true, reason: "no-title" };

  const filterUrl = options?.filterUrl?.trim();
  const minConfidence = options?.minConfidence ?? 0.85;

  if (filterUrl) {
    try {
      const raw = (await fetchWithTimeout(filterUrl, { title, targets }, options?.timeoutMs ?? 2000)) as {
        match?: boolean;
        family?: string | null;
        confidence?: number;
        engine?: string;
      };
      const confidence = Number(raw.confidence ?? 0);
      if (raw.engine === "laya") {
        if (raw.match) return { match: true, reason: "laya-match", family: raw.family ?? null, confidence, engine: "laya" };
        if (Number.isFinite(confidence) && confidence >= minConfidence) {
          return { match: false, reason: "laya-mismatch", confidence, engine: "laya" };
        }
        return { match: true, reason: "laya-uncertain", confidence, engine: "laya" };
      }
      // sidecar substring fallback result
      if (raw.match) return { match: true, reason: "substring-match", family: raw.family ?? null, confidence, engine: raw.engine ?? "substring" };
      return { match: false, reason: "substring-mismatch", confidence, engine: raw.engine ?? "substring" };
    } catch {
      // fall through to local substring so a down sidecar never blocks analysis
    }
  }

  return substringTitleMatch(title, targets)
    ? { match: true, reason: "substring-match", engine: "local" }
    : { match: false, reason: "substring-mismatch", engine: "local" };
}
