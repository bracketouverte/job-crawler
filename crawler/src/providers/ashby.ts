import { firstString } from "../normalizers.js";
import { CrawlContext, IdentifierSource, NormalizedJob, ProviderCrawler, SourceEntry } from "../types.js";

type AshbyResponse = {
  jobs?: AshbyJob[];
};

type AshbyJob = {
  id?: unknown;
  title?: unknown;
  location?: unknown;
  employmentType?: unknown;
  department?: unknown;
  team?: unknown;
  workplaceType?: unknown;
  publishedAt?: unknown;
  jobUrl?: unknown;
};

export const ashbyCrawler: ProviderCrawler = {
  provider: "ashby",
  async crawl(source: SourceEntry, context: CrawlContext): Promise<NormalizedJob[]> {
    const { identifier } = source as IdentifierSource;
    const response = await context.http.getJson<AshbyResponse>(
      `https://api.ashbyhq.com/posting-api/job-board/${encodeURIComponent(identifier)}`
    );

    const jobs = response.jobs ?? [];
    return jobs.map((job) => normalizeAshbyJob(identifier, job, context.fetchedAt()));
  }
};

export function normalizeAshbyJob(sourceKey: string, job: AshbyJob, fetchedAt: string): NormalizedJob {
  const id = firstString(job.id, job.title) ?? "unknown";
  return {
    provider: "ashby",
    source_key: sourceKey,
    job_id: id,
    title: firstString(job.title),
    location: firstString(job.location),
    employment_type: firstString(job.employmentType),
    compensation: null,
    department: firstString(job.department, job.team),
    office: firstString(job.workplaceType),
    language: null,
    updated_at: firstString(job.publishedAt),
    job_url: firstString(job.jobUrl) ?? `https://jobs.ashbyhq.com/${sourceKey}/${id}`,
    fetched_at: fetchedAt
  };
}
