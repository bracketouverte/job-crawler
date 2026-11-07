import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useBrandSearch, useMatchRun, useStartMatchRun } from "../api/hooks";
import { companyName, formatRelativeTime, jobMode } from "../lib/jobDisplay";
import { useLocalStore } from "../stores/localStore";
import { useToastStore } from "../stores/toastStore";
import { useUiStore } from "../stores/uiStore";
import type { Job } from "../types";
import { jobKey } from "../types";
import { JobCardAnalysis } from "./JobCardAnalysis";

interface Props {
  job: Job;
}

export function JobCard({ job }: Props) {
  const key = jobKey(job);
  const company = companyName(job);
  const [runId, setRunId] = useState<string | null>(null);

  const queryClient = useQueryClient();
  const startMatchRun = useStartMatchRun();
  const matchRun = useMatchRun(runId, runId !== null);
  const brand = useBrandSearch(company);

  const hiddenJobs = useLocalStore((s) => s.hiddenJobs);
  const hideJob = useLocalStore((s) => s.hideJob);
  const unhideJob = useLocalStore((s) => s.unhideJob);
  const addToast = useToastStore((s) => s.addToast);
  const visitedJobs = useLocalStore((s) => s.visitedJobs);
  const visitJob = useLocalStore((s) => s.visitJob);
  const favoriteCompanies = useLocalStore((s) => s.favoriteCompanies);
  const toggleFavoriteCompany = useLocalStore((s) => s.toggleFavoriteCompany);
  const setActivePanelJobKey = useUiStore((s) => s.setActivePanelJobKey);

  const isRunning = matchRun.data?.status === "pending" || matchRun.data?.status === "running";

  useEffect(() => {
    if (matchRun.data?.status === "completed" || matchRun.data?.status === "failed") {
      if (matchRun.data.status === "failed") {
        addToast({ message: `Analysis failed: ${matchRun.data.error || "unknown error"}`, kind: "error" });
      }
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      setRunId(null);
    } else if (matchRun.isError) {
      addToast({ message: "Lost track of the analysis run", kind: "error" });
      setRunId(null);
    }
  }, [matchRun.data?.status, matchRun.data?.error, matchRun.isError, queryClient, addToast]);

  if (hiddenJobs.has(key)) return null;

  const score5 = job.analysis?.score_5;
  const isFavorite = favoriteCompanies.has(company);
  const isVisited = visitedJobs.has(key);
  const compensation = job.compensation;
  const age = formatRelativeTime(job.posted_at ?? job.first_seen_at);

  const handleAnalyze = () => {
    startMatchRun.mutate(
      { job_keys: [key], mode: "claude" },
      { onSuccess: (data) => setRunId(data.run_id) },
    );
  };

  return (
    <article className="job-card" data-testid="job-card">
      <div className="job-card-main">
        {brand.data && (
          <img className="job-card-logo" src={`https://img.logo.dev/${brand.data}`} alt="" width={32} height={32} />
        )}
        <div className="job-card-body">
          <div className="job-card-title-row">
            <span className="job-card-company">{company}</span>
            <span className="pill job-card-provider">{job.provider}</span>
            {isVisited && <span className="job-card-visited">visited</span>}
          </div>
          <a
            className="job-card-title"
            href={job.job_url ?? undefined}
            target="_blank"
            rel="noreferrer"
            onClick={() => visitJob(key)}
          >
            {job.title ?? "Untitled role"}
          </a>
          <div className="job-card-meta">
            <span className="pill">{jobMode(job.location, job.employment_type)}</span>
            {job.location && <span>{job.location}</span>}
            {age && <span className="job-card-age">{age}</span>}
            {compensation && <span className="mono">{compensation}</span>}
          </div>
        </div>
        <div className="job-card-actions">
          <button
            type="button"
            className="job-card-star"
            aria-pressed={isFavorite}
            onClick={() => toggleFavoriteCompany(company)}
            title="Favorite company"
          >
            {isFavorite ? "★" : "☆"}
          </button>
          <button
            type="button"
            onClick={() => {
              hideJob(key);
              addToast({
                message: `Hid "${job.title ?? "job"}".`,
                kind: "neutral",
                undo: () => unhideJob(key),
              });
            }}
            title="Hide job"
          >
            Hide
          </button>
          <button
            type="button"
            className="btn-analyze"
            onClick={handleAnalyze}
            disabled={isRunning}
          >
            {isRunning ? "Analyzing…" : score5 !== undefined ? "Re-analyze" : "Analyze"}
          </button>
          {score5 !== undefined && (
            <button
              type="button"
              className="job-card-score-badge"
              onClick={() => setActivePanelJobKey(key)}
            >
              {score5.toFixed(1)}/5
            </button>
          )}
        </div>
      </div>
      {job.analysis && <JobCardAnalysis analysis={job.analysis} />}
    </article>
  );
}
