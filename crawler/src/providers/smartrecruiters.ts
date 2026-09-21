import { firstString, joinStrings } from "../normalizers.js";
import { CrawlContext, IdentifierSource, NormalizedJob, ProviderCrawler, SourceEntry } from "../types.js";

type SmartRecruitersResponse = {
  content?: SmartRecruitersPosting[];
  totalFound?: unknown;
  limit?: unknown;
  offset?: unknown;
};

type Labeled = {
  label?: unknown;
};

type SmartRecruitersLocation = {
  city?: unknown;
  region?: unknown;
  country?: unknown;
  fullLocation?: unknown;
  remote?: unknown;
  hybrid?: unknown;
};

type SmartRecruitersPosting = {
  id?: unknown;
  name?: unknown;
  ref?: unknown;
  releasedDate?: unknown;
  createdOn?: unknown;
  location?: SmartRecruitersLocation;
  department?: Labeled;
  function?: Labeled;
  typeOfEmployment?: Labeled;
  experienceLevel?: Labeled;
  language?: {
    code?: unknown;
  };
};

const PAGE_LIMIT = 100;

export const smartrecruitersCrawler: ProviderCrawler = {
  provider: "smartrecruiters",
  async crawl(source: SourceEntry, context: CrawlContext): Promise<NormalizedJob[]> {
    const { identifier } = source as IdentifierSource;
    const fetchedAt = context.fetchedAt();
    const jobs: NormalizedJob[] = [];
    let offset = 0;

    while (true) {
      const url = `https://api.smartrecruiters.com/v1/companies/${encodeURIComponent(identifier)}/postings?limit=${PAGE_LIMIT}&offset=${offset}`;
      const response = await context.http.getJson<SmartRecruitersResponse>(url);
      const postings = response.content ?? [];
      for (const posting of postings) {
        jobs.push(normalizeSmartrecruitersJob(identifier, posting, fetchedAt));
        if (context.maxJobsPerSource !== undefined && jobs.length >= context.maxJobsPerSource) {
          return jobs;
        }
      }

      const total = typeof response.totalFound === "number" ? response.totalFound : undefined;
      offset += postings.length;
      // Stop when the page is short or we've covered the reported total.
      if (postings.length < PAGE_LIMIT) {
        return jobs;
      }
      if (total !== undefined && offset >= total) {
        return jobs;
      }
    }
  }
};

export function normalizeSmartrecruitersJob(sourceKey: string, posting: SmartRecruitersPosting, fetchedAt: string): NormalizedJob {
  const id = firstString(posting.id, posting.ref, posting.name) ?? "unknown";
  return {
    provider: "smartrecruiters",
    source_key: sourceKey,
    job_id: id,
    title: firstString(posting.name),
    location: formatLocation(posting.location),
    employment_type: firstString(posting.typeOfEmployment?.label),
    compensation: null,
    salary_min: null,
    salary_max: null,
    salary_currency: null,
    salary_period: null,
    salary_location: null,
    salary_is_estimated: false,
    work_mode: workMode(posting.location),
    department: firstString(posting.department?.label, posting.function?.label),
    office: officeType(posting.location),
    language: firstString(posting.language?.code),
    updated_at: firstString(posting.releasedDate, posting.createdOn),
    posted_at: firstString(posting.releasedDate, posting.createdOn),
    job_url: firstString(
      `https://jobs.smartrecruiters.com/${sourceKey}/${id}`,
      posting.ref
    ),
    fetched_at: fetchedAt
  };
}

function formatLocation(location: SmartRecruitersLocation | undefined): string | null {
  if (!location) {
    return null;
  }
  return firstString(
    location.fullLocation,
    joinStrings([location.city, location.region, location.country])
  );
}

function officeType(location: SmartRecruitersLocation | undefined): string | null {
  if (location?.remote === true) {
    return "Remote";
  }
  if (location?.hybrid === true) {
    return "Hybrid";
  }
  return null;
}

function workMode(location: SmartRecruitersLocation | undefined): NormalizedJob["work_mode"] {
  if (location?.remote === true) {
    return "remote";
  }
  if (location?.hybrid === true) {
    return "hybrid";
  }
  return null;
}
