import { useEffect, useRef, useState } from "../../vendor/react.js";
import { api } from "../lib/api.js";
import { html } from "../lib/html.js";
import { companyName, jobKey, parseJobKey } from "../lib/jobDisplay.js";
import { useResource } from "../hooks/useResource.js";
import { useRun } from "../hooks/useRun.js";
import { useLocal, useToast, useUi } from "../state/context.js";
import { GapsList } from "./GapsList.js";
import { JDAccordion } from "./JDAccordion.js";
import { Scorecard } from "./Scorecard.js";
import { ToolMatch } from "./ToolMatch.js";

const FOCUSABLE = 'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

/** Side panel with score, scorecard, verdict and actions for one job. */
export function AnalysisPanel() {
  const ui = useUi();
  const local = useLocal();
  const { addToast } = useToast();
  const activeKey = ui.panelJobKey;
  const isOpen = activeKey !== null;
  const panelRef = useRef(null);
  const [activePipeline, setActivePipeline] = useState(null);
  const [runId, setRunId] = useState(null);

  const jobQuery = useResource(
    () => (activeKey ? api.get("/job", { params: parseJobKey(activeKey) }) : Promise.resolve(null)),
    { deps: [activeKey] },
  );

  useRun(runId, (manifest) => {
    setRunId(null);
    if (manifest.status === "failed") {
      addToast({ message: `Re-run failed: ${manifest.error || "unknown error"}`, kind: "error" });
    } else {
      addToast({ message: "Re-run complete.", kind: "success" });
    }
    jobQuery.refresh();
    ui.refreshJobs();
  });

  useEffect(() => {
    if (!isOpen) return undefined;
    const handleKeyDown = (e) => {
      if (e.key === "Escape") {
        ui.closePanel();
        return;
      }
      if (e.key === "Tab" && panelRef.current) {
        const focusable = Array.from(panelRef.current.querySelectorAll(FOCUSABLE));
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    panelRef.current?.focus();
    return () => document.removeEventListener("keydown", handleKeyDown);
    // Re-focus only when the panel opens or switches job, not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, activeKey]);

  useEffect(() => setActivePipeline(null), [activeKey]);

  if (!isOpen) return html`<div className="analysis-panel analysis-panel-closed" aria-hidden="true"></div>`;

  const job = jobQuery.data && jobKey(jobQuery.data) === activeKey ? jobQuery.data : null;
  const pipelineIds = job ? Object.keys(job.pipelines) : [];
  const pipeline = activePipeline ?? pipelineIds.find((p) => p === "claude-ensemble") ?? pipelineIds[0];
  const analysis = pipeline ? job?.pipelines[pipeline]?.analysis : job?.analysis;
  const isRunning = runId !== null;

  const handleRerun = async () => {
    try {
      const data = await api.post("/match-runs", { job_keys: [activeKey], mode: "claude-ensemble" });
      setRunId(data.run_id);
      ui.refreshQueue();
      addToast({ message: "Re-run queued.", kind: "success" });
    } catch (error) {
      addToast({ message: `Failed to queue re-run: ${error.message}`, kind: "error" });
    }
  };

  const handleApply = () => {
    if (!job?.job_url) return;
    local.visitJob(activeKey);
    window.open(job.job_url, "_blank", "noreferrer");
  };

  return html`
    <div className="analysis-panel-backdrop" onClick=${ui.closePanel}></div>
    <div className="analysis-panel" role="dialog" aria-modal="true" aria-label="Job analysis" ref=${panelRef} tabIndex=${-1}>
      <button type="button" className="analysis-panel-close" onClick=${ui.closePanel}>Close</button>

      ${jobQuery.isLoading && html`<p>Loading…</p>`}
      ${jobQuery.error && html`<p>Failed to load job.</p>`}

      ${job &&
      html`
        <h2>${job.title}</h2>
        <p className="analysis-panel-company">${companyName(job)}</p>

        ${pipelineIds.length > 1 &&
        html`<div className="analysis-panel-tabs" role="tablist">
          ${pipelineIds.map(
            (id) => html`<button key=${id} type="button" role="tab" aria-selected=${pipeline === id} onClick=${() => setActivePipeline(id)}>
              ${id}
            </button>`,
          )}
        </div>`}

        ${!analysis && html`<p>Not yet analyzed.</p>`}

        ${analysis &&
        html`
          ${analysis.score_5 !== undefined &&
          html`<div className="analysis-panel-score">
            <span className="analysis-panel-score-value">${Math.round(analysis.score_5 * 20)}/100</span>
            <div className="scorecard-track">
              <div className="scorecard-fill" style=${{ width: `${(analysis.score_5 / 5) * 100}%` }}></div>
            </div>
            ${analysis.verdict && html`<span className="pill">${analysis.verdict}</span>`}
          </div>`}

          ${analysis.role_summary?.tldr && html`<p>${analysis.role_summary.tldr}</p>`}
          <${Scorecard} analysis=${analysis} />
          <${ToolMatch} tools=${analysis.technical_tools_mentioned ?? []} gaps=${analysis.gaps ?? []} />
          <${GapsList} gaps=${analysis.gaps ?? []} blockers=${analysis.blockers ?? []} />
          ${analysis.standout_differentiator &&
          html`<p className="analysis-panel-standout">${analysis.standout_differentiator}</p>`}
        `}

        <div className="analysis-panel-actions">
          <button type="button" onClick=${handleRerun} disabled=${isRunning}>
            ${isRunning ? "Re-running…" : "Re-run (full analysis)"}
          </button>
          <button type="button" onClick=${handleApply} disabled=${!job.job_url}>Apply</button>
        </div>

        <${JDAccordion} jobKey=${activeKey} onRequestPasteJD=${ui.openPasteJD} />
      `}
    </div>
  `;
}
