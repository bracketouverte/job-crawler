import { firstString } from "../normalizers.js";
import { CrawlContext, IdentifierSource, NormalizedJob, ProviderCrawler, SourceEntry } from "../types.js";

type BambooResponse = {
  result?: BambooJob[];
};

type BambooJob = {
  id?: unknown;
  jobOpeningName?: unknown;
  title?: unknown;
  location?: unknown;
  departmentLabel?: unknown;
  employmentStatus?: unknown;
  datePosted?: unknown;
};

export const bamboohrCrawler: ProviderCrawler = {
  provider: "bamboohr",
  async crawl(source: SourceEntry, context: CrawlContext): Promise<NormalizedJob[]> {
    const { identifier } = source as IdentifierSource;
    const url = `https://${identifier}.bamboohr.com/careers/list`;
    const response = await context.http.getJson<BambooResponse | BambooJob[]>(url, {
      headers: { Accept: "application/json" }
    });
    const jobs = Array.isArray(response) ? response : response.result ?? [];
    return jobs.map((job) => normalizeBambooJob(identifier, job, context.fetchedAt()));
  }
};

export function normalizeBambooJob(sourceKey: string, job: BambooJob, fetchedAt: string): NormalizedJob {
  const id = firstString(job.id, job.jobOpeningName, job.title) ?? "unknown";
  return {
    provider: "bamboohr",
    source_key: sourceKey,
    job_id: id,
    title: firstString(job.jobOpeningName, job.title),
    location: firstString(job.location),
    employment_type: firstString(job.employmentStatus),
    compensation: null,
    department: firstString(job.departmentLabel),
    office: null,
    language: null,
    updated_at: firstString(job.datePosted),
    posted_at: firstString(job.datePosted),
    job_url: `https://${sourceKey}.bamboohr.com/careers/${id}/detail`,
    fetched_at: fetchedAt
  };
}
