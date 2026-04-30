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
  
  const postedOn = firstString(job.postedOn);

  return {
    provider: "workday",
    source_key: sourceKey,
    job_id: id,
    title: firstString(job.title),
    location: firstString(job.locationsText),
    employment_type: firstString(job.timeType, inferBullet(job.bulletFields, "time")),
    compensation: inferCompensation(job.bulletFields),
    department: firstString(job.jobFamily),
    office: null,
    language: null,
    updated_at: postedOn,
    posted_at: parseWorkdayPostedAt(postedOn, fetchedAt),
    job_url: jobUrl,
    fetched_at: fetchedAt
  };
}

export function parseWorkdayPostedAt(value: string | null, fetchedAt: string): string | null {
  if (value === null) {
    return null;
  }
  const text = value.trim();
  if (!text) {
    return null;
  }

  const fetchedMs = Date.parse(fetchedAt);
  if (Number.isNaN(fetchedMs)) {
    return null;
  }
  const fetchedDate = new Date(fetchedMs);
  const exactMs = Date.parse(text);
  if (!Number.isNaN(exactMs)) {
    return new Date(exactMs).toISOString();
  }
  if (/\btoday\b/i.test(text)) {
    return startOfUtcDay(fetchedDate).toISOString();
  }
  if (/\byesterday\b/i.test(text)) {
    return addUtcDays(startOfUtcDay(fetchedDate), -1).toISOString();
  }

  const relative = text.match(/posted\s+(\d+)\+?\s+(day|week|month|year)s?\s+ago/i);
  if (relative?.[1] && relative[2]) {
    const amount = Number(relative[1]);
    const unit = relative[2].toLowerCase();
    const days = unit === "year" ? amount * 365 : unit === "month" ? amount * 30 : unit === "week" ? amount * 7 : amount;
    return addUtcDays(startOfUtcDay(fetchedDate), -days).toISOString();
  }

  return null;
}

function startOfUtcDay(date: Date): Date {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
}

function addUtcDays(date: Date, days: number): Date {
  return new Date(date.getTime() + days * 86400000);
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

function inferCompensation(values: unknown): string | null {
  const value = inferBullet(values, "pay");
  if (value === null) {
    return null;
  }
  if (/^(req|r|jr|job)[-_]?\d+[a-z0-9-]*$/i.test(value)) {
    return null;
  }
  if (!/(salary|compensation|base pay|pay range|ote|equity|bonus|hour|annual|year|yr|[$€£]|\b\d{2,3}\s?k\b|\b\d{2,3}[,\s]\d{3}\b)/i.test(value)) {
    return null;
  }
  return value;
}
