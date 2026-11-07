import type { Job } from "../types";
import { JobCard } from "./JobCard";

interface Props {
  jobs: Job[];
  isLoading: boolean;
  isError: boolean;
}

// Server-side pagination already caps each page at a small, bounded item
// count (<=500), so plain rendering is used instead of @tanstack/react-virtual
// — the plan explicitly allows this as a simpler alternative.
export function JobList({ jobs, isLoading, isError }: Props) {
  if (isLoading) return <p>Loading jobs…</p>;
  if (isError) return <p>Failed to load jobs.</p>;
  if (jobs.length === 0) return <p>No jobs match the current filters.</p>;

  return (
    <div className="job-list">
      {jobs.map((job) => (
        <JobCard key={`${job.provider}|${job.source_key}|${job.job_id}`} job={job} />
      ))}
    </div>
  );
}
