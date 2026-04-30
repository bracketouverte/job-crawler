import { firstString, joinStrings } from "../normalizers.js";
import { CrawlContext, IdentifierSource, NormalizedJob, ProviderCrawler, SourceEntry } from "../types.js";

type LeverJob = {
  id?: unknown;
  text?: unknown;
  hostedUrl?: unknown;
  applyUrl?: unknown;
  categories?: {
    location?: unknown;
    team?: unknown;
    commitment?: unknown;
    department?: unknown;
  };
  lists?: unknown;
  workplaceType?: unknown;
  createdAt?: unknown;
};

export const leverCrawler: ProviderCrawler = {
  provider: "lever",
  async crawl(source: SourceEntry, context: CrawlContext): Promise<NormalizedJob[]> {
    const { identifier } = source as IdentifierSource;
    const url = `https://api.lever.co/v0/postings/${encodeURIComponent(identifier)}?mode=json`;
    const jobs = await context.http.getJson<LeverJob[]>(url);
    return jobs.map((job) => normalizeLeverJob(identifier, job, context.fetchedAt()));
  }
};

export function normalizeLeverJob(sourceKey: string, job: LeverJob, fetchedAt: string): NormalizedJob {
  const id = firstString(job.id, job.hostedUrl, job.text) ?? "unknown";
  return {
    provider: "lever",
    source_key: sourceKey,
    job_id: id,
    title: firstString(job.text),
    location: firstString(job.categories?.location),
    employment_type: firstString(job.categories?.commitment),
    compensation: null,
    department: firstString(job.categories?.team, job.categories?.department),
    office: firstString(job.workplaceType),
    language: null,
    // Lever only exposes createdAt — no updatedAt field exists in their API
    updated_at: typeof job.createdAt === "number" ? new Date(job.createdAt).toISOString() : null,
    posted_at: typeof job.createdAt === "number" ? new Date(job.createdAt).toISOString() : null,
    job_url: firstString(job.hostedUrl, job.applyUrl),
    fetched_at: fetchedAt
  };
}
