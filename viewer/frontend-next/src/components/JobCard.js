import { useState } from "../../vendor/react.js";
import { api } from "../lib/api.js";
import { brandDomain } from "../lib/brand.js";
import { companyName, formatRelativeTime, jobKey, jobMode } from "../lib/jobDisplay.js";
import { html } from "../lib/html.js";
import { useResource } from "../hooks/useResource.js";
import { useRun } from "../hooks/useRun.js";
import { useLocal, useToast, useUi } from "../state/context.js";
import { JobCardAnalysis } from "./JobCardAnalysis.js";

/** @param {{ job: any }} props */
export function JobCard({ job }) {
  const key = jobKey(job);
  const company = companyName(job);
  const ui = useUi();
  const local = useLocal();
  const { addToast } = useToast();
  const [runId, setRunId] = useState(null);
  const [failure, setFailure] = useState(null);
  const brand = useResource(() => brandDomain(company), { deps: [company] });

  const { status } = useRun(runId, (manifest) => {
    setRunId(null);
    if (manifest.status === "failed") {
      const reason = manifest.error || "unknown error";
      setFailure(reason);
      addToast({ message: `Analysis failed: ${reason}`, kind: "error" });
    } else {
      addToast({ message: `Analysis complete: ${job.title ?? "job"}`, kind: "success" });
    }
    ui.refreshJobs();
  });

  if (local.hiddenJobs.has(key)) return null;

  const isRunning = status === "pending" || status === "running" || runId !== null;
  const score5 = job.analysis?.score_5;
  const isFavorite = local.favoriteCompanies.has(company);
  const isVisited = local.visitedJobs.has(key);
  const age = formatRelativeTime(job.posted_at ?? job.first_seen_at);

  const handleAnalyze = async () => {
    setFailure(null);
    try {
      const data = await api.post("/match-runs", { job_keys: [key], mode: "claude" });
      setRunId(data.run_id);
      ui.refreshQueue();
      addToast({ message: "Analysis queued.", kind: "success" });
    } catch (error) {
      addToast({ message: `Failed to queue analysis: ${error.message}`, kind: "error" });
    }
  };

  return html`
    <article className="job-card" data-testid="job-card">
      <div className="job-card-main">
        ${brand.data &&
        html`<img className="job-card-logo" src=${`https://img.logo.dev/${brand.data}`} alt="" width=${32} height=${32} />`}
        <div className="job-card-body">
          <div className="job-card-title-row">
            <span className="job-card-company">${company}</span>
            <span className="pill job-card-provider">${job.provider}</span>
            ${isVisited && html`<span className="job-card-visited">visited</span>`}
          </div>
          <a
            className="job-card-title"
            href=${job.job_url ?? undefined}
            target="_blank"
            rel="noreferrer"
            onClick=${() => local.visitJob(key)}
          >
            ${job.title ?? "Untitled role"}
          </a>
          <div className="job-card-meta">
            <span className="pill">${jobMode(job.location, job.employment_type)}</span>
            ${job.location && html`<span>${job.location}</span>`}
            ${age && html`<span className="job-card-age">${age}</span>`}
            ${job.compensation && html`<span className="mono">${job.compensation}</span>`}
          </div>
        </div>
        <div className="job-card-actions">
          <button
            type="button"
            className="job-card-star"
            aria-pressed=${isFavorite}
            onClick=${() => {
              local.toggleFavoriteCompany(company);
              addToast({
                message: `${isFavorite ? "Removed" : "Added"} ${company} ${isFavorite ? "from" : "to"} favorites.`,
                kind: "neutral",
              });
            }}
            title="Favorite company"
          >
            ${isFavorite ? "★" : "☆"}
          </button>
          <button
            type="button"
            title="Hide job"
            onClick=${() => {
              local.hideJob(key);
              addToast({
                message: `Hid "${job.title ?? "job"}".`,
                kind: "neutral",
                undo: () => local.unhideJob(key),
              });
            }}
          >
            Hide
          </button>
          <button type="button" className="btn-analyze" onClick=${handleAnalyze} disabled=${isRunning}>
            ${isRunning ? "Analyzing…" : score5 !== undefined ? "Re-analyze" : "Analyze"}
          </button>
          ${score5 !== undefined &&
          html`<button type="button" className="job-card-score-badge" onClick=${() => ui.openPanel(key)}>
            ${score5.toFixed(1)}/5
          </button>`}
        </div>
      </div>
      ${failure && html`<p className="job-card-failure" role="alert">Analysis failed: ${failure}</p>`}
      ${job.analysis && html`<${JobCardAnalysis} analysis=${job.analysis} />`}
    </article>
  `;
}
