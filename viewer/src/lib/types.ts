export type JobRow = {
  provider: string;
  source_key: string;
  job_id: string;
  title: string | null;
  location: string | null;
  employment_type: string | null;
  compensation: string | null;
  department: string | null;
  job_url: string | null;
  updated_at: string | null;
  posted_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
  analysis?: unknown;
};

export type SinglePipelineResult = {
  analysis: unknown;
  analyzed_at: string;
  run_id: string;
};

export type CachedJobAnalysis = {
  pipelines: Record<string, SinglePipelineResult>;
  // keep old fields for backward compat read
  analysis?: unknown;
  analyzed_at?: string;
  run_id?: string;
};

export type AnalysisCache = Record<string, CachedJobAnalysis>;

export type HiddenJobsState = {
  hidden: string[];
  updated_at: string;
};

export type ScoreNotificationsState = {
  sent: Record<string, { score_5: number; notified_at: string; run_id: string }>;
};

export type TitleTokenGroup = {
  terms: string[];
  exclude: boolean;
};

export type StatsRow = {
  provider: string;
  count: number;
};

export type MatchJobKey = {
  provider: string;
  source_key: string;
  job_id: string;
};

export type CartJobPayload = MatchJobKey & {
  title?: string | null;
  company?: string | null;
  location?: string | null;
  job_url?: string | null;
};

export type MatchRunManifest = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  job_count: number;
  parsed_count: number;
  matched_count: number;
  failed_count: number;
  jobs: CartJobPayload[];
  error: string | null;
  result_file: string | null;
  log_file: string | null;
};

export type ParsedJobPost = {
  title?: string | null;
  jd_concepts?: string[];
  posted_datetime?: string | null;
  location?: string | null;
  compensation?: string | null;
  workplace_type?: string | null;
  employment_type?: string | null;
  responsibilities?: string[];
  requirements_summary?: string[];
  must_have_requirements?: string[];
  nice_to_have_requirements?: string[];
  technical_tools_mentioned?: string[];
  url?: string | null;
  provider?: string | null;
};

export type SavedSearch = {
  id?: string;
  label?: string;
  title?: string;
  location?: string;
  company?: string;
  days?: string | number;
  sources?: string[];
};

export type RunCommandOptions = {
  cwd?: string;
  env?: NodeJS.ProcessEnv;
  logPrefix?: string;
  logFile?: string;
  logStdout?: boolean;
  logStderr?: boolean;
};
