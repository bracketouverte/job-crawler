import { NormalizedJob } from "./types.js";

const CURRENCY_SYMBOL_TO_CODE: Record<string, string> = {
  "$": "USD",
  "€": "EUR",
  "£": "GBP",
  "¥": "JPY",
};

function parseAmount(raw: string): number {
  const cleaned = raw.trim().replace(/,/g, "").replace(/ /g, "").replace(/^[$€£]+/, "");
  if (cleaned.toLowerCase().endsWith("k")) {
    return parseFloat(cleaned.slice(0, -1)) * 1_000;
  }
  return parseFloat(cleaned);
}

function detectPeriod(text: string): string {
  const lower = text.toLowerCase();
  if (/\b(per\s*hour|\/hr|hourly|\bhr\b)\b/.test(lower)) return "hourly";
  if (/\b(per\s*month|monthly)\b/.test(lower)) return "monthly";
  if (/\b(per\s*week|weekly)\b/.test(lower)) return "weekly";
  return "annual";
}

function isEstimated(text: string): boolean {
  return /\b(estimated|approximate|around|about|typically|target\s*pay)\b/i.test(text);
}

type SalaryResult = {
  min: number | null;
  max: number | null;
  currency: string | null;
  period: string | null;
  location: string | null;
  isEstimated: boolean;
  rawText: string | null;
};

export function extractCompensation(text: string | null | undefined): SalaryResult {
  if (!text || text.length < 20) {
    return { min: null, max: null, currency: null, period: null, location: null, isEstimated: false, rawText: null };
  }

  const locationPayPattern = /(?:based\s+in|located\s+in|for\s+(?:candidates\s+)?in|work\s+from)\s+([^:\n]+?)\s*[:\.]\s*([\$€£])\s?(\d{2,3}(?:[,\s]\d{3}|[kK]))\s*(?:-|–|to|—)\s*([\$€£]?)\s?(\d{2,3}(?:[,\s]\d{3}|[kK]))/i;
  const rangePattern = /([\$€£])\s?(\d{2,3}(?:[,\s]\d{3}|[kK]))\s*(?:-|–|to|—)\s*([\$€£]?)\s?(\d{2,3}(?:[,\s]\d{3}|[kK]))/i;
  const singlePattern = /([\$€£])\s?(\d{2,3}(?:[,\s]\d{3}|[kK]))\b/i;
  const hourlyPattern = /([\$€£])\s?(\d{1,3}(?:\.\d{1,2})?)\s*(?:\/hr|per\s*hour|hourly)/i;

  let match: RegExpMatchArray | null;
  let result: SalaryResult;

  match = text.match(locationPayPattern);
  if (match) {
    const location = match[1]!.trim();
    const currency = CURRENCY_SYMBOL_TO_CODE[match[2]!] || "USD";
    const min = parseAmount(match[3]!);
    const max = parseAmount(match[5]!);
    const raw = match[0]!.trim();
    if (min < 5_000_000 && max < 5_000_000 && min >= 1_000) {
      result = {
        min,
        max: max >= min ? max : min,
        currency,
        period: detectPeriod(raw),
        location: location.length > 2 ? location : null,
        isEstimated: isEstimated(raw),
        rawText: raw,
      };
      return result;
    }
  }

  match = text.match(rangePattern);
  if (match) {
    const currency = CURRENCY_SYMBOL_TO_CODE[match[1]!] || "USD";
    const min = parseAmount(match[2]!);
    const max = parseAmount(match[4]!);
    const raw = match[0]!.trim();
    if (min < 5_000_000 && max < 5_000_000 && min >= 1_000) {
      result = {
        min,
        max: max >= min ? max : min,
        currency,
        period: detectPeriod(raw),
        location: null,
        isEstimated: isEstimated(raw),
        rawText: raw,
      };
      return result;
    }
  }

  match = text.match(hourlyPattern);
  if (match) {
    const currency = CURRENCY_SYMBOL_TO_CODE[match[1]!] || "USD";
    const hourly = parseFloat(match[2]!);
    const raw = match[0]!.trim();
    if (hourly >= 10 && hourly <= 500) {
      result = {
        min: hourly,
        max: hourly,
        currency,
        period: "hourly",
        location: null,
        isEstimated: isEstimated(raw),
        rawText: raw,
      };
      return result;
    }
  }

  match = text.match(singlePattern);
  if (match) {
    const currency = CURRENCY_SYMBOL_TO_CODE[match[1]!] || "USD";
    const amount = parseAmount(match[2]!);
    const raw = match[0]!.trim();
    if (amount < 5_000_000 && amount >= 1_000) {
      result = {
        min: amount,
        max: amount,
        currency,
        period: detectPeriod(raw),
        location: null,
        isEstimated: isEstimated(raw),
        rawText: raw,
      };
      return result;
    }
  }

  return { min: null, max: null, currency: null, period: null, location: null, isEstimated: false, rawText: null };
}

export function detectWorkMode(text: string | null | undefined): "remote" | "hybrid" | "onsite" | null {
  if (!text || text.length < 10) {
    return null;
  }
  const lower = text.toLowerCase();

  const remotePatterns = [
    /\bremote\b/,
    /\bwork\s*from\s*home\b/,
    /\bwfh\b/,
    /\btelecommut/i,
    /\bfully\s*remote\b/,
    /\b100\s*%\s*remote\b/,
  ];
  for (const pattern of remotePatterns) {
    if (pattern.test(lower)) return "remote";
  }

  const hybridPatterns = [
    /\bhybrid\b/,
    /\bmixed\s*location\b/,
    /\bflexible\s*location\b/,
    /\bpartially\s*remote\b/,
    /\bremote\s*-?\s*hybrid\b/,
    /\bhybrid\s*-?\s*remote\b/,
  ];
  for (const pattern of hybridPatterns) {
    if (pattern.test(lower)) return "hybrid";
  }

  const onsitePatterns = [
    /\bonsite\b/,
    /\bon-site\b/,
    /\bin\s*office\b/,
    /\bon\s*premises\b/,
  ];
  for (const pattern of onsitePatterns) {
    if (pattern.test(lower)) return "onsite";
  }

  return null;
}

export function applySalaryToJob(job: NormalizedJob, salary: SalaryResult): NormalizedJob {
  return {
    ...job,
    salary_min: salary.min,
    salary_max: salary.max,
    salary_currency: salary.currency,
    salary_period: salary.period,
    salary_location: salary.location,
    salary_is_estimated: salary.isEstimated,
  };
}
