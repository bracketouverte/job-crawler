export const providers = [
  "ashby",
  "bamboohr",
  "greenhouse",
  "lever",
  "teamtailor",
  "workable",
  "workday",
] as const;

export type Provider = (typeof providers)[number];

export type IdentifierSource = {
  identifier: string;
};

export type WorkdaySource = {
  tenant: string;
  shard: string;
  site: string;
};

export type SourceEntry = IdentifierSource | WorkdaySource;

export type SourceFile = {
  provider: Provider;
  url_template?: string;
  companies: SourceEntry[];
};

export type NormalizedJob = {
  provider: Provider;
  source_key: string;
  job_id: string;
  title: string | null;
  location: string | null;
  employment_type: string | null;
  compensation: string | null;
  department: string | null;
  office: string | null;
  language: string | null;
  updated_at: string | null;
  posted_at: string | null;
  job_url: string | null;
  fetched_at: string;
};

export type CrawlFailure = {
  provider: Provider;
  source_key: string;
  status?: number;
  message: string;
};

export type SourceExclusion = {
  provider: Provider;
  source_key: string;
  reason?: string;
  last_http_status?: number;
  last_seen_at?: string;
};

export type ProviderStats = {
  sources: number;
  skipped: number;
  succeeded: number;
  failed: number;
  jobs: number;
};

export type CrawlReport = {
  started_at: string;
  ended_at: string;
  source_counts: Record<Provider, number>;
  skipped_sources: number;
  skipped_by_provider: Record<Provider, number>;
  providers: Record<Provider, ProviderStats>;
  total_jobs: number;
  failures: CrawlFailure[];
};

export type HttpClient = {
  getJson<T = unknown>(url: string, init?: RequestInit): Promise<T>;
  postJson<T = unknown>(url: string, body: unknown, init?: RequestInit): Promise<T>;
  getText(url: string, init?: RequestInit): Promise<string>;
};

export type CrawlContext = {
  http: HttpClient;
  fetchedAt: () => string;
  maxJobsPerSource?: number;
};

export type ProviderCrawler = {
  provider: Provider;
  crawl(source: SourceEntry, context: CrawlContext): Promise<NormalizedJob[]>;
};
