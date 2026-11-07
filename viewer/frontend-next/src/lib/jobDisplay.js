/** @param {{ provider: string, source_key: string }} job */
export function companyName(job) {
  if (job.provider === "workday") {
    return job.source_key.split("/")[0] || job.source_key;
  }
  return job.source_key;
}

/**
 * @param {{ provider: string, source_key: string, job_id: string }} job
 * @returns {string}
 */
export function jobKey(job) {
  return `${job.provider}|${job.source_key}|${job.job_id}`;
}

/**
 * @param {string} key
 * @returns {{ provider: string, source_key: string, job_id: string }}
 */
export function parseJobKey(key) {
  const [provider, source_key, ...rest] = key.split("|");
  return { provider, source_key, job_id: rest.join("|") };
}

/**
 * @param {string | null | undefined} location
 * @param {string | null | undefined} employmentType
 * @returns {string}
 */
export function jobMode(location, employmentType) {
  const combined = `${location ?? ""} ${employmentType ?? ""}`.toLowerCase();
  if (/\bremote\b/.test(combined)) return "Remote";
  if (/\bhybrid\b/.test(combined)) return "Hybrid";
  if (/\bonsite\b|\bon-site\b|\bin-office\b|\boffice\b/.test(combined)) return "On-site";
  return (location ?? employmentType ?? "n/a").trim() || "n/a";
}

const UNITS = [
  ["year", 365 * 24 * 60 * 60 * 1000],
  ["month", 30 * 24 * 60 * 60 * 1000],
  ["week", 7 * 24 * 60 * 60 * 1000],
  ["day", 24 * 60 * 60 * 1000],
  ["hour", 60 * 60 * 1000],
  ["minute", 60 * 1000],
];

const relativeFormatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/**
 * @param {string | null | undefined} isoDate
 * @returns {string | null}
 */
export function formatRelativeTime(isoDate) {
  if (!isoDate) return null;
  const timestamp = new Date(isoDate).getTime();
  if (Number.isNaN(timestamp)) return null;
  const diffMs = timestamp - Date.now();
  for (const [unit, ms] of UNITS) {
    if (Math.abs(diffMs) >= ms) {
      return relativeFormatter.format(Math.round(diffMs / ms), /** @type {Intl.RelativeTimeFormatUnit} */ (unit));
    }
  }
  return relativeFormatter.format(0, "minute");
}

/**
 * @param {number | null | undefined} score5
 * @returns {number | null}
 */
export function scoreOutOf100(score5) {
  if (score5 === null || score5 === undefined || Number.isNaN(score5)) return null;
  return Math.round(score5 * 20);
}

/**
 * Concatenate job lists, keeping the first occurrence of each job key.
 * @param {Array<Array<{ provider: string, source_key: string, job_id: string }>>} lists
 */
export function mergeJobs(lists) {
  const seen = new Set();
  const merged = [];
  for (const list of lists) {
    for (const job of list) {
      const key = jobKey(job);
      if (!seen.has(key)) {
        seen.add(key);
        merged.push(job);
      }
    }
  }
  return merged;
}
