import { firstString, joinStrings } from "../normalizers.js";
import { CrawlContext, IdentifierSource, NormalizedJob, ProviderCrawler, SourceEntry } from "../types.js";

type SmartRecruitersResponse = {
  content?: SmartRecruitersJob[];
  jobs?: SmartRecruitersJob[];
  postings?: SmartRecruitersJob[];
  offset?: unknown;
  limit?: unknown;
  totalFound?: unknown;
};

type Label = {
  label?: unknown;
  name?: unknown;
};

type SmartRecruitersLocation = {
  city?: unknown;
  region?: unknown;
  country?: unknown;
  remote?: unknown;
};

type SmartRecruitersJob = {
  id?: unknown;
  uuid?: unknown;
  jobId?: unknown;
  refNumber?: unknown;
  name?: unknown;
  title?: unknown;
  location?: SmartRecruitersLocation;
  typeOfEmployment?: Label;
  department?: Label;
  function?: Label;
  industry?: Label;
  language?: unknown;
  releasedDate?: unknown;
  updatedDate?: unknown;
  createdOn?: unknown;
  postingUrl?: unknown;
  applyUrl?: unknown;
  ref?: unknown;
};

const defaultUrlTemplate = "https://api.smartrecruiters.com/v1/companies/{identifier}/postings/";
const defaultJobIdTemplate = "https://jobs.smartrecruiters.com/{identifier}/{job_id}";

export const smartrecruitersCrawler: ProviderCrawler = {
  provider: "smartrecruiters",
  async crawl(source: SourceEntry, context: CrawlContext): Promise<NormalizedJob[]> {
    const { identifier } = source as IdentifierSource;
    const urlTemplate = context.urlTemplate ?? defaultUrlTemplate;
    const jobIdTemplate = context.jobIdTemplate ?? defaultJobIdTemplate;
    const fetchedAt = context.fetchedAt();
    const jobs = await fetchSmartRecruitersJobs(identifier, urlTemplate, context);

    return jobs.map((job) => normalizeSmartRecruitersJob(identifier, job, fetchedAt, jobIdTemplate));
  }
};

export async function fetchSmartRecruitersJobs(
  identifier: string,
  urlTemplate: string,
  context: CrawlContext
): Promise<SmartRecruitersJob[]> {
  const jobs: SmartRecruitersJob[] = [];
  let offset = 0;
  const pageSize = 100;

  while (true) {
    const url = withPaging(renderTemplate(urlTemplate, { identifier }), offset, pageSize);
    const response = await context.http.getJson<SmartRecruitersResponse | SmartRecruitersJob[]>(url);
    const page = extractJobs(response);
    jobs.push(...page);

    if (context.maxJobsPerSource !== undefined && jobs.length >= context.maxJobsPerSource) {
      return jobs.slice(0, context.maxJobsPerSource);
    }

    if (!shouldFetchNextPage(response, page.length, offset, pageSize)) {
      return jobs;
    }

    offset += pageSize;
  }
}

export function normalizeSmartRecruitersJob(
  sourceKey: string,
  job: SmartRecruitersJob,
  fetchedAt: string,
  jobIdTemplate = defaultJobIdTemplate
): NormalizedJob {
  const id = firstString(job.id, job.uuid, job.jobId, job.refNumber, job.ref, job.name, job.title) ?? "unknown";
  const postedAt = firstString(job.releasedDate, job.createdOn);

  return {
    provider: "smartrecruiters",
    source_key: sourceKey,
    job_id: id,
    title: firstString(job.name, job.title),
    location: formatLocation(job.location),
    employment_type: firstString(job.typeOfEmployment?.label, job.typeOfEmployment?.name),
    compensation: null,
    department: firstString(job.department?.label, job.department?.name, job.function?.label, job.function?.name),
    office: job.location?.remote === true ? "Remote" : null,
    language: firstString(job.language),
    updated_at: firstString(job.updatedDate, postedAt),
    posted_at: postedAt,
    job_url: firstString(job.postingUrl, job.applyUrl) ?? renderTemplate(jobIdTemplate, { identifier: sourceKey, job_id: id, id }),
    fetched_at: fetchedAt
  };
}

function extractJobs(response: SmartRecruitersResponse | SmartRecruitersJob[]): SmartRecruitersJob[] {
  if (Array.isArray(response)) {
    return response;
  }

  return response.content ?? response.jobs ?? response.postings ?? [];
}

function shouldFetchNextPage(
  response: SmartRecruitersResponse | SmartRecruitersJob[],
  pageLength: number,
  offset: number,
  pageSize: number
): boolean {
  if (Array.isArray(response)) {
    return false;
  }

  const totalFound = typeof response.totalFound === "number" ? response.totalFound : undefined;
  if (totalFound !== undefined) {
    return offset + pageLength < totalFound;
  }

  return pageLength === pageSize;
}

function renderTemplate(template: string, values: Record<string, string>): string {
  return template.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, key: string) => {
    const value = values[key];
    return value === undefined ? match : encodeURIComponent(value);
  });
}

function withPaging(url: string, offset: number, limit: number): string {
  const parsed = new URL(url);
  if (!parsed.searchParams.has("offset")) {
    parsed.searchParams.set("offset", String(offset));
  }
  if (!parsed.searchParams.has("limit")) {
    parsed.searchParams.set("limit", String(limit));
  }
  return parsed.toString();
}

function formatLocation(location: SmartRecruitersLocation | undefined): string | null {
  if (location === undefined) {
    return null;
  }

  return joinStrings([location.city, location.region, location.country]);
}
