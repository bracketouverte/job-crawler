import { compactObjectStrings, firstString, joinStrings } from "../normalizers.js";
import { CrawlContext, NormalizedJob, ProviderCrawler, SourceEntry, WorkdaySource } from "../types.js";

type WorkdayResponse = {
  jobPostings?: WorkdayJob[];
  total?: number;
};

type WorkdayJob = {
  title?: unknown;
  externalPath?: unknown;
  locationsText?: unknown;
  postedOn?: unknown;
  bulletFields?: unknown[];
  timeType?: unknown;
  jobFamily?: unknown;
  jobId?: unknown;
  id?: unknown;
};

const pageLimit = 20;
const maxPagesPerSource = 1000;

export const workdayCrawler: ProviderCrawler = {
  provider: "workday",
  async crawl(source: SourceEntry, context: CrawlContext): Promise<NormalizedJob[]> {
    const workday = source as WorkdaySource;
    const jobs: WorkdayJob[] = [];

    for (let offset = 0; offset < pageLimit * maxPagesPerSource; offset += pageLimit) {
      const page = await fetchPage(workday, offset, context);
      const postings = page.jobPostings ?? [];
      jobs.push(...postings);

      const total = typeof page.total === "number" ? page.total : undefined;
      if (context.maxJobsPerSource !== undefined && jobs.length >= context.maxJobsPerSource) {
        break;
      }
      if (postings.length < pageLimit || (total !== undefined && offset + postings.length >= total)) {
        break;
      }
    }

    const key = `${workday.tenant}/${workday.shard}/${workday.site}`;
    const jobsToReturn = context.maxJobsPerSource === undefined ? jobs : jobs.slice(0, context.maxJobsPerSource);
    return jobsToReturn.map((job) => normalizeWorkdayJob(workday, key, job, context.fetchedAt()));
  }
};

async function fetchPage(source: WorkdaySource, offset: number, context: CrawlContext): Promise<WorkdayResponse> {
  const url = `https://${source.tenant}.${source.shard}.myworkdayjobs.com/wday/cxs/${source.tenant}/${source.site}/jobs`;
  return context.http.postJson<WorkdayResponse>(url, {
    appliedFacets: {},
    limit: pageLimit,
    offset,
    searchText: ""
  });
}

export function normalizeWorkdayJob(
  source: WorkdaySource,
  sourceKey: string,
  job: WorkdayJob,
  fetchedAt: string
): NormalizedJob {
  const id = firstString(job.jobId, job.id, job.externalPath, job.title) ?? "unknown";
  const externalPath = firstString(job.externalPath);
  
  // Reconstruct full job URL with locale and site
  // API returns: /job/DUNDEE-GBR/Product-Manager_R1151951
  // Full URL needs: /en-US/{site}/job/Product-Manager_R1151951
  let jobUrl: string | null = null;
  if (externalPath !== null) {
    const match = externalPath.match(/^\/job\/[^/]*\/(.+)$/);
    const jobPath = match ? match[1] : externalPath.replace(/^\/job\//, "");
    jobUrl = `https://${source.tenant}.${source.shard}.myworkdayjobs.com/en-US/${source.site}/job/${jobPath}`;
  }
  
  return {
    provider: "workday",
    source_key: sourceKey,
    job_id: id,
    title: firstString(job.title),
    location: firstString(job.locationsText),
    employment_type: firstString(job.timeType, inferBullet(job.bulletFields, "time")),
    compensation: inferBullet(job.bulletFields, "pay"),
    department: firstString(job.jobFamily),
    office: null,
    language: null,
    updated_at: firstString(job.postedOn),
    job_url: jobUrl,
    fetched_at: fetchedAt
  };
}

function inferBullet(values: unknown, keyword: string): string | null {
  if (!Array.isArray(values)) {
    return compactObjectStrings(values);
  }

  const exact = values
    .map((value) => compactObjectStrings(value))
    .find((value) => value?.toLowerCase().includes(keyword));

  return exact ?? joinStrings(values.map((value) => compactObjectStrings(value)));
}
