export interface RoleSummary {
  tldr?: string;
  domain?: string;
  [key: string]: unknown;
}

export interface Analysis {
  score_5?: number;
  pipeline?: string;
  role_summary?: RoleSummary;
  core_skills?: number;
  relevant_experience?: number;
  target_alignment?: number;
  seniority_fit?: number;
  workplace_fit?: number;
  requirements_coverage?: number;
  technical_tools_mentioned?: string[];
  gaps?: string[];
  blockers?: string[];
  standout_differentiator?: string;
  verdict?: string;
  [key: string]: unknown;
}

export interface PipelineEntry {
  analysis: Analysis | null;
  analyzed_at: string;
  run_id: string;
}

export interface Job {
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
  first_seen_at: string | null;
  last_seen_at: string | null;
  skill_tier?: string | null;
  employment_type_canonical?: string | null;
  lat?: number | null;
  lon?: number | null;
  parsed_jd?: string | null;
  analysis: Analysis | null;
  pipelines: Record<string, PipelineEntry>;
}

export function jobKey(job: Pick<Job, "provider" | "source_key" | "job_id">): string {
  return `${job.provider}|${job.source_key}|${job.job_id}`;
}

export interface JobsResponse {
  jobs: Job[];
  total: number;
  page: number;
  limit: number;
}

export interface JobsFilters {
  title?: string;
  myLoc?: string;
  remote?: "0" | "1";
  days?: string;
  company?: string;
  sources?: string;
  page?: number;
  limit?: number;
  favCompanies?: string;
  evaluated?: "1";
  score?: "none" | "4plus";
  inc?: string;
  exc?: string;
  tiers?: string;
  types?: string;
}

export type QueueTaskStatus = "todo" | "running" | "done" | "error" | "permanent_error" | "retrying";

export interface QueueSubtask {
  id: string;
  label: string;
  status: QueueTaskStatus;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
}

export interface QueueItem {
  id: string;
  job_key: string;
  title: string;
  company: string;
  mode: string;
  status: QueueTaskStatus;
  subtasks: QueueSubtask[];
  attempt: number;
  max_attempts: number;
  next_retry_at: string | null;
  created_at: string;
  updated_at: string;
  error: string | null;
  score: number | null;
}

export type MatchRunStatus = "pending" | "running" | "completed" | "failed";

export interface MatchRunManifest {
  id: string;
  status: MatchRunStatus;
  mode: string;
  job_count: number;
  parsed_count: number;
  matched_count: number;
  created_at: string;
  updated_at: string;
  error: string | null;
  is_active?: boolean;
}

export interface MatchRunResult {
  status: "ok" | "error";
  provider: string;
  source_key: string;
  job_id: string;
  analysis?: Analysis;
  error?: string;
}

export interface Config {
  ensembleScorers: string[];
  ensembleSynthesizer: string;
  logoDevPublishableKey: string | null;
  scoreNotifyMinScore: number;
  userLocation: string | null;
  savedSearchAnalyzerEnabled: boolean;
}

export interface CrawlStatus {
  active: boolean;
  progress: Record<string, unknown> | null;
  next_run: string;
}

export interface AutoAnalyzerCurrent {
  run_id: string;
  job_key: string;
  search_id: string | null;
  search_label: string | null;
  started_at: string;
}

export interface AutoAnalyzerState {
  enabled: boolean;
  paused: boolean;
  busy: boolean;
  current: AutoAnalyzerCurrent | null;
}

export interface HiddenJobsResponse {
  hidden: string[];
}

export interface SavedSearch {
  id: string;
  label: string;
  title?: string;
  location?: string;
  company?: string;
  sources?: string[];
  days?: string;
}
