import { firstString, joinStrings } from "../normalizers.js";
import { CrawlContext, IdentifierSource, NormalizedJob, ProviderCrawler, SourceEntry } from "../types.js";

type WorkableResponse = {
  jobs?: WorkableJob[];
};

type WorkableLocation = {
  country?: unknown;
  city?: unknown;
  region?: unknown;
  hidden?: unknown;
};

type WorkableJob = {
  title?: unknown;
  shortcode?: unknown;
  code?: unknown;
  employment_type?: unknown;
  telecommuting?: unknown;
  department?: unknown;
  function?: unknown;
  url?: unknown;
  shortlink?: unknown;
  application_url?: unknown;
  published_on?: unknown;
  created_at?: unknown;
  country?: unknown;
  city?: unknown;
  state?: unknown;
  locations?: WorkableLocation[];
};

export const workableCrawler: ProviderCrawler = {
  provider: "workable",
  async crawl(source: SourceEntry, context: CrawlContext): Promise<NormalizedJob[]> {
    const { identifier } = source as IdentifierSource;
    const url = `https://apply.workable.com/api/v1/widget/accounts/${encodeURIComponent(identifier)}`;
    const response = await context.http.getJson<WorkableResponse>(url);
    return (response.jobs ?? []).map((job) => normalizeWorkableJob(identifier, job, context.fetchedAt()));
  }
};

export function normalizeWorkableJob(sourceKey: string, job: WorkableJob, fetchedAt: string): NormalizedJob {
  const id = firstString(job.shortcode, job.code, job.url, job.title) ?? "unknown";
  return {
    provider: "workable",
    source_key: sourceKey,
    job_id: id,
    title: firstString(job.title),
    location: firstString(formatLocations(job.locations), formatLocation(job.city, job.state, job.country)),
    employment_type: firstString(job.employment_type),
    compensation: null,
    department: firstString(job.department, job.function),
    office: officeType(job.telecommuting),
    language: null,
    updated_at: firstString(job.published_on, job.created_at),
    posted_at: firstString(job.published_on, job.created_at),
    job_url: firstString(job.url, job.shortlink, job.application_url),
    fetched_at: fetchedAt
  };
}

function formatLocations(locations: WorkableJob["locations"]): string | null {
  if (!Array.isArray(locations)) {
    return null;
  }

  const visible = locations
    .filter((location) => location && typeof location === "object" && location.hidden !== true)
    .map((location) => formatLocation(location.city, location.region, location.country))
    .filter((location): location is string => location !== null);

  return joinStrings(visible, " | ");
}

function formatLocation(city: unknown, region: unknown, country: unknown): string | null {
  const parts = [firstString(city), firstString(region), firstString(country)].filter((part): part is string => part !== null);
  return parts.length > 0 ? parts.join(", ") : null;
}

function officeType(telecommuting: unknown): string | null {
  return telecommuting === true ? "Remote" : null;
}
