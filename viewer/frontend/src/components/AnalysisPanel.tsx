import { useEffect, useRef, useState } from "react";

import { useJob, useStartMatchRun } from "../api/hooks";
import { companyName } from "../lib/jobDisplay";
import { useLocalStore } from "../stores/localStore";
import { useUiStore } from "../stores/uiStore";
import type { Analysis } from "../types";
import { GapsList } from "./GapsList";
import { JDAccordion } from "./JDAccordion";
import { Scorecard } from "./Scorecard";
import { ToolMatch } from "./ToolMatch";

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
    ),
  );
}

export function AnalysisPanel() {
  const activePanelJobKey = useUiStore((s) => s.activePanelJobKey);
  const setActivePanelJobKey = useUiStore((s) => s.setActivePanelJobKey);
  const setPasteJDModalOpen = useUiStore((s) => s.setPasteJDModalOpen);
  const visitJob = useLocalStore((s) => s.visitJob);

  const jobQuery = useJob(activePanelJobKey);
  const startMatchRun = useStartMatchRun();
  const [activePipeline, setActivePipeline] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const isOpen = activePanelJobKey !== null;

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setActivePanelJobKey(null);
        return;
      }
      if (e.key === "Tab" && panelRef.current) {
        const focusable = focusableElements(panelRef.current);
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
  }, [isOpen, setActivePanelJobKey]);

  if (!isOpen) {
    return <div className="analysis-panel analysis-panel-closed" aria-hidden="true" />;
  }

  const job = jobQuery.data;
  const pipelineIds = job ? Object.keys(job.pipelines) : [];
  const pipeline = activePipeline ?? pipelineIds.find((p) => p === "claude-ensemble") ?? pipelineIds[0];
  const analysis: Analysis | null | undefined = pipeline ? job?.pipelines[pipeline]?.analysis : job?.analysis;

  const handleRerun = () => {
    if (!activePanelJobKey) return;
    startMatchRun.mutate({ job_keys: [activePanelJobKey], mode: "claude-ensemble" });
  };

  const handleApply = () => {
    if (!activePanelJobKey || !job?.job_url) return;
    visitJob(activePanelJobKey);
    window.open(job.job_url, "_blank", "noreferrer");
  };

  return (
    <>
      <div className="analysis-panel-backdrop" onClick={() => setActivePanelJobKey(null)} />
      <div
        className="analysis-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Job analysis"
        ref={panelRef}
        tabIndex={-1}
      >
        <button type="button" className="analysis-panel-close" onClick={() => setActivePanelJobKey(null)}>
          Close
        </button>

        {jobQuery.isLoading && <p>Loading…</p>}
        {jobQuery.isError && <p>Failed to load job.</p>}

        {job && (
          <>
            <h2>{job.title}</h2>
            <p className="analysis-panel-company">{companyName(job)}</p>

            {pipelineIds.length > 1 && (
              <div className="analysis-panel-tabs" role="tablist">
                {pipelineIds.map((id) => (
                  <button
                    key={id}
                    type="button"
                    role="tab"
                    aria-selected={pipeline === id}
                    onClick={() => setActivePipeline(id)}
                  >
                    {id}
                  </button>
                ))}
              </div>
            )}

            {!analysis && <p>Not yet analyzed.</p>}

            {analysis && (
              <>
                {analysis.score_5 !== undefined && (
                  <div className="analysis-panel-score">
                    <span className="analysis-panel-score-value">
                      {Math.round(analysis.score_5 * 20)}/100
                    </span>
                    <div className="scorecard-track">
                      <div
                        className="scorecard-fill"
                        style={{ width: `${(analysis.score_5 / 5) * 100}%` }}
                      />
                    </div>
                    {analysis.verdict && <span className="pill">{analysis.verdict}</span>}
                  </div>
                )}

                {analysis.role_summary?.tldr && <p>{analysis.role_summary.tldr}</p>}

                <Scorecard analysis={analysis} />

                <ToolMatch
                  tools={analysis.technical_tools_mentioned ?? []}
                  gaps={analysis.gaps ?? []}
                />

                <GapsList gaps={analysis.gaps ?? []} blockers={analysis.blockers ?? []} />

                {analysis.standout_differentiator && (
                  <p className="analysis-panel-standout">{analysis.standout_differentiator}</p>
                )}
              </>
            )}

            <div className="analysis-panel-actions">
              <button type="button" onClick={handleRerun} disabled={startMatchRun.isPending}>
                {startMatchRun.isPending ? "Re-running…" : "Re-run (full analysis)"}
              </button>
              <button type="button" onClick={handleApply} disabled={!job.job_url}>
                Apply
              </button>
            </div>

            <JDAccordion
              jobKey={activePanelJobKey!}
              onRequestPasteJD={() => setPasteJDModalOpen(true)}
            />
          </>
        )}
      </div>
    </>
  );
}
