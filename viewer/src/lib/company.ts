import type { JobRow } from "./types.js";
import {
  LOGO_DEV_PUBLISHABLE_KEY,
  LOGO_CACHE_MAX,
  logoDevBrandCache,
} from "./config.js";

export function companyName(job: Pick<JobRow, "provider" | "source_key">): string {
  if (job.provider === "workday") return job.source_key.split("/")[0] ?? job.source_key;
  return job.source_key;
}

export function normalizeLabel(value: string | null | undefined): string {
  return String(value ?? "").trim().replace(/\s+/g, " ");
}

export function jobMode(location: string | null | undefined, employmentType: string | null | undefined): string {
  const normalizedLocation = normalizeLabel(location);
  const normalizedEmploymentType = normalizeLabel(employmentType);
  const combined = `${normalizedLocation} ${normalizedEmploymentType}`.toLowerCase();

  if (/\bremote\b/.test(combined)) return "Remote";
  if (/\bhybrid\b/.test(combined)) return "Hybrid";
  if (/\bonsite\b|\bon-site\b|\bin-office\b|\boffice\b/.test(combined)) return "On-site";

  return normalizedLocation || normalizedEmploymentType || "n/a";
}

export function jobCompensation(compensation: string | null | undefined): string {
  return normalizeLabel(compensation) || "n/a";
}

export function decisionEmoji(score: number): string {
  if (score >= 4.75) return "🌟 Top pick";
  if (score >= 4.5) return "🎯 Strong match";
  if (score > 4.2) return "⚡ Quick apply";
  return "✅ Worth applying";
}

export function companyLogoUrl(company: string): string | null {
  if (!LOGO_DEV_PUBLISHABLE_KEY) {
    return null;
  }

  const normalizedCompany = normalizeLabel(company);
  if (!normalizedCompany) {
    return null;
  }

  const cachedDomain = logoDevBrandCache.get(normalizedCompany.toLowerCase());
  if (cachedDomain) {
    return `https://img.logo.dev/${encodeURIComponent(cachedDomain)}?token=${encodeURIComponent(LOGO_DEV_PUBLISHABLE_KEY)}&size=64&format=png&fallback=404`;
  }

  return `https://img.logo.dev/name/${encodeURIComponent(normalizedCompany)}?token=${encodeURIComponent(LOGO_DEV_PUBLISHABLE_KEY)}&size=64&format=png&fallback=404`;
}

export function companyWebsite(company: string): string | null {
  const normalizedCompany = normalizeLabel(company);
  if (!normalizedCompany) {
    return null;
  }

  const cachedDomain = logoDevBrandCache.get(normalizedCompany.toLowerCase());
  if (cachedDomain) {
    return `https://${cachedDomain}`;
  }

  return null;
}

export function logoCacheSet(key: string, value: string | null): void {
  if (logoDevBrandCache.size >= LOGO_CACHE_MAX) {
    logoDevBrandCache.delete(logoDevBrandCache.keys().next().value!);
  }
  logoDevBrandCache.set(key, value);
}
