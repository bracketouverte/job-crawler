import { decideTitleMatch, loadTargetTitles } from "./title-matcher.js";

export type WorkMode = "remote" | "hybrid" | "onsite";

export type LocationTypeEntry = {
  mode: WorkMode;
  region: string; // e.g. "US"
};

export type FilterableJob = {
  title?: string | null;
  location?: string | null;
  employment_type?: string | null;
  salary_min?: number | null;
  salary_max?: number | null;
};

export type FilterCriteria = {
  targets: string[];
  locationTypes: LocationTypeEntry[];
  metros: string[];
  salary: number | null;
};

export type FactorVerdict = "pass" | "fail" | "unknown";

export type JobFilterDecision = {
  proceed: boolean;
  failedFactor?: "title" | "location_type" | "metro" | "salary";
  reason?: string;
  family?: string | null;
  confidence?: number;
  engine?: string;
};

function normalize(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9+\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Parse JOB_LOCATION_TYPE, e.g. "remote_US, hybrid_US, onsite_US". */
export function parseLocationTypes(raw: string | undefined): LocationTypeEntry[] {
  if (!raw) return [];
  const entries: LocationTypeEntry[] = [];
  for (const part of raw.split(",")) {
    const cleaned = part.trim();
    if (!cleaned) continue;
    const sep = cleaned.lastIndexOf("_");
    if (sep === -1) continue;
    const modeRaw = cleaned.slice(0, sep).toLowerCase().replace(/[\s-]+/g, "");
    const region = cleaned.slice(sep + 1).trim().toUpperCase();
    const mode: WorkMode | null =
      modeRaw === "remote" ? "remote" : modeRaw === "hybrid" ? "hybrid" : modeRaw === "onsite" ? "onsite" : null;
    if (mode && region) entries.push({ mode, region });
  }
  return entries;
}

/** Parse JOB_LOCATION_METRO, e.g. "chicago, Los Angeles". */
export function parseMetros(raw: string | undefined): string[] {
  if (!raw) return [];
  return raw
    .split(",")
    .map((m) => normalize(m))
    .filter(Boolean);
}

/** Parse SALARY, e.g. "120000", "$120,000", "120k". Blank -> null (factor disabled). */
export function parseSalaryThreshold(raw: string | undefined): number | null {
  if (!raw) return null;
  const cleaned = raw.trim().replace(/[$,\s]/g, "").toLowerCase();
  if (!cleaned) return null;
  const match = cleaned.match(/^(\d+(?:\.\d+)?)(k)?$/);
  if (!match) return null;
  const value = parseFloat(match[1]!);
  if (!Number.isFinite(value)) return null;
  return match[2] ? Math.round(value * 1000) : value;
}

/** Detect work mode from location + employment-type text. Null when undeterminable. */
export function detectWorkMode(location: string | null | undefined, employmentType: string | null | undefined): WorkMode | null {
  const combined = `${location ?? ""} ${employmentType ?? ""}`.toLowerCase();
  if (!combined.trim()) return null;
  if (/\bremote\b/.test(combined)) return "remote";
  if (/\bhybrid\b/.test(combined)) return "hybrid";
  if (/\bonsite\b|\bon-site\b|\bin-office\b/.test(combined)) return "onsite";
  return null;
}

/** US-region check. Null when the location is missing (unknown). */
export function isUSLocation(location: string | null | undefined): boolean | null {
  if (!location?.trim()) return null;
  const text = location.toLowerCase();
  if (/\bunited states\b|\bu\.s\.a?\.?\b|\busa\b|\(us\)|\bus\b/.test(text)) return true;
  // "City, ST" pattern (e.g. "Austin, TX") strongly implies US.
  if (/,\s*[a-z]{2}\b/.test(text)) return true;
  return false;
}

export function decideLocationType(job: FilterableJob, types: LocationTypeEntry[]): FactorVerdict {
  if (types.length === 0) return "pass";
  const mode = detectWorkMode(job.location, job.employment_type);
  if (mode === null) return "unknown";
  for (const entry of types) {
    if (entry.mode !== mode) continue;
    if (entry.region === "US") {
      const us = isUSLocation(job.location);
      if (us === true) return "pass";
      if (us === null) return "unknown";
      continue; // known non-US -> try next entry
    }
    // Unknown region codes: match on mode only.
    return "pass";
  }
  return "fail";
}

export function decideMetro(job: FilterableJob, metros: string[]): FactorVerdict {
  if (metros.length === 0) return "pass";
  if (!job.location?.trim()) return "unknown";
  const norm = normalize(job.location);
  return metros.some((m) => m && norm.includes(m)) ? "pass" : "fail";
}

/**
 * Salary gate. Qualifies when the threshold is inside the job's
 * [salary_min, salary_max] range (open-ended bounds allowed).
 * Unknown salary data -> "unknown" (fail-open, proceeds to LLM).
 */
export function decideSalary(job: FilterableJob, threshold: number | null): FactorVerdict {
  if (threshold === null) return "pass";
  const min = typeof job.salary_min === "number" ? job.salary_min : null;
  const max = typeof job.salary_max === "number" ? job.salary_max : null;
  if (min === null && max === null) return "unknown";
  if (min !== null && threshold < min) return "fail";
  if (max !== null && threshold > max) return "fail";
  return "pass";
}

/**
 * Full pre-filter: title (via Laya sidecar + substring fallback) AND the
 * deterministic location/salary factors. Missing data is fail-open
 * ("unknown" proceeds to the LLM); only a definitive mismatch skips it.
 */
export async function decideJobFilters(
  job: FilterableJob,
  criteria: FilterCriteria,
  titleOptions?: { filterUrl?: string; minConfidence?: number; timeoutMs?: number },
): Promise<JobFilterDecision> {
  if (criteria.targets.length > 0) {
    const title = await decideTitleMatch(job.title, criteria.targets, titleOptions);
    if (!title.match) {
      return { proceed: false, failedFactor: "title", reason: title.reason, family: title.family, confidence: title.confidence, engine: title.engine };
    }
  }

  const locationType = decideLocationType(job, criteria.locationTypes);
  if (locationType === "fail") {
    return { proceed: false, failedFactor: "location_type", reason: "location-type-mismatch" };
  }

  const metro = decideMetro(job, criteria.metros);
  if (metro === "fail") {
    return { proceed: false, failedFactor: "metro", reason: "metro-mismatch" };
  }

  const salary = decideSalary(job, criteria.salary);
  if (salary === "fail") {
    return { proceed: false, failedFactor: "salary", reason: "salary-mismatch" };
  }

  return { proceed: true };
}

export async function loadFilterCriteria(env: {
  targetsRaw?: string;
  targetsPath?: string;
  locationTypesRaw?: string;
  metrosRaw?: string;
  salaryRaw?: string;
}): Promise<FilterCriteria> {
  return {
    targets: await loadTargetTitles(env.targetsRaw, env.targetsPath),
    locationTypes: parseLocationTypes(env.locationTypesRaw),
    metros: parseMetros(env.metrosRaw),
    salary: parseSalaryThreshold(env.salaryRaw),
  };
}
