import { firstString, joinStrings } from "../normalizers.js";
import { CrawlContext, IdentifierSource, NormalizedJob, ProviderCrawler, SourceEntry } from "../types.js";

type GreenhouseResponse = {
  jobs?: GreenhouseJob[];
};

type Named = {
  name?: unknown;
};

type GreenhouseJob = {
  id?: unknown;
  internal_job_id?: unknown;
  title?: unknown;
  updated_at?: unknown;
  location?: Named;
  absolute_url?: unknown;
  language?: unknown;
  departments?: Named[];
  offices?: Named[];
  metadata?: unknown;
  content?: unknown;
};

export const greenhouseCrawler: ProviderCrawler = {
  provider: "greenhouse",
  async crawl(source: SourceEntry, context: CrawlContext): Promise<NormalizedJob[]> {
    const { identifier } = source as IdentifierSource;
    const url = `https://boards-api.greenhouse.io/v1/boards/${encodeURIComponent(identifier)}/jobs?content=true`;
    const response = await context.http.getJson<GreenhouseResponse>(url);
    return (response.jobs ?? []).map((job) => normalizeGreenhouseJob(identifier, job, context.fetchedAt()));
  }
};

export function normalizeGreenhouseJob(sourceKey: string, job: GreenhouseJob, fetchedAt: string): NormalizedJob {
  const id = firstString(job.id, job.internal_job_id, job.title) ?? "unknown";
  return {
    provider: "greenhouse",
    source_key: sourceKey,
    job_id: id,
    title: firstString(job.title),
    location: firstString(job.location?.name),
    employment_type: null,
    compensation: extractCompensation(job),
    department: joinStrings(job.departments?.map((item) => item.name)),
    office: joinStrings(job.offices?.map((item) => item.name)),
    language: firstString(job.language),
    updated_at: firstString(job.updated_at),
    job_url: firstString(job.absolute_url),
    fetched_at: fetchedAt
  };
}

function extractCompensation(job: GreenhouseJob): string | null {
  const metadata = job.metadata;
  if (!metadata || typeof metadata !== "object") {
    return null;
  }

  const entries = Array.isArray(metadata) ? metadata : Object.values(metadata);
  const compensation = entries.find((entry) => {
    if (!entry || typeof entry !== "object") {
      return false;
    }
    const label = firstString((entry as Record<string, unknown>).name, (entry as Record<string, unknown>).label);
    return label?.toLowerCase().includes("compensation") || label?.toLowerCase().includes("salary");
  });

  if (!compensation || typeof compensation !== "object") {
    return null;
  }

  const record = compensation as Record<string, unknown>;
  return firstString(record.value, record.name);
}
